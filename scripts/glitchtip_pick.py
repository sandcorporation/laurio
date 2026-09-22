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
토큰(`GLITCHTIP_TOKEN`)만 준다 — 세션은 그것으로 이벤트를 직접 읽는다(한 이슈에 이벤트가
여럿이고, 스택 밖의 맥락이 필요할 때 세션이 스스로 더 받아야 한다).

**그 읽기 토큰이 흘리는 자리가 하나 있다.** `list_alerts`(REST 로는
`/projects/{org}/{project}/alerts/`)가 **Discord 웹훅 URL 을 평문으로 돌려준다**(실측
2026-09-18 — 이 쓰기 토큰은 `project:read` 가 없어 같은 경로에서 403 이다). 세션은
인젝션될 수 있는 텍스트를 읽으므로, 스킬의 「하지 않는 것」이 그 경로를 명시적으로
금지한다.

**클레임을 GlitchTip 코멘트로 남기는 이유.** 이슈 목록 응답에 `numComments` 가 이미 있어서
「손 댄 적 있나」를 목록 API 한 번으로 알 수 있다 — 새 상태 상자를 만들지 않아도 되고,
사람이 GlitchTip 화면에서 같은 사실을 본다. 실측으로 코멘트를 달면 `numComments` 가 그
자리에서 0→1 이 된다(2026-09-18 확인).

**그래서 판정은 내용이 아니라 개수다.** 이 토큰(`event:write`)으로는 코멘트를 **달 수만
있고 읽을 수 없다** — `GET issues/{id}/comments/` 가 `{"detail": "Permission denied"}` 다
(실측 2026-09-18). 즉 「우리가 단 클레임인가, 사람이 단 메모인가」를 구별할 수단이 없고,
구별하려 들면 스코프를 넓혀야 한다(그러면 알림 규칙의 Discord 웹훅까지 열린다). 대신
**코멘트가 하나라도 있으면 손 댄 것으로 본다** — 사람이 메모를 달아 둔 오류를 자동화가
집지 않는 것은 오히려 맞는 동작이다. 대가는 하나: 무심코 단 코멘트가 그 오류를 자동
진단에서 영구히 빼고, 되돌리려면 사람이 화면에서 그 코멘트를 지워야 한다(지우는 데는
`event:admin` 이 필요하고 이 토큰에는 일부러 없다). 실제로 한 번 겪었다 — 클레임 기구를
시험하려고 단 코멘트가 미해결 prod 오류 하나를 막고 있었다.

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
import subprocess
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

#: **우리가 일부러 던지는 예외** — 진단할 것이 없다. 이것을 집으면 세션 하나가 「사고가
#: 아니다」라고 스스로 적힌 예외를 재현하려 애쓴다.
#:
#: `SentrySmokeError` 는 `manage.py sentry_smoke` 가 「오류 수집이 실제로 닿는가」를 확인
#: 하려고 던지는 것이다(`CLAUDE.md` 의 「닿는지 확인하는 법」) — 배포 뒤 사람이 손으로
#: 쏘고 GlitchTip 화면에서 눈으로 본다. 즉 **그 오류가 도착한 것이 곧 성공**이고, 그걸
#: 고치려 드는 것은 정확히 거꾸로다.
#:
#: 필터는 `metadata.type`(정확히 예외 클래스 이름이다)으로 본다 — 제목 문자열로 보면
#: 메시지가 바뀔 때 조용히 새고, 그 메시지는 한국어라 더 잘 바뀐다.
DELIBERATE_EXCEPTION_TYPES = frozenset({"SentrySmokeError"})

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


def _sweep_merged_automation_worktrees(min_idle_minutes: float) -> list[str]:
    """머지가 끝난 자동 진단 워크트리를 걷는다 — 실행마다 하나씩 쌓이기 때문이다.

    **이 함수는 한 번 도는 세션을 죽였다**(티켓 #459, 2026-09-18). 첫 판은 「팁이
    `origin/main` 의 조상이면 머지됐다」로만 판정했는데, **막 만들어져 아직 커밋이 없는
    분기는 팁이 곧 `origin/main`** 이라 그 판정을 그대로 통과했다. 그리고 청소가 잠금
    확인보다 먼저 돌아서, 진단 중인 세션이 첫 커밋 전에 다음 분 precheck 에 워크트리째
    치워졌다(`Working directory ... was deleted`). 재현에 1분 넘게 걸리는 세션은 사실상
    전부 걸리는 결함이었다. 지금은 문이 둘이다:

    1. **잠금이 살아 있으면 이 함수를 아예 부르지 않는다**(`main` 이 잠금 확인 뒤로
       옮겼다) — 도는 세션의 워크트리에는 손이 닿지 않는다.
    2. **팁이 `origin/main` 과 같은 분기는 「아무것도 안 했다」로 보고 건드리지
       않는다** — 잠금이 어떤 이유로 없더라도(TTL 만료 직후 등) 방금 만들어진
       워크트리가 살아남는다. 다만 그러면 재현 실패로 커밋 없이 끝난 워크트리가
       영원히 남으므로, **`min_idle_minutes` 보다 오래 손대지 않은 것만** 걷는다.

    automation 은 `--workspace-mode new-per-run` 이라 세션이 뜨는 실행마다 워크트리와
    브랜치(`auto-<이름>-run-<n>-<시각>`)를 하나 만들고, **끝나도 치우지 않는다.** 그
    안에 `node_modules`·`.venv` 가 각각 들어서므로 몇 건만 쌓여도 이 머신(사람도 같이
    쓴다)의 디스크를 먹는다.

    **매분 도는 것이 이 precheck 하나뿐이라 청소도 여기서 한다.** 별 cron 을 더하는
    것보다 낫다 — 청소할 것이 있는 시점과 이것이 도는 시점이 정확히 같다.

    **머지된 것만 걷는다.** 브랜치 팁이 `origin/main` 의 조상이면 그 안의 작업은 이미
    `main` 에 있다. 조상이 아니면 그대로 둔다 — 게이트에 걸려 사람에게 넘긴 분기
    (스킬의 「사람을 부르는 자리」)가 정확히 그 모양이고, 그건 사람이 이어받을 것이다.

    **무엇이 실패해도 진단을 멈추지 않는다.** 청소가 안 된 것과 오류를 못 집는 것은
    다른 문제다. 실제로 이 저장소에서 `git worktree remove` 가 root 소유
    `.pnpm-store` 때문에 `Permission denied` 로 실패한 적이 있다(2026-09-18) — 그때는
    이름만 알리고 지나간다.
    """

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(_repo_root()), *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )

    swept: list[str] = []
    try:
        listing = git("worktree", "list", "--porcelain")
        if listing.returncode != 0:
            return swept

        main_tip = git("rev-parse", "origin/main").stdout.strip()
        if not main_tip:
            return swept

        path = None
        for line in listing.stdout.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :]
                continue
            if not (line.startswith("branch refs/heads/") and path):
                continue

            branch = line[len("branch refs/heads/") :]
            here, path = path, None
            if not branch.startswith("auto-"):
                continue

            # 머지되지 않았으면 남긴다 — 게이트에 걸려 사람에게 넘긴 분기가 그 모양이다.
            if git("merge-base", "--is-ancestor", branch, "origin/main").returncode != 0:
                continue

            # 팁이 origin/main 이면 **아직 아무것도 커밋하지 않은** 것이다. 도는 세션의
            # 워크트리가 정확히 이 모양이라, 손대기 전에 충분히 식었는지 본다.
            if git("rev-parse", branch).stdout.strip() == main_tip:
                try:
                    idle = (time.time() - pathlib.Path(here).stat().st_mtime) / 60
                except OSError:
                    continue
                if idle < min_idle_minutes:
                    continue

            removed = git("worktree", "remove", "--force", here)
            if removed.returncode == 0:
                git("branch", "-D", branch)
                swept.append(branch)
            else:
                print(
                    f"워크트리 {here} 를 걷지 못했다: {removed.stderr.strip()[:160]}",
                    file=sys.stderr,
                )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"워크트리 청소를 건너뛴다: {exc}", file=sys.stderr)
    return swept


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


#: 재발을 이미 다시 집은 기록 — `{오류 id: 그때의 lastSeen}`. 같은 재발을 매분 또 집지
#: 않으려는 자리다. 새 이벤트가 오면 lastSeen 이 바뀌어 다시 집힌다.
REGRESSION_LEDGER = pathlib.Path("~/.codemit/glitchtip-regressions.json").expanduser()

#: 수정 커밋을 찾을 때 거슬러 볼 main 커밋 수. 수정은 대개 최근이다.
FIX_LOOKBACK = 600

_TRAILER = re.compile(r"^[ \t]*GlitchTip:[ \t]*(\d+)[ \t]*$", re.MULTILINE | re.IGNORECASE)


def _latest_fixes() -> dict[str, str]:
    """`origin/main` 에서 오류마다 **가장 최근의** 수정 커밋 sha 를 모은다.

    커밋 메시지의 `GlitchTip: <id>` 줄로 찾는다 — 해결 표시(`glitchtip_resolve.py`)가
    읽는 것과 같은 줄이다. 한 오류를 두 번 고쳤으면 **최신 것**이 기준이다: 옛 수정만
    포함한 코드에서 난 이벤트는 「최신 수정 이전의 코드」이지 재발이 아니다.
    """

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(_repo_root()), *args], capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )

    git("fetch", "origin", "main", "-q")
    log = git("log", "origin/main", f"-n{FIX_LOOKBACK}", "--format=%H%x00%B%x01")
    fixes: dict[str, str] = {}
    for entry in log.stdout.split("\x01"):
        sha, _, body = entry.strip().partition("\x00")
        for issue_id in _TRAILER.findall(body):
            # git log 은 최신순이라 처음 본 것이 최신 수정이다.
            fixes.setdefault(issue_id, sha)
    return fixes


def _contains(release: str, fix: str) -> bool:
    """`release` 가 `fix` 를 포함하는가 — 즉 그 이벤트가 수정이 든 코드에서 났는가."""

    return (
        subprocess.run(
            ["git", "-C", str(_repo_root()), "merge-base", "--is-ancestor", fix, release],
            capture_output=True,
        ).returncode
        == 0
    )


def _load_ledger() -> dict[str, str]:
    try:
        return json.loads(REGRESSION_LEDGER.read_text())
    except (OSError, ValueError):
        return {}


def _regression_of(issue: dict, fixes: dict[str, str], ledger: dict[str, str]) -> str | None:
    """클레임된 오류가 **아직 다시 집지 않은 재발**이면 그 수정 커밋 sha 를 돌려준다.

    **왜 필요한가.** 「코멘트가 하나라도 있으면 집지 않는다」는 사람의 메모를 존중하려고
    둔 규칙인데, 정할 때 **재발을 고려하지 않았다.** 자동 진단이 고치고 CI 가 닫은 오류가
    고친 코드에서 다시 나면 GlitchTip 이 스스로 미해결로 되살리는데, 클레임 코멘트가
    남아 있어 **자동화가 영영 다시 보지 않았다** — 오류 64 가 그랬다(2026-09-22).

    **재발의 판정은 「최신 이벤트의 release 가 우리 최신 수정을 포함하는가」다.** 오류 64
    에서 실측으로 확인했다: 마지막 이벤트의 release 3037fa2 가 수정 4ac6986 을 포함했다.
    포함하지 않으면 그 이벤트는 수정이 배포되기 전의 옛 코드에서 난 것이라 재발이 아니다 —
    그걸 재발로 보면 배포 대기 5~10분 사이에 이미 고친 오류를 또 집는다.

    **수정 커밋이 없으면 재발이 아니다.** 사람이 메모를 달았거나 자동 진단이 재현하지
    못하고 사람에게 넘긴 오류다 — 그 규칙은 그대로 존중한다.
    """

    issue_id = str(issue.get("id"))
    fix = fixes.get(issue_id)
    if not fix:
        return None
    release = ((issue.get("lastRelease") or {}) or {}).get("version") or ""
    if not release or not _contains(release, fix):
        return None
    if ledger.get(issue_id) == issue.get("lastSeen"):
        # 이 발생 시각에서 이미 다시 집었다. 새 이벤트가 오면 lastSeen 이 바뀐다.
        return None
    return fix


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

    fixes: dict[str, str] | None = None  # 클레임된 후보가 나올 때만 git 을 친다.
    ledger = _load_ledger()

    for issue in issues:
        # 우리가 일부러 던지는 예외는 진단 대상이 아니다.
        if (issue.get("metadata") or {}).get("type") in DELIBERATE_EXCEPTION_TYPES:
            continue
        issue.pop("_regression_of", None)
        # 이미 손 댄 것은 건너뛴다 — 클레임이 곧 이 값이다. **다만 수정한 코드에서
        # 재발한 것은 다시 집는다**(`_regression_of`).
        if not args.any_claimed and int(issue.get("numComments") or 0) > 0:
            if fixes is None:
                fixes = _latest_fixes()
            previous_fix = _regression_of(issue, fixes, ledger)
            if not previous_fix:
                continue
            issue["_regression_of"] = previous_fix
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
    parser.add_argument("--no-tidy", action="store_true", help="머지된 자동 워크트리를 걷지 않는다")
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

    # **청소는 잠금 확인을 통과한 뒤에만 한다**(티켓 #459). 위에서 `return 1` 했다면
    # 세션이 돌고 있다는 뜻이고, 그 세션의 워크트리를 우리가 지우면 작업이 통째로
    # 사라진다 — 실제로 한 번 그렇게 죽였다.
    if not args.dry_run and not args.no_tidy:
        swept = _sweep_merged_automation_worktrees(args.lock_ttl_minutes)
        if swept:
            print(f"머지된 워크트리 {len(swept)}건을 걷었다: {', '.join(swept)}", file=sys.stderr)

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
        # **재발이면 지난번 수정 커밋**이다 — 세션은 「처음 보는 오류」가 아니라 「고쳤는데
        # 그 코드에서 또 난 오류」를 받는 것이므로, 그 수정이 무엇을 놓쳤는지부터 봐야 한다.
        "regression_of": issue.get("_regression_of"),
    }

    if not args.dry_run:
        status, _ = _request(
            f"issues/{issue['id']}/comments/",
            _TOKEN,
            method="POST",
            body={"data": {"text": (
                f"{CLAIM_PREFIX} 이 오류가 **수정이 들어간 코드에서 재발**해 자동 진단이 다시 "
                f"집었습니다(지난 수정 `{picked['regression_of'][:12]}`). 결과를 이 이슈에 다시 적습니다."
                if picked["regression_of"]
                else f"{CLAIM_PREFIX} 이 오류를 자동 진단이 집었습니다. 결과를 이 이슈에 다시 적습니다."
            )}},
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

    if picked["regression_of"] and not args.dry_run:
        # 이 발생 시각에서 다시 집었다고 적는다 — 적지 않으면 세션이 끝나 잠금이 풀린
        # 다음 분에 **같은 재발을 또 집는다**(재현 실패로 미해결인 채 남으니까).
        ledger = _load_ledger()
        ledger[str(picked["id"])] = picked["lastSeen"]
        REGRESSION_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        REGRESSION_LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))

    if holds_lock:
        # **클레임이 성공한 뒤에만 잠근다.** 앞에서 실패해 `return 1` 한 경로에 잠금이
        # 남으면, 세션이 뜨지도 않았는데 다음 45분이 통째로 막힌다.
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(f"{picked['id']}\n")

    print(json.dumps(picked, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
