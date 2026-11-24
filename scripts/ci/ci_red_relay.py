#!/usr/bin/env python3
"""핫픽스 길의 ci-red 이슈를 운영 담당 Orca 메일로 넘긴다(#1325, #1374). work 의 Orca 자동화 precheck 가 매분 부른다.

    python3 scripts/ci/ci_red_relay.py relay     # 보낼 것을 보내고 1 로 끝난다(에이전트를 띄울 일이 없다)
    python3 scripts/ci/ci_red_relay.py mark      # 보내지 않고 지금 상태만 기록(처음 켤 때 묵은 이슈 거르기)

넘기는 이슈: 라벨 ci-red, 제목이 KINDS 로 시작하는 것(after-push.yml → scripts/ci/after-push-notify.sh 가 연다).
- 열린 이슈를 처음 보면 메일 한 통 — 번호·종류·sha·run 링크만. 이어지는 실패는 같은 이슈의 댓글이라 메일이 다시 가지 않는다.
- 보낸 이슈가 닫히면 「복구·닫힘」 한 통(마지막 댓글의 sha·run).
- 기록은 상태 파일(`CODEMIT_CI_RED_RELAY_STATE`, 기본 ~/.cache/codemit-automation/ci-red-relay.json) — {번호: open|closed}.
  처음 보는 닫힌 이슈는 보내지 않는다. 처음 켤 때는 `mark` 로 만든다.
- 상태 파일이 없거나 깨졌으면 아무것도 보내지 않고 지금 상태를 기록만 한 뒤 3 으로 끝난다 — 열린 이슈를 한꺼번에 다시
  보내지 않고(중복 폭주 없음), 무엇을 건너뛰었는지는 표준오류 한 줄로 automation-run.sh 가 대장에게 한 번 드러낸다.

scripts/notify-ops.sh 가 0 으로 끝나야(orca 0 + `messageId=` 줄) 보낸 것이다(scripts/feedback.sh 와 같다). 못 보낸 이슈는 기록하지 않아
다음 분에 다시 시도한다. 종료 코드: 1 정상(보낼 것을 다 보냈거나 없었다) · 2 gh 조회 실패 · 3 메일 실패가 있었다.
automation-run.sh 가 1 밖의 코드를 운영 담당에게 드러낸다(docs/ops/feedback-relay.md 「실패는 드러난다」).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
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
    notify = Path(__file__).resolve().parent.parent / "notify-ops.sh"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        r = subprocess.run(["bash", str(notify), f"[codemit] ci-red {subject}", f.name],
                           capture_output=True, text=True, check=False)
    print((r.stdout + r.stderr).strip())
    return r.returncode == 0


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


def load(path: Path) -> dict[str, str] | None:
    """기록. 없거나 깨졌으면 None."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else None


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
    loaded = load(state_path)
    if loaded is None and not dry:
        relay(state_path, gh, send, dry=True)
        opened = [f"#{i['number']}" for i in found if i["state"] == "OPEN"]
        print(f"상태 파일({state_path})이 없거나 깨져 다시 만들었다 — 보내지 않고 기록만 했다. 지금 열린 것: "
              f"{' '.join(opened) or '없음'}", file=sys.stderr)
        return 3
    state = loaded or {}
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
