#!/usr/bin/env python3
"""핫픽스 길의 ci-red 이슈를 대장 메일함으로 넘긴다(#1325). work 의 Orca 자동화 precheck 가 매분 부른다.

    python3 scripts/ci/ci_red_relay.py relay     # 보낼 것을 보내고 1 로 끝난다(에이전트를 띄울 일이 없다)
    python3 scripts/ci/ci_red_relay.py mark      # 보내지 않고 지금 상태만 기록(처음 켤 때 묵은 이슈 거르기)

넘기는 이슈: 라벨 ci-red, 제목이 KINDS 로 시작하는 것(after-push.yml → scripts/ci/after-push-notify.sh 가 연다).
- 열린 이슈를 처음 보면 메일 한 통 — 번호·종류·sha·run 링크만. 이어지는 실패는 같은 이슈의 댓글이라 메일이 다시 가지 않는다.
- 보낸 이슈가 닫히면 「복구·닫힘」 한 통(마지막 댓글의 sha·run).
- 기록은 상태 파일(`CODEMIT_CI_RED_RELAY_STATE`, 기본 ~/.cache/codemit-automation/ci-red-relay.json) — {번호: open|closed}.
  처음 보는 닫힌 이슈는 보내지 않는다.

switchboard 가 0 으로 끝나고 「#번호」 줄을 찍어야 보낸 것이다(scripts/feedback.sh 와 같다). 못 보낸 이슈는 기록하지 않아
다음 분에 다시 시도한다. 종료 코드: 1 정상(보낼 것을 다 보냈거나 없었다) · 2 gh 조회 실패 · 3 메일 실패가 있었다.
automation-run.sh 가 1 밖의 코드를 대장 메일함에 드러낸다(docs/ops/feedback-relay.md 「실패는 드러난다」).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypedDict

LABEL = "ci-red"
KINDS = ("핫픽스 뒤 검사 실패", "표식 없는 main 직접 push")
SHA = re.compile(r"\b[0-9a-f]{40}\b")
RUN = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/actions/runs/\d+")


class Issue(TypedDict):
    number: int
    title: str
    state: str  # OPEN · CLOSED
    body: str


Gh = Callable[[Sequence[str]], str]
Send = Callable[[str, str], bool]


def _gh(args: Sequence[str]) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def _send(subject: str, body: str) -> bool:
    sb = os.environ.get("CODEMIT_SWITCHBOARD", str(Path.home() / ".local/bin/switchboard"))
    env = {**os.environ, "SWITCHBOARD_PROFILE": os.environ.get("CODEMIT_CI_RED_RELAY_PROFILE", "codemit-coordinator")}
    r = subprocess.run(
        [sb, "send", "--to", os.environ.get("CODEMIT_CI_RED_RELAY_TO", "sandcorp/boss"),
         "--task", os.environ.get("CODEMIT_CI_RED_RELAY_TASK", "codemit-ci-red"),
         "--subject", subject, "--body", body],
        capture_output=True, text=True, check=False, env=env,
    )
    out = r.stdout + r.stderr
    print(out.strip())
    return r.returncode == 0 and re.search(r"(?m)^#\d+ ", out) is not None


def kind_of(title: str) -> str | None:
    return next((k for k in KINDS if title.startswith(k)), None)


def facts(text: str) -> str:
    sha = SHA.search(text)
    run = RUN.search(text)
    return f"sha {sha.group(0)[:12] if sha else '?'} · {run.group(0) if run else 'run ?'}"


def issues(gh: Gh) -> list[Issue]:
    raw: list[Issue] = json.loads(gh(["issue", "list", "--label", LABEL, "--state", "all", "--limit", "100",
                                       "--json", "number,title,state,body"]))
    return sorted((i for i in raw if kind_of(i["title"])), key=lambda i: i["number"])


def last_comment(n: int, gh: Gh) -> str:
    data: dict[str, list[dict[str, str]]] = json.loads(gh(["issue", "view", str(n), "--json", "comments"]))
    comments = data.get("comments") or []
    return comments[-1].get("body", "") if comments else ""


def load(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True))
    tmp.replace(path)


def relay(state_path: Path, gh: Gh = _gh, send: Send = _send, *, dry: bool = False) -> int:
    try:
        found = issues(gh)
    except (RuntimeError, ValueError) as e:
        print(f"ci-red 이슈 조회 실패: {e}", file=sys.stderr)
        return 2
    state = load(state_path)
    failed = 0
    for i in found:
        key, kind = str(i["number"]), kind_of(i["title"])
        seen = state.get(key)
        if i["state"] == "OPEN" and seen != "open":
            subject = f"[CI] codemit #{key} {kind}"
            body = f"ci-red #{key} · {kind} · {facts(i['body'])}\ngh issue view {key}"
            new = "open"
        elif i["state"] == "CLOSED" and seen == "open":
            try:
                text = last_comment(i["number"], gh)
            except (RuntimeError, ValueError) as e:
                print(f"#{key} 댓글 조회 실패: {e}", file=sys.stderr)
                return 2
            word = "복구" if kind == KINDS[0] else "닫힘"
            subject = f"[CI] codemit #{key} {word} · {kind}"
            body = f"ci-red #{key} {word} · {kind} · {facts(text)}\ngh issue view {key}"
            new = "closed"
        else:
            if seen is None and i["state"] == "CLOSED":
                state[key] = "closed"  # 처음 보는 닫힌 이슈는 보내지 않는다
            continue
        if dry or send(subject, body):
            state[key] = new
            save(state_path, state)
        else:
            print(f"#{key} 를 대장에게 못 보냈다 — 다음 실행에서 다시 보낸다", file=sys.stderr)
            failed += 1
    save(state_path, state)
    return 3 if failed else 1


def main(argv: Sequence[str]) -> int:
    default = Path.home() / ".cache/codemit-automation/ci-red-relay.json"
    state_path = Path(os.environ.get("CODEMIT_CI_RED_RELAY_STATE", str(default)))
    mode = argv[0] if argv else ""
    if mode == "relay":
        return relay(state_path)
    if mode == "mark":
        rc = relay(state_path, dry=True)
        return 0 if rc == 1 else rc
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
