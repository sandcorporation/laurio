#!/usr/bin/env python3
"""CI 실패 잡을 다시 돌려도 되는지 판정한다(#1207) — 사람 눈이 아니라 이 스크립트가 정한다.

    python3 scripts/ci/rerun_verdict.py <run 번호> [--pr <PR 번호>]

한 줄로 「재실행 가능 — 까닭」 / 「재실행 불가 — 까닭」을 내고, 가능이면 PR 에 남길 댓글 본문이 이어 나온다.
종료 코드: 0 가능 · 1 불가 · 2 조회 실패. **`gh run rerun` 은 부르지 않는다** — 재실행은 사람·작업자가 한다.

규칙(docs/ops/ci.md): 인프라 실패는 아래 셋을 모두 채울 때만 한 번 다시 돈다.
  ① 시험이 시작되기 전 단계(받기·굽기·서비스 띄우기)에서 났다 — 시험 시작 표지가 로그에 먼저 있으면 불가
  ② 로그 줄로 원인이 확인된다 — rerun_causes.json 표에 있는 원인만, 없으면 불가(사람이 표에 더한 뒤에 가능)
  ③ 그 PR 에서 처음이다 — PR 댓글 첫 줄 표지(`COMMENT_PREFIX`)를 센다
거기에 그 원인의 누적 횟수(표의 count)가 1 이상이면 불가이고 「티켓을 올려라」를 낸다. 가능으로 다시 돌렸으면
표의 count 를 1 올린다. CPU 한도 한 번(#1014)은 이 스크립트가 말하지 않는다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

COMMENT_PREFIX = "CI 인프라 재실행 — "
CAUSES_FILE = Path(__file__).resolve().parent / "rerun_causes.json"

# 시험이 돌기 시작했다는 표지 — 이게 원인 줄보다 앞서 있으면 시험 단계의 실패다.
TEST_START_MARKERS = (
    re.compile(r"Running \d+ tests? using \d+ workers?"),  # playwright
    re.compile(r"=+ test session starts =+"),  # pytest
    re.compile(r"^\s*RUN\s+v\d+\.\d+"),  # vitest
    re.compile(r"Found \d+ test\(s\)"),  # django test runner
)
# 실패 단계 이름이 시험 자체인 경우(단계 이름으로 아는 것)
# 앞 잡들의 결과를 모으는 잡 — 거기서 난 실패는 원인이 아니라 결과라 판정에서 뺀다
AGGREGATE_JOBS = frozenset({"결과"})
TEST_STEP = re.compile(r"pytest|vitest|unittest|시험", re.IGNORECASE)

_TS_PREFIX = re.compile(r"^\S.*?\t\S.*?\t﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?")


@dataclass(frozen=True)
class Cause:
    name: str
    pattern: re.Pattern[str]
    count: int
    ticket: str


@dataclass(frozen=True)
class FailedJob:
    name: str
    step: str
    log: list[str]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    cause: str = ""
    cause_line: str = ""


def load_causes(path: Path = CAUSES_FILE) -> list[Cause]:
    rows: list[dict[str, str | int]] = json.loads(path.read_text(encoding="utf-8"))
    return [Cause(str(r["name"]), re.compile(str(r["pattern"])), int(r["count"]), str(r["ticket"])) for r in rows]


def strip_prefix(line: str) -> str:
    """`gh run view --log-failed` 줄의 「잡\\t단계\\t시각 」 머리를 뗀다."""
    return _TS_PREFIX.sub("", line, count=1).rstrip()


def judge_job(job: FailedJob, causes: Sequence[Cause], reruns_on_pr: int) -> Verdict:
    lines = [strip_prefix(x) for x in job.log]
    if TEST_STEP.search(job.step):
        return Verdict(False, f"{job.name}: 실패 단계 「{job.step}」 는 시험 단계다")
    hit = next(((i, c) for i, line in enumerate(lines) for c in causes if c.pattern.search(line)), None)
    if hit is None:
        return Verdict(False, f"{job.name}: 알려진 인프라 원인 줄이 없다 — 코드 탓이면 고치고, 인프라 탓이면 표(rerun_causes.json)에 더한 뒤 다시 판정한다")
    at, cause = hit
    started = next((i for i, line in enumerate(lines) if i < at and any(m.search(line) for m in TEST_START_MARKERS)), None)
    if started is not None:
        return Verdict(False, f"{job.name}: 시험이 시작된 뒤({started + 1}번째 줄)에 난 실패다 — 「{cause.name}」 줄이 있어도 시험 단계다")
    line = lines[at].strip()[:300]
    if cause.count >= 1:
        to = f" ({cause.ticket})" if cause.ticket else ""
        return Verdict(False, f"{job.name}: 「{cause.name}」 은 이미 {cause.count}회 셌다 — 재실행하지 말고 티켓을 올려라{to}", cause.name, line)
    if reruns_on_pr >= 1:
        return Verdict(False, f"{job.name}: 이 PR 에서 인프라 재실행을 이미 {reruns_on_pr}번 했다", cause.name, line)
    return Verdict(True, f"{job.name}: 시험 전 단계의 「{cause.name}」, 이 PR 에서 처음, 누적 {cause.count}회", cause.name, line)


def judge_run(run: str, jobs: Sequence[FailedJob], causes: Sequence[Cause], reruns_on_pr: int) -> tuple[bool, str]:
    if not jobs:
        return False, "재실행 불가 — 실패한 잡이 없다"
    verdicts = [judge_job(j, causes, reruns_on_pr) for j in jobs]
    bad = [v for v in verdicts if not v.ok]
    if bad:
        return False, "재실행 불가 — " + " / ".join(v.reason for v in bad)
    head = "재실행 가능 — " + " / ".join(v.reason for v in verdicts)
    body = [f"{COMMENT_PREFIX}run {run}"]
    for v in verdicts:
        body.append(f"- 원인: {v.cause}")
        body.append(f"  로그: `{v.cause_line}`")
    body.append("재실행: `gh run rerun " + run + " --failed` (표의 누적 횟수도 1 올린다)")
    return True, head + "\n" + "\n".join(body)


def split_failed_log(text: str) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            out.setdefault((parts[0], parts[1]), []).append(line)
    return out


def count_reruns(comment_bodies: Sequence[str]) -> int:
    return sum(1 for b in comment_bodies if b.lstrip().startswith(COMMENT_PREFIX))


def _gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def fetch(run: str, pr: str | None) -> tuple[list[FailedJob], int]:
    info = json.loads(_gh("run", "view", run, "--json", "jobs,headBranch"))
    logs = split_failed_log(_gh("run", "view", run, "--log-failed"))
    jobs: list[FailedJob] = []
    for j in info["jobs"]:
        if j.get("conclusion") != "failure" or j["name"] in AGGREGATE_JOBS:
            continue
        steps = [s["name"] for s in j["steps"] if s.get("conclusion") == "failure"]
        if not steps:  # 단계 없이 잡이 실패한 것(「결과」 같은 모음 잡 포함)은 원인 줄이 없으니 판정에서 뺀다
            continue
        log = [ln for (jn, sn), lns in logs.items() if jn == j["name"] and sn in steps for ln in lns]
        jobs.append(FailedJob(j["name"], steps[0], log))
    number = pr or _gh("pr", "list", "--state", "all", "--head", info["headBranch"], "--json", "number", "-q", ".[0].number").strip()
    comments = json.loads(_gh("pr", "view", number, "--json", "comments"))["comments"] if number else []
    return jobs, count_reruns([c["body"] for c in comments])


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    pr = argv[argv.index("--pr") + 1] if "--pr" in argv else None
    if pr:
        args.remove(pr)
    if len(args) != 1:
        print("사용법: rerun_verdict.py <run 번호> [--pr <PR 번호>]", file=sys.stderr)
        return 2
    try:
        jobs, reruns = fetch(args[0], pr)
    except (RuntimeError, KeyError, ValueError) as e:
        print(f"조회 실패 — {e}", file=sys.stderr)
        return 2
    ok, text = judge_run(args[0], jobs, load_causes(), reruns)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
