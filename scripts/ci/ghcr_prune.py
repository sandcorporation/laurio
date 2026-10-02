#!/usr/bin/env python3
"""ghcr 에 쌓인 옛 이미지 버전을 지운다 — 패키지마다 최근 N 개만 남긴다(2026-10-02, Jenkinsfile.ghcr-prune).

    GH_TOKEN=… scripts/ci/ghcr_prune.py [--keep-images 12] [--keep-cache 10] [--dry-run]

**왜 있는가**(2026-09-20). 이미지 잡이 커밋마다 여섯 이미지를 올리는데 옛 버전을 지우는 것이
아무 데도 없어, 비공개 패키지 용량이 차서 **ghcr 쓰기가 403** 으로 막혔고 배포가 이틀 멈췄다(실측:
이미지 여섯 99 버전, 빌드 캐시 176 버전 — 캐시 쪽은 대부분 태그 없는 블롭이다). 쓰기가 막혀도
패키지 API 의 삭제는 열려 있다.

**되돌릴 수 없다.** 지운 버전은 복구되지 않는다. 돌고 있는 컨테이너는 영향이 없다 — 배포된
이미지는 이미 그 호스트에 있고, 잃는 것은 그 커밋으로 pull 해 되돌리는 길뿐이다(최근 N 개는
남는다). 커밋 하나가 패키지마다 두 버전(staging·prod)을 만든다. 빌드 캐시는 더 적게 남긴다 —
없으면 빌드가 느려질 뿐 깨지지 않는다.

토큰은 classic PAT(`read:packages`·`delete:packages`)여야 한다 — fine-grained 토큰은 패키지 API 에
닿지 못한다. 예전에는 Actions 의 GITHUB_TOKEN 으로 했다(.github/workflows/ghcr-prune.yaml).
"""

from __future__ import annotations

import argparse
import json
import os
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


def prune(package: str, keep: int, dry_run: bool) -> int:
    listed = sorted(versions(package), key=lambda v: v["created_at"], reverse=True)
    doomed = listed[keep:]
    print(f"{package}: 전체 {len(listed)} · 남김 {min(keep, len(listed))} · 지움 {len(doomed)}")
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
    args = parser.parse_args()
    failures = 0
    for package in IMAGES:
        failures += prune(package, args.keep_images, args.dry_run)
    failures += prune(CACHE, args.keep_cache, args.dry_run)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
