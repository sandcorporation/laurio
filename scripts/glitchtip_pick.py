#!/usr/bin/env python3
"""GlitchTip 에서 **진단할 오류 하나**를 집는다 — Orca automation 의 precheck (2026-09-18).

`orca automations create --precheck` 가 부르는 문이다. **종료 코드가 전부다**:

- `0` — 집었다. automation 이 세션을 띄운다. 집은 이슈는 stdout 에 JSON 한 줄로 적고,
  `--claim-file` 이 주어지면 그 파일에도 남긴다 — **세션이 읽을 자리**다. automation 은
  precheck 의 stdout 을 세션에 넘겨주지 않고, 세션은 매 실행 새 워크트리에서 도므로 그
  워크트리 안의 경로로는 약속이 성립하지 않는다. 그래서 자리를 워크트리 **밖**의 고정
  경로로 둔다(동시 실행이 하나라 덮어써도 안전하다).
- `0 이 아님` — 집을 것이 없거나 지금 돌 때가 아니다. automation 이 「건너뜀」으로
  기록하고 **세션을 아예 띄우지 않는다** — 조용한 분에는 비용이 0 이다.

**왜 에이전트가 아니라 스크립트가 고르는가.** 이슈 제목·스택트레이스는 공개 DSN 으로
누구나 넣을 수 있는 값이다(GlitchTip MCP 서버가 직접 그 위험을 경고한다). 무엇을 집을지와
클레임을 남기는 쓰기는 **읽고 판단하는 에이전트 밖에서** 끝내고, 에이전트에게는 읽기 전용
토큰만 준다. 그래서 인젝션된 텍스트가 GlitchTip 을 조종하는 길이 없다.

**클레임을 GlitchTip 코멘트로 남기는 이유.** 이슈 목록 응답에 `numComments` 가 이미 있어서
「손 댄 적 있나」를 목록 API 한 번으로 알 수 있다 — 새 상태 상자를 만들지 않아도 되고,
사람이 GlitchTip 화면에서 같은 사실을 본다. 실측으로 코멘트를 달면 `numComments` 가 그
자리에서 0→1 이 된다(2026-09-18 확인).

토큰 둘을 가른다(`.env`):

- `GLITCHTIP_TOKEN_FOR_AUTOMATION` — `event:write` 하나. 이 스크립트가 쓴다.
  `project:read` 를 일부러 주지 않았다 — 알림 규칙 조회가 Discord 웹훅 URL 을 평문으로
  돌려주는데, 그 경로를 막아 두려는 것이다(실측: 403).
- `GLITCHTIP_TOKEN` — 읽기 전용. 세션(에이전트)과 MCP 가 쓴다. 이 스크립트는 쓰지 않는다.

사용법:

    scripts/glitchtip_pick.py --claim-file ~/.codemit/glitchtip-current.json   # precheck
    scripts/glitchtip_pick.py --dry-run            # 클레임 없이 무엇이 집힐지만 본다
    scripts/glitchtip_pick.py --dry-run --any-environment --any-status
                                                   # 필터를 풀어 선별 로직만 눈으로 확인

**precheck 는 이 스크립트를 절대 경로로 부른다.** automation 의 precheck 가 어느
디렉터리에서 도는지는 약속되지 않았고, 이 스크립트는 토큰을 **자기 위치 기준**의 `.env`
에서 읽는다 — 절대 경로로 부르면 주 워크트리의 `.env` 와 주 워크트리에 커밋된 이 파일이
쓰인다. 즉 이 스크립트를 고치려면 `main` 에 머지해야 스케줄러가 본다(그게 맞는 동작이다).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GLITCHTIP_URL = os.environ.get("GLITCHTIP_URL", "https://glitchtip.honeycombpizza.link")
ORG_SLUG = os.environ.get("GLITCHTIP_ORG", "codemit")

#: 이 환경의 오류만 집는다. staging·dev 는 대개 사람이 그 자리에서 보고 있다.
TARGET_ENVIRONMENT = "production"

#: 클레임 코멘트의 첫 줄 — 사람이 GlitchTip 에서 보고 「자동화가 집었다」를 알 수 있게.
CLAIM_PREFIX = "[자동 진단]"

TIMEOUT_SECONDS = 20


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def _load_env_token() -> str:
    """쓰기 토큰을 환경변수에서, 없으면 루트 `.env` 에서 읽는다.

    automation 의 precheck 는 셸 초기화를 거치지 않을 수 있어 `.env` 를 직접 읽는다 —
    이 저장소의 `.env` 는 gitignore 대상이고 토큰이 사는 자리다.
    """

    token = os.environ.get("GLITCHTIP_TOKEN_FOR_AUTOMATION", "").strip()
    if token:
        return token

    env_path = _repo_root() / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            match = re.match(r"^\s*GLITCHTIP_TOKEN_FOR_AUTOMATION\s*=\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip().strip("'\"")
    return ""


def _request(path: str, token: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    url = f"{GLITCHTIP_URL}/api/0/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw
    except (urllib.error.URLError, TimeoutError) as exc:
        # GlitchTip 이 안 떠 있거나 네트워크가 끊긴 것은 **집을 것이 없는 것과 다르다** —
        # 호출부가 구별할 수 있게 예외로 올린다.
        raise RuntimeError(f"GlitchTip 에 닿지 못했다: {exc}") from exc


def _a_session_holds_the_lock(lock_path: pathlib.Path, ttl_minutes: float) -> bool:
    """이미 도는 진단 세션이 있으면 집지 않는다 — 동시 하나가 여기서 지켜진다.

    **왜 필요한가.** 매분 트리거인데 세션은 10분을 넘긴다. 막지 않으면 매분 새 워크트리와
    새 dev 스택이 뜬다 — 사람도 같이 쓰는 머신이고, 오늘 워크트리 일곱을 치우며 그 부하를
    실측했다.

    **왜 `orca automations runs` 를 보지 않는가.** 그 응답의 status 값 목록이 CLI 도움말
    에도 스킬 문서에도 없다(2026-09-18 확인). 「running·pending」 같은 문자열을 추측해 두면
    실제 값이 다를 때 이 함수가 **항상 False 를 돌려주고도 조용하다** — 가드가 있는 줄 알고
    없는 상태가 된다. 그래서 우리가 쓰고 우리가 읽는 파일 하나로 잠근다.

    **수명이 둘로 지켜진다.** 정상 종료는 세션이 `.claude/skills/glitchtip-triage` 의
    마지막 단계에서 이 파일을 지운다(그러면 다음 분에 바로 다음 오류를 집는다). 세션이
    죽어 그 단계에 못 가면 `ttl_minutes` 가 지나 저절로 풀린다 — 잠금이 영원히 남아
    자동화가 조용히 멈추는 것이 이 배선의 가장 나쁜 실패 모양이라 그렇게 했다.
    """

    if not lock_path.exists():
        return False
    age_minutes = (time.time() - lock_path.stat().st_mtime) / 60
    if age_minutes < ttl_minutes:
        return True
    # 수명이 지난 잠금은 남이 죽어 두고 간 것이다 — 걷어내고 우리가 집는다.
    lock_path.unlink(missing_ok=True)
    return False


def _environments_of(issue: dict) -> set[str]:
    """이 이슈가 **어느 환경들에서** 났는가.

    이슈 목록 응답에는 environment 가 없다 — 태그로 물어봐야 한다. GlitchTip 6.2.6 의
    알림 규칙에는 environment 필터가 아예 없어서(상위 브랜치에만 있다) 이 판정을 여기서
    한다.

    **하나가 아니라 집합이다.** 같은 예외가 staging 과 prod 에서 함께 나면 GlitchTip 은
    이슈 하나로 묶고 태그에 두 값을 다 담는다(실측: issue 1 = `['production',
    'staging']`, 2026-09-18). 그래서 「첫 값이 production 인가」로 보면 안 된다 —
    `topValues` 의 순서가 빈도순이라는 보장이 문서에 없고, prod 에서 난 오류가 staging
    이 먼저 적혔다는 이유로 조용히 빠진다. 「prod 에서 난 적이 있는가」로 본다.
    """

    status, tags = _request(f"issues/{issue['id']}/tags/", _TOKEN)
    if status != 200 or not isinstance(tags, list):
        return set()
    for tag in tags:
        if tag.get("key") != "environment":
            continue
        return {value.get("value") for value in (tag.get("topValues") or [])}
    return set()


def _pick(args: argparse.Namespace) -> dict | None:
    query_parts = [] if args.any_status else ["is:unresolved"]
    params = {
        "limit": "25",
        # 처음 본 순서대로 집는다 — 오래 방치된 것이 먼저다.
        "sort": "first_seen",
    }
    if query_parts:
        params["query"] = " ".join(query_parts)

    status, issues = _request(
        f"organizations/{ORG_SLUG}/issues/?{urllib.parse.urlencode(params)}", _TOKEN
    )
    if status != 200 or not isinstance(issues, list):
        raise RuntimeError(f"이슈 목록을 받지 못했다: {status} {str(issues)[:200]}")

    for issue in issues:
        # 이미 손 댄 것은 건너뛴다 — 클레임이 곧 이 값이다.
        if not args.any_claimed and int(issue.get("numComments") or 0) > 0:
            continue
        if not args.any_environment and TARGET_ENVIRONMENT not in _environments_of(issue):
            continue
        return issue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="클레임 코멘트를 달지 않는다")
    parser.add_argument("--any-environment", action="store_true", help="production 필터를 끈다")
    parser.add_argument("--any-status", action="store_true", help="미해결 필터를 끈다")
    parser.add_argument("--any-claimed", action="store_true", help="이미 손 댄 것도 후보에 넣는다")
    parser.add_argument("--claim-file", default="", help="집은 이슈를 남길 JSON 파일 경로")
    parser.add_argument("--lock-file", default="~/.codemit/glitchtip-lock", help="동시 실행 잠금 파일")
    parser.add_argument("--lock-ttl-minutes", type=float, default=45.0, help="잠금이 저절로 풀리는 시간")
    parser.add_argument("--skip-lock", action="store_true", help="잠금을 보지도 걸지도 않는다")
    args = parser.parse_args()

    lock_path = pathlib.Path(args.lock_file).expanduser()

    global _TOKEN
    _TOKEN = _load_env_token()
    if not _TOKEN:
        print("GLITCHTIP_TOKEN_FOR_AUTOMATION 이 없다 — .env 나 환경변수에 넣어야 한다", file=sys.stderr)
        return 2

    holds_lock = not args.skip_lock and not args.dry_run
    if holds_lock and _a_session_holds_the_lock(lock_path, args.lock_ttl_minutes):
        print(f"진단 세션이 이미 돌고 있다({lock_path}) — 이번 분은 건너뛴다", file=sys.stderr)
        return 1

    try:
        issue = _pick(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if issue is None:
        print("집을 오류가 없다", file=sys.stderr)
        return 1

    picked = {
        "id": issue["id"],
        "shortId": issue.get("shortId"),
        "title": issue.get("title"),
        "culprit": issue.get("culprit"),
        "level": issue.get("level"),
        "count": issue.get("count"),
        "project": (issue.get("project") or {}).get("slug"),
        "permalink": issue.get("permalink"),
        "firstSeen": issue.get("firstSeen"),
        "lastSeen": issue.get("lastSeen"),
        # 여러 환경에 걸칠 수 있다 — `_environments_of` 의 docstring 참고.
        "environments": sorted(_environments_of(issue)),
        # 어느 커밋의 코드에서 났는가 — `SENTRY_RELEASE` 가 커밋 SHA 다.
        "release": ((issue.get("lastRelease") or {}) or {}).get("version"),
    }

    if not args.dry_run:
        status, _ = _request(
            f"issues/{issue['id']}/comments/",
            _TOKEN,
            method="POST",
            body={"data": {"text": f"{CLAIM_PREFIX} 이 오류를 자동 진단이 집었습니다. 결과를 이 이슈에 다시 적습니다."}},
        )
        if status != 201:
            # 클레임에 실패하면 **집지 않는다** — 클레임 없이 진단하면 다음 분이 같은
            # 이슈를 또 집어 세션이 겹친다.
            print(f"클레임 코멘트에 실패했다({status}) — 이번 분은 건너뛴다", file=sys.stderr)
            return 1

    if args.claim_file:
        claim_file = pathlib.Path(args.claim_file).expanduser()
        claim_file.parent.mkdir(parents=True, exist_ok=True)
        claim_file.write_text(json.dumps(picked, ensure_ascii=False, indent=2))

    if holds_lock:
        # **클레임이 성공한 뒤에만 잠근다.** 앞에서 실패해 `return 1` 한 경로에 잠금이
        # 남으면, 세션이 뜨지도 않았는데 다음 45분이 통째로 막힌다.
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(f"{picked['id']}\n")

    print(json.dumps(picked, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
