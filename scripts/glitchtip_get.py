#!/usr/bin/env python3
"""GlitchTip 을 사람·에이전트가 눈으로 읽을 때 쓰는 조회 도구 (2026-09-18).

**왜 curl 대신 이것을 쓰는가.** 이 세션에서 **같은 실수를 세 번** 했다 — GlitchTip 의
오류 응답(`{"detail": "Permission denied"}` · `{"detail": "Not Found"}`)을 그대로
`json.load` 해서 필드를 찾다가 **빈 값이 나오면 「그 필드가 비어 있다」로 읽었다.** 그
결과 「코멘트가 비어 있다」(실은 권한 거부)와 「쿠키가 사라졌다」(실은 이슈가 삭제됨)를
사용자에게 사실처럼 말했다. `curl | python3 -c` 한 줄은 그 구별을 강제하지 않는다.

그래서 이 도구는 **HTTP 상태를 먼저 말한다.** 2xx 가 아니면 필드를 보여주지 않고
`상태 + 본문` 만 적고 비정상 종료한다 — 「값이 없다」와 「물어볼 수 없었다」가 절대
같은 모양으로 나오지 않는다.

**토큰은 읽기 전용(`GLITCHTIP_TOKEN`)을 쓴다.** 이 도구는 아무것도 쓰지 않는다 —
쓰기는 `glitchtip_pick.py`(클레임)와 `scripts/ci/glitchtip-resolve.sh`(해결 표시)만 한다.
`--alerts` 류 경로는 일부러 지원하지 않는다: 그 응답이 Discord 웹훅 URL 을 평문으로
돌려준다(`.claude/skills/glitchtip-triage/` 의 「하지 않는 것」).

사용법:

    scripts/glitchtip_get.py issues                 # 미해결 목록
    scripts/glitchtip_get.py issues --all           # 해결된 것까지
    scripts/glitchtip_get.py issue 60               # 오류 하나
    scripts/glitchtip_get.py event 60               # 그 오류의 최신 이벤트 (요약)
    scripts/glitchtip_get.py event 60 --raw         # 그 이벤트 전문 (JSON)
    scripts/glitchtip_get.py tags 60                # 환경·release 등 태그
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

GLITCHTIP_URL = os.environ.get("GLITCHTIP_URL", "").rstrip("/")  # 자체 호스팅 GlitchTip 주소 — 저장소에 적지 않는다(#930)
ORG_SLUG = os.environ.get("GLITCHTIP_ORG", "codemit")
TIMEOUT_SECONDS = 20

#: 이벤트 본문에서 **절대 화면에 찍지 않는** 자리. 남아 있을 수 있고(옛 이벤트),
#: 붙여넣기 한 번으로 남의 세션이 된다.
NEVER_PRINT = ("cookies", "data")
CREDENTIAL_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization", "x-internal-token"}


def _token() -> str:
    token = os.environ.get("GLITCHTIP_TOKEN", "").strip()
    if token:
        return token
    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            match = re.match(r"^\s*GLITCHTIP_TOKEN\s*=\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip().strip("'\"")
    return ""


def _get(path: str, token: str) -> object:
    """2xx 가 아니면 **여기서 죽는다** — 호출부가 빈 값을 사실로 읽을 길을 없앤다."""

    if not GLITCHTIP_URL:
        raise SystemExit("GLITCHTIP_URL 이 비어 있다 — 자체 호스팅 GlitchTip 주소를 환경변수로 준다")
    url = f"{GLITCHTIP_URL}/api/0/{path.lstrip('/')}"
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        hint = {
            403: "이 토큰에 그 권한이 없다 — 「값이 없다」가 아니다.",
            404: "그 이슈·이벤트가 없다(지워졌을 수 있다) — 「값이 없다」가 아니다.",
            401: "토큰이 틀렸거나 비었다.",
        }.get(exc.code, "")
        print(f"HTTP {exc.code} — {url}\n  {body}\n  {hint}".rstrip(), file=sys.stderr)
        raise SystemExit(2)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"GlitchTip 에 닿지 못했다: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _row(issue: dict) -> str:
    return "id=%-4s %-6s com=%-3s %-19s %-9s %s" % (
        issue.get("id"),
        issue.get("count"),
        issue.get("numComments", 0),
        (issue.get("project") or {}).get("slug", "?"),
        issue.get("status"),
        (issue.get("title") or "")[:52],
    )


def cmd_issues(args: argparse.Namespace, token: str) -> None:
    params = {"limit": str(args.limit), "sort": "-count"}
    if not args.all:
        params["query"] = "is:unresolved"
    issues = _get(f"organizations/{ORG_SLUG}/issues/?{urllib.parse.urlencode(params)}", token)
    if not isinstance(issues, list):
        print(f"목록이 아니라 {type(issues).__name__} 이 왔다: {str(issues)[:200]}", file=sys.stderr)
        raise SystemExit(2)
    print(f"{'해결된 것까지 ' if args.all else '미해결 '}{len(issues)}건")
    for issue in issues:
        print("  " + _row(issue))


def cmd_issue(args: argparse.Namespace, token: str) -> None:
    issue = _get(f"issues/{args.id}/", token)
    assert isinstance(issue, dict)
    print(_row(issue))
    for key in ("firstSeen", "lastSeen", "permalink", "shortId", "level"):
        print(f"  {key}: {issue.get(key)}")
    release = ((issue.get("lastRelease") or {}) or {}).get("version")
    print(f"  lastRelease: {release}")


def cmd_tags(args: argparse.Namespace, token: str) -> None:
    tags = _get(f"issues/{args.id}/tags/", token)
    assert isinstance(tags, list)
    for tag in tags:
        values = [v.get("value") for v in (tag.get("topValues") or [])]
        print(f"  {tag.get('key')}: {', '.join(str(v) for v in values)}")


def cmd_event(args: argparse.Namespace, token: str) -> None:
    event = _get(f"issues/{args.id}/events/latest/", token)
    assert isinstance(event, dict)

    if args.raw:
        # 전문을 달라고 했으면 준다 — 다만 자격증명 자리는 여기서도 가린다.
        request = next(
            (e.get("data") or {} for e in event.get("entries", []) if e.get("type") == "request"), None
        )
        if isinstance(request, dict):
            for key in NEVER_PRINT:
                if key in request:
                    request[key] = "<REDACTED — 이 도구는 자격증명을 찍지 않는다>"
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return

    print(f"eventID: {event.get('eventID')}  dateCreated: {event.get('dateCreated')}")
    print(f"title: {(event.get('title') or '')[:100]}")
    for entry in event.get("entries", []):
        kind = entry.get("type")
        data = entry.get("data") or {}
        if kind == "exception":
            for value in (data.get("values") or [])[:1]:
                frames = ((value.get("stacktrace") or {}) or {}).get("frames") or []
                ours = [f for f in frames if not (f.get("filename") or "").startswith(("node:", "/node_modules"))]
                print(f"\n[exception] {value.get('type')}: {str(value.get('value'))[:120]}")
                for frame in ours[-6:]:
                    print(f"    {frame.get('filename')}:{frame.get('lineNo')} in {frame.get('function')}")
        elif kind == "request":
            print(f"\n[request] {data.get('method')} {data.get('url')}")
            # **키가 있는 것과 값이 있는 것은 다르다.** GlitchTip 은 안 보낸 자리도
            # `cookies: null` 로 채워 돌려준다 — 키만 보고 경고하면 브라우저 쪽
            # 이벤트마다 「누출」이라고 외친다(내가 실제로 한 번 그렇게 잘못 읽었다).
            present = [k for k in NEVER_PRINT if data.get(k) not in (None, {}, [], "")]
            if present:
                # **이 사실은 반드시 보인다** — 누출이 남아 있다는 신호다(#460).
                print(f"    ⚠ 이 이벤트에는 {', '.join(present)} 가 실려 있다 (값은 찍지 않는다)")
            headers = data.get("headers") or []
            names = [h[0] for h in headers] if isinstance(headers, list) else list(headers)
            leaked = [n for n in names if str(n).lower() in CREDENTIAL_HEADERS]
            print(f"    헤더 {len(names)}개" + (f", 자격증명 헤더 있음: {leaked}" if leaked else ""))
    print("\n(전문은 --raw)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("issues", help="오류 목록")
    p.add_argument("--all", action="store_true", help="해결된 것까지")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_issues)

    for name, func, helptext in (
        ("issue", cmd_issue, "오류 하나"),
        ("tags", cmd_tags, "그 오류의 태그(환경·release 등)"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("id")
        p.set_defaults(func=func)

    p = sub.add_parser("event", help="그 오류의 최신 이벤트")
    p.add_argument("id")
    p.add_argument("--raw", action="store_true", help="JSON 전문 (자격증명은 가린다)")
    p.set_defaults(func=cmd_event)

    args = parser.parse_args()
    token = _token()
    if not token:
        print("GLITCHTIP_TOKEN 이 없다 — .env 나 환경변수에 넣어야 한다", file=sys.stderr)
        return 2
    args.func(args, token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
