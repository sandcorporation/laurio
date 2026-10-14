#!/usr/bin/env python3
"""ghcr 에 쌓인 옛 이미지 버전을 지운다 — 패키지마다 최근 N 개만 남긴다(2026-10-02, Jenkinsfile.ghcr-prune).

    GH_TOKEN=… scripts/ci/ghcr_prune.py [--keep-images 12] [--keep-cache 10] [--dry-run]

**왜 있는가**(2026-09-20). 이미지 잡이 커밋마다 여섯 이미지를 올리는데 옛 버전을 지우는 것이
아무 데도 없어, 비공개 패키지 용량이 차서 **ghcr 쓰기가 403** 으로 막혔고 배포가 이틀 멈췄다(실측:
이미지 여섯 99 버전, 빌드 캐시 176 버전 — 캐시 쪽은 대부분 태그 없는 블롭이다). 쓰기가 막혀도
패키지 API 의 삭제는 열려 있다.

**되돌릴 수 없다.** 지운 버전은 복구되지 않는다. 돌고 있는 컨테이너는 영향이 없다 — 배포된
이미지는 이미 그 호스트에 있고, 잃는 것은 그 커밋으로 pull 해 되돌리는 길뿐이다(최근 N 개는
남는다). 커밋 하나가 패키지마다 두 버전(amd64·arm64)을 만든다. 빌드 캐시는 지금 이름의 태그
(`<서비스>-<아키텍처>`)만 늘 남기고 옛 이름은 지운다(`doomed_cache_versions`, #727) — 없으면 빌드가
느려질 뿐 깨지지 않는다.

**살아 있는 커밋의 버전은 순서와 무관하게 남긴다**(#705). 이미지 잡이 바뀌지 않은 서비스를 굽지 않고
옛 매니페스트에 커밋 태그만 더하므로(`scripts/ci/images.sh` — 같은 digest 라 같은 버전에 태그가 붙는다),
지금 배포된 커밋의 이미지가 **오래전에 만든 버전**일 수 있다 — 만든 순서로만 자르면 staging·prod 가
쓰는 이미지를 지운다. 그래서 `--protect-sha`(Jenkinsfile.ghcr-prune 이 main·staging·production 의 끝을
넘긴다)로 시작하는 태그를 가진 버전은 몇 번째든 남기고, 순서는 `updated_at`(태그가 붙으면 바뀐다)으로
센다. `ctx-<해시>-…` 태그만 남은 버전은 다른 버전과 똑같이 순서대로 지운다 — 지워지면 그 문맥을 다음에
한 번 다시 구울 뿐이다.

토큰은 classic PAT(`read:packages`·`delete:packages`)여야 한다 — fine-grained 토큰은 패키지 API 에
닿지 못한다. 예전에는 Actions 의 GITHUB_TOKEN 으로 했다(.github/workflows/ghcr-prune.yaml).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

ORG = "sandcorporation"
IMAGES = ["codemit-backend", "codemit-frontend", "codemit-operator", "codemit-classroom", "codemit-search", "codemit-pgbouncer"]
CACHE = "codemit-buildcache"
API = "https://api.github.com"


def call(method: str, path: str) -> tuple[int, object]:
    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def versions(package: str) -> list[dict]:
    found: list[dict] = []
    page = 1
    while True:
        code, batch = call("GET", f"/orgs/{ORG}/packages/container/{package}/versions?per_page=100&page={page}")
        if code != 200 or not isinstance(batch, list):
            raise RuntimeError(f"{package} 버전 목록을 못 읽었다({code}): {batch}")
        found.extend(batch)
        if len(batch) < 100:
            return found
        page += 1


def protected(version: dict, shas: list[str]) -> bool:
    tags = version.get("metadata", {}).get("container", {}).get("tags", [])
    return any(tag.startswith(sha) for tag in tags for sha in shas)


def doomed_versions(listed: list[dict], keep: int, shas: list[str]) -> list[dict]:
    """지울 버전 — 최근(태그가 붙은 때 기준) `keep` 개와 살아 있는 커밋의 태그를 가진 것을 뺀 나머지."""
    ordered = sorted(listed, key=lambda v: max(v["created_at"], v.get("updated_at") or ""), reverse=True)
    return [v for v in ordered[keep:] if not protected(v, shas)]


# 빌드 캐시의 **지금 이름**(#712 — `scripts/ci/images.sh` 의 `codemit-buildcache:<서비스>-<아키텍처>`).
LIVE_CACHE_TAG = re.compile(r"^(" + "|".join(i.removeprefix("codemit-") for i in IMAGES) + r")-(amd64|arm64)$")


def doomed_cache_versions(listed: list[dict], keep: int) -> list[dict]:
    """빌드 캐시에서 지울 버전(#727).

    - 지금 이름의 태그(`<서비스>-<아키텍처>`, 여섯 × 둘 = 열둘)를 가진 버전은 순서와 무관하게 남긴다 —
      태그 하나가 버전 하나라 많아야 열둘이고, 순서로 자르면 드물게 굽는 search·pgbouncer 의 살아 있는
      캐시가 `keep`(10) 밖으로 밀려 매번 지워졌다(2026-10-15 실측: 살아 있는 태그 12 > 10).
    - 그 밖의 태그만 가진 버전은 순서와 무관하게 지운다 — 옛 이름 `<앱>-staging`·`<앱>-prod`(#711 전,
      환경마다 따로 굽던 때)는 다시 쓰이지 않는데, 순서로만 자르면 새 이름 캐시보다 최근에 갱신된 동안은
      남았다.
    - 태그 없는 버전(덮어쓴 캐시의 옛 매니페스트)은 예전처럼 최근 `keep` 개만 남긴다.
    """
    def tags(v: dict) -> list[str]:
        return v.get("metadata", {}).get("container", {}).get("tags", [])

    live = [v for v in listed if any(LIVE_CACHE_TAG.match(t) for t in tags(v))]
    stale = [v for v in listed if tags(v) and v not in live]
    untagged = [v for v in listed if not tags(v)]
    return stale + doomed_versions(untagged, keep, [])


def prune(package: str, keep: int, dry_run: bool, shas: list[str]) -> int:
    listed = versions(package)
    doomed = doomed_cache_versions(listed, keep) if package == CACHE else doomed_versions(listed, keep, shas)
    print(f"{package}: 전체 {len(listed)} · 남김 {len(listed) - len(doomed)} · 지움 {len(doomed)}")
    failures = 0
    for version in doomed:
        tags = ",".join(version["metadata"]["container"]["tags"]) or "<태그없음>"
        if dry_run:
            print(f"  (드라이런) {version['created_at'][:16]} {tags}")
            continue
        code, detail = call("DELETE", f"/orgs/{ORG}/packages/container/{package}/versions/{version['id']}")
        if code != 204:
            print(f"  지우지 못했다 {version['id']} {tags}: {code} {detail}", file=sys.stderr)
            failures += 1
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep-images", type=int, default=12)
    parser.add_argument("--keep-cache", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--protect-sha", action="append", default=[], help="이 커밋의 태그를 가진 버전은 남긴다(여러 번)")
    args = parser.parse_args()
    # 짧은 sha 로 지키면 엉뚱한 태그까지 지킨다 — 40자만 받는다.
    shas = [s for s in (x.strip() for x in args.protect_sha) if len(s) == 40]
    print("지키는 커밋: " + (" ".join(s[:12] for s in shas) or "없음"))
    failures = 0
    for package in IMAGES:
        failures += prune(package, args.keep_images, args.dry_run, shas)
    failures += prune(CACHE, args.keep_cache, args.dry_run, [])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
