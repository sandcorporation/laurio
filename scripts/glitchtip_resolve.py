#!/usr/bin/env python3
"""`main` 에 들어온 커밋이 고친 GlitchTip 이슈를 해결 표시한다 (2026-09-18).

Jenkins 배포 잡 `codemit/deploy` 의 이미지 굽기(`scripts/ci/build-images.sh`)가 직전 성공 배포 → 배포할 커밋 범위로
부른다(2026-11-05 #873 — 그 전에는 열차 `codemit/ci-train` 의 병합 단계가 PR 범위로(2026-10-02 — 그 전에는 main 의 Actions 잡이 `auto` 범위로 불렀다). 읽는 것은 **커밋 메시지의 마지막 줄 형식**
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

GLITCHTIP_URL = os.environ.get("GLITCHTIP_URL", "").rstrip("/")  # 자체 호스팅 GlitchTip 주소 — 저장소에 적지 않는다(#930)

#: **줄 전체**가 이 모양일 때만 읽는다 — 본문 산문에 섞인 「GlitchTip: 이슈를 봤는데
#: 원인은 다른 곳이었다」 같은 문장을 이슈 번호로 착각하지 않게.
#:
#: 대소문자와 앞쪽 공백은 받아 준다. 둘 다 오탐을 만들 수 없는 자리이고, 여기서 가장
#: 나쁜 실패는 「형식이 살짝 달라 조용히 아무 일도 안 한다」다 — 그러면 이슈가 미해결로
#: 남는데 클레임 때문에 다시 집히지도 않는다.
TRAILER = re.compile(r"^[ \t]*GlitchTip:[ \t]*(\d+)[ \t]*$", re.MULTILINE | re.IGNORECASE)

#: 표시 코멘트의 첫 줄 — 사람이 GlitchTip 에서 「기다리는 중」임을 알 수 있게.
ACK_PREFIX = "[자동 진단]"

TIMEOUT_SECONDS = 20

#: 이 스크립트를 부르는 CI 잡 이름 — 직전 성공 지점을 찾을 때 이 이름으로 잡을 가린다.
JOB_NAME = "glitchtip-resolve"


def _last_resolved_head(token: str, repo: str, current_run_id: str, head: str) -> str | None:
    """**직전에 이 잡이 실제로 성공한 실행**의 head sha 를 돌려준다(2026-09-22).

    **왜 `github.event.before` 가 아닌가.** 그 값은 「직전 push 의 끝」이다. 그런데
    GitHub 은 한 concurrency 그룹에 pending 을 하나만 두어서, 짧은 간격으로 셋을 밀면
    **가운데 실행이 잡 하나도 못 돌고 취소된다.** 다음 실행의 범위 `before..sha` 는
    가운데 커밋을 포함하지 않으므로 그 커밋의 `GlitchTip:` 줄은 **영영 읽히지 않는다.**
    실제로 그렇게 났다 — 자동 진단이 2분 간격으로 셋을 밀어(14:22·14:24·14:26)
    가운데 오류 75 가 다음 초록 실행이 그 수정을 포함했는데도 닫히지 않았다.

    **왜 「직전 초록 실행」도 아닌가.** 테스트는 초록인데 다른 잡(e2e 등)이 빨개
    실행 전체가 실패한 경우, **이 잡은 이미 돌아서 그 오류를 닫았다.** 그 실행을
    기준에서 빼면 다음 초록 실행이 같은 커밋을 다시 읽고, 그 사이 재발한 오류를
    **다시 해결로 덮어 재발을 숨긴다** — 넓은 창을 피한 이유가 바로 그것이었다.
    그래서 기준은 「실행이 초록이었는가」가 아니라 **「이 잡이 성공했는가」**다.

    이렇게 하면 커밋 하나는 **이 잡이 성공한 실행 하나에만** 속한다 — 취소된 커밋은
    다음 성공이 줍고, 이미 읽힌 커밋은 다시 읽히지 않는다.

    찾지 못하면(첫 실행, API 실패) None — 호출부가 옛 방식으로 물러난다.
    """

    import urllib.parse

    def get(path: str) -> dict | None:
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}")
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"GitHub API 에 닿지 못했다({path}): {exc}", file=sys.stderr)
            return None

    query = urllib.parse.urlencode({"branch": "main", "status": "completed", "per_page": "30"})
    listing = get(f"actions/workflows/ci.yaml/runs?{query}")
    if not listing:
        return None

    for run in listing.get("workflow_runs") or []:
        if str(run.get("id")) == str(current_run_id):
            continue
        candidate = run.get("head_sha") or ""
        # **이 커밋보다 앞선 실행만** 기준이 될 수 있다. 목록은 최신순이라 나중 실행이
        # 먼저 나오는데, 그것을 집으면 범위가 거꾸로 되어 아무것도 읽지 않는다. 실시간
        # CI 에서는 동시성 때문에 나중 실행이 끝나 있을 수 없지만, 조상 검사를 여기서
        # 하면 과거 실행을 재현해 시험할 때도 같은 답이 나온다.
        if not candidate or candidate == head or not _is_ancestor(candidate, head):
            continue
        jobs = get(f"actions/runs/{run['id']}/jobs?per_page=100")
        if not jobs:
            continue
        for job in jobs.get("jobs") or []:
            if job.get("name") == JOB_NAME and job.get("conclusion") == "success":
                return run.get("head_sha")
    return None


def _is_ancestor(older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            capture_output=True,
        ).returncode
        == 0
    )


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


def _call(path: str, token: str, *, method: str, body: dict) -> tuple[int, str]:
    if not GLITCHTIP_URL:
        raise SystemExit("GLITCHTIP_URL 이 비어 있다 — 자체 호스팅 GlitchTip 주소를 환경변수로 준다")
    request = urllib.request.Request(
        f"{GLITCHTIP_URL}/api/0/{path}",
        data=json.dumps(body).encode("utf-8"),
        method=method,
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


def _resolve(issue_id: str, token: str) -> tuple[int, str]:
    return _call(f"issues/{issue_id}/", token, method="PUT", body={"status": "resolved"})


def _acknowledge(issue_id: str, token: str, sha: str) -> tuple[int, str]:
    """「수정을 push 했다 — CI 를 기다리는 중」을 코멘트로 남긴다.

    **왜 필요한가.** 해결 표시는 `needs: test` 뒤에 오므로 push 와 GlitchTip 사이에
    5~10분이 있다(실측: 커밋 05:03 → 표시 05:11). 그 사이 화면은 **「아직 안 닫혔다」와
    「배선이 고장났다」를 구별해 주지 않는다** — 실제로 그 질문을 받았다(2026-09-18).
    이 코멘트가 그 갈림을 화면에 적는다.

    **부작용을 알고 쓴다.** 코멘트가 곧 클레임이라(`glitchtip_pick.py` 의 「판정은
    내용이 아니라 개수다」), 이 표시가 달린 오류는 나중에 재발해도 자동 진단이 집지
    않는다. 자동 진단이 고친 오류는 이미 클레임돼 있으니 달라지는 것이 없고, **사람이
    손으로 `GlitchTip:` 줄을 적은 경우에만** 새로 그 상태가 된다 — 그 오류는 사람이
    보고 있다는 뜻이므로 받아들일 만한 대가로 봤다.
    """

    text = (
        f"{ACK_PREFIX} 이 오류를 고친 수정이 `main` 에 들어갔습니다(커밋 `{sha[:12]}`). "
        "CI 가 초록으로 끝나면 이 오류가 해결로 표시됩니다 — 그때까지는 열린 채로 있는 "
        "것이 정상입니다."
    )
    return _call(f"issues/{issue_id}/comments/", token, method="POST", body={"data": {"text": text}})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "base",
        help="이 커밋 다음부터 본다. `auto` 면 직전에 이 잡이 성공한 실행의 커밋부터 본다(CI 용)",
    )
    parser.add_argument("head", help="이 커밋까지 본다")
    parser.add_argument(
        "--fallback-base",
        default="",
        help="`auto` 가 직전 성공 지점을 찾지 못했을 때 쓸 시작점(CI 는 push 의 before 를 준다)",
    )
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 무엇을 할지만 적는다")
    parser.add_argument(
        "--ack",
        action="store_true",
        help="해결 표시 대신 「수정을 push 했다」 코멘트만 남긴다 (CI 의 이른 잡이 쓴다)",
    )
    args = parser.parse_args()

    base = args.base
    if base == "auto":
        # CI 에서만 쓴다 — 저장소·실행 id·토큰은 Actions 가 준다.
        found = _last_resolved_head(
            os.environ.get("GITHUB_TOKEN", ""),
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
            args.head,
        )
        if found and _is_ancestor(found, args.head):
            base = found
            print(f"범위: 직전에 이 잡이 성공한 {found[:12]} 이후")
        else:
            # **옛 범위(push 의 before)로 물러난다** — 옛 방식보다 나빠지지 않으려는 것이다.
            # 처음에는 「이 커밋 하나만」으로 물러났는데, 권한이 없어 실제로 물러났을 때
            # push 하나의 여러 커밋 중 마지막만 읽어 고치기 전보다 좁았다(2026-09-22).
            # before 가 없거나(0000…, 첫 push) 이 저장소에 없으면 그때만 이 커밋 하나다.
            fallback = args.fallback_base.strip()
            usable = (
                fallback
                and set(fallback) != {"0"}
                and subprocess.run(
                    ["git", "cat-file", "-e", f"{fallback}^{{commit}}"], capture_output=True
                ).returncode == 0
            )
            base = fallback if usable else f"{args.head}~1"
            reason = "없음" if not found else "조상 아님"
            where = f"push 의 before({fallback[:12]}) 이후" if usable else "이 커밋 하나만"
            print(f"범위: 직전 성공 지점을 찾지 못해({reason}) {where} 본다")

    issue_ids = _issue_ids(base, args.head)
    if not issue_ids:
        print("GlitchTip: 줄을 가진 커밋이 없다 — 표시할 것이 없다")
        return 0

    verb = "표시" if not args.ack else "알림"
    print(f"{verb}할 이슈: {', '.join(issue_ids)}")

    token = os.environ.get("GLITCHTIP_TOKEN_FOR_AUTOMATION", "").strip()
    if not token:
        # 시크릿이 없는 실행(포크 PR 등)에서 빨개지는 것은 뜻이 없다 — 무엇을
        # 못 했는지만 남긴다.
        print("GLITCHTIP_TOKEN_FOR_AUTOMATION 이 없다 — 표시하지 않고 넘어간다")
        return 0

    failures = 0
    for issue_id in issue_ids:
        if args.dry_run:
            print(f"  (드라이런) 이슈 {issue_id} → {'코멘트' if args.ack else 'resolved'}")
            continue
        if args.ack:
            status, detail = _acknowledge(issue_id, token, args.head)
            ok, done = 201, "수정 push 됨을 적었다"
        else:
            status, detail = _resolve(issue_id, token)
            ok, done = 200, "resolved"
        if status == ok:
            print(f"  이슈 {issue_id} → {done}")
        else:
            # **잡을 실패시키지 않는다**(아래 return 0). 이미 머지된 수정을 되돌릴
            # 수는 없고, 표시가 안 된 것은 다음 사람이 GlitchTip 에서 본다 —
            # 배포 파이프라인을 세울 일이 아니다.
            print(f"  이슈 {issue_id} 쓰기 실패: {status} {detail}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"{failures}건을 쓰지 못했다 — GlitchTip 에서 눈으로 확인한다", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
