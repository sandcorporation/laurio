#!/usr/bin/env python3
"""`main` 에 들어온 커밋이 고친 GlitchTip 이슈를 해결 표시한다 (2026-09-18).

CI 의 `glitchtip-resolve` 잡이 부른다. 읽는 것은 **커밋 메시지의 마지막 줄 형식**
하나다:

    GlitchTip: 42

`.claude/skills/glitchtip-triage/` 를 따르는 세션이 그 줄을 적고 push 하면, 여기서
이슈를 `resolved` 로 돌린다.

**왜 세션이 직접 표시하지 않는가.** 세션은 자기 수정이 옳은지 판정할 처지가 아니다 —
「고친 것 같다」와 「고쳤다」를 가르는 것은 CI 다. 그래서 세션에는 읽기 전용 토큰만
주고, 표시는 `main` 의 CI 가 초록으로 끝난 뒤에만 일어나게 했다. 자동 진단이 아무것도
고치지 못한 경우 이슈는 미해결로 남고, 다음에 사람이 본다.

**이 잡이 없으면 무엇이 조용히 깨지는가.** 이슈가 영원히 미해결로 남는다 — 그런데
클레임 코멘트 때문에 다시 집히지도 않으므로, 자동화가 「고쳤는데 아무 표시가 없는」
상태를 계속 쌓는다. 그래서 이 스크립트는 **무엇을 읽었는지 항상 stdout 에 적는다** —
표시할 것이 없었다는 사실도 적는다. 「잡이 초록이었다」가 「표시가 됐다」를 뜻하지
않으므로, 확인할 자리는 그 로그 한 줄이다.

토큰은 `GLITCHTIP_TOKEN_FOR_AUTOMATION`(스코프 `event:write`) 하나다. 없으면
**아무 일도 하지 않고 성공으로 끝낸다** — 포크 PR 처럼 시크릿이 없는 실행에서 잡이
빨개지는 것은 뜻이 없다.

사용법:

    scripts/glitchtip_resolve.py <base-sha> <head-sha>
    scripts/glitchtip_resolve.py --dry-run <base-sha> <head-sha>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

GLITCHTIP_URL = os.environ.get("GLITCHTIP_URL", "https://glitchtip.honeycombpizza.link")

#: **줄 전체**가 이 모양일 때만 읽는다 — 본문 산문에 섞인 「GlitchTip: 이슈를 봤는데
#: 원인은 다른 곳이었다」 같은 문장을 이슈 번호로 착각하지 않게.
#:
#: 대소문자와 앞쪽 공백은 받아 준다. 둘 다 오탐을 만들 수 없는 자리이고, 여기서 가장
#: 나쁜 실패는 「형식이 살짝 달라 조용히 아무 일도 안 한다」다 — 그러면 이슈가 미해결로
#: 남는데 클레임 때문에 다시 집히지도 않는다.
TRAILER = re.compile(r"^[ \t]*GlitchTip:[ \t]*(\d+)[ \t]*$", re.MULTILINE | re.IGNORECASE)

TIMEOUT_SECONDS = 20


def _issue_ids(base: str, head: str) -> list[str]:
    """`base..head` 의 커밋 메시지에서 이슈 번호를 순서대로, 중복 없이 모은다."""

    log = subprocess.run(
        ["git", "log", "--format=%B%x00", f"{base}..{head}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    seen: list[str] = []
    for message in log.split("\0"):
        for issue_id in TRAILER.findall(message):
            if issue_id not in seen:
                seen.append(issue_id)
    return seen


def _resolve(issue_id: str, token: str) -> tuple[int, str]:
    request = urllib.request.Request(
        f"{GLITCHTIP_URL}/api/0/issues/{issue_id}/",
        data=json.dumps({"status": "resolved"}).encode("utf-8"),
        method="PUT",
    )
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", help="이 커밋 다음부터 본다")
    parser.add_argument("head", help="이 커밋까지 본다")
    parser.add_argument("--dry-run", action="store_true", help="표시하지 않고 무엇을 표시할지만 적는다")
    args = parser.parse_args()

    issue_ids = _issue_ids(args.base, args.head)
    if not issue_ids:
        print("GlitchTip: 줄을 가진 커밋이 없다 — 표시할 것이 없다")
        return 0

    print(f"표시할 이슈: {', '.join(issue_ids)}")

    token = os.environ.get("GLITCHTIP_TOKEN_FOR_AUTOMATION", "").strip()
    if not token:
        # 시크릿이 없는 실행(포크 PR 등)에서 빨개지는 것은 뜻이 없다 — 무엇을
        # 못 했는지만 남긴다.
        print("GLITCHTIP_TOKEN_FOR_AUTOMATION 이 없다 — 표시하지 않고 넘어간다")
        return 0

    failures = 0
    for issue_id in issue_ids:
        if args.dry_run:
            print(f"  (드라이런) 이슈 {issue_id} → resolved")
            continue
        status, detail = _resolve(issue_id, token)
        if status == 200:
            print(f"  이슈 {issue_id} → resolved")
        else:
            # **잡을 실패시키지 않는다**(아래 return 0). 이미 머지된 수정을 되돌릴
            # 수는 없고, 표시가 안 된 것은 다음 사람이 GlitchTip 에서 본다 —
            # 배포 파이프라인을 세울 일이 아니다.
            print(f"  이슈 {issue_id} 표시 실패: {status} {detail}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"{failures}건을 표시하지 못했다 — GlitchTip 에서 손으로 닫는다", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
