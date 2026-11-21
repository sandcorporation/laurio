#!/usr/bin/env python3
"""스펙 브랜치 흐름(#1210, #1228) — 여러 티켓짜리 스펙은 `spec/<이름>` 하나에 PR 없이 모아 PR 하나·검사 한 번·배포 한 번.

    python3 scripts/spec/spec.py start <이름>            # origin/main 위에 spec/<이름> 을 만들어 push(착수 표지 커밋 하나)
    python3 scripts/spec/spec.py push <이름>             # 작업자 워크트리에서: fetch → merge origin/spec/<이름> → 보통 push(티켓 사이 PR·CI 없음)
    python3 scripts/spec/spec.py sync <이름>             # spec/<이름> 워크트리에서: git merge origin/main → 보통 push
    python3 scripts/spec/spec.py finish <이름> [--title] # spec/<이름> → main PR 하나(티켓별 커밋·Closes). 그 뒤는 enqueue.sh
    python3 scripts/spec/spec.py blame <이름> <실행 번호|시험 경로>  # 붉은 PR — 실패 파일을 마지막으로 바꾼 티켓 커밋
    python3 scripts/spec/spec.py report <이름>           # 착수→배포 시각·티켓·전체 검사·배포·마지막 검사 실패·충돌
    python3 scripts/spec/spec.py report --prs 1179,1180  # 「티켓마다 main PR」 방식의 같은 숫자(비교용)
    python3 scripts/spec/spec.py dev <이름> [--offset N] [--print]  # 스펙 브랜치를 워크트리 + 오프셋 dev 스택으로 띄운다

판정은 사람 눈이 아니라 이 스크립트가 한다. 종료 코드: 0 됨 · 1 거절(까닭 한 줄) · 2 사용법·조회 실패.
force push 는 하지 않는다. 기록은 커밋 꼬리말 셋에 남는다 — `Spec-Start: <이름>`(start), `Spec-Ticket: #<이슈>`(티켓
커밋마다, push 가 없으면 거절), `Spec-Sync-Conflicts: <수>`(sync); finish·blame·report 가 그 꼬리말을 읽는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
WORKFLOW = "pr-check.yml"
DEPLOY_CONTEXT = os.environ.get("ISSUE_TRACK_DEPLOY_CONTEXT", "sandcorp/deploy")
START_TRAILER = "Spec-Start"
SYNC_TRAILER = "Spec-Sync-Conflicts"
TICKET_TRAILER = "Spec-Ticket"
TICKET_TRAILER_RE = re.compile(rf"^{TICKET_TRAILER}:\s*#?(\d+)\s*$", re.MULTILINE)

Gh = Callable[[Sequence[str]], str]


class Refused(Exception):
    """거절 — 까닭 한 줄. 종료 코드 1."""


def _gh(args: Sequence[str]) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r


def branch(name: str) -> str:
    if not NAME.match(name):
        raise Refused(f"스펙 이름 {name!r} — 소문자·숫자·- 만(41자까지)")
    return f"spec/{name}"


# ── start ────────────────────────────────────────────────────────────────────────────────
def start(name: str, cwd: Path | None = None) -> str:
    br = branch(name)
    _git("fetch", "-q", "origin", "main", cwd=cwd)
    if _git("ls-remote", "--heads", "origin", br, cwd=cwd).stdout.strip():
        raise Refused(f"{br} 가 이미 있다")
    tree = _git("rev-parse", "origin/main^{tree}", cwd=cwd).stdout.strip()
    msg = f"{br} 착수\n\n{START_TRAILER}: {name}\n"
    sha = _git("commit-tree", tree, "-p", "origin/main", "-m", msg, cwd=cwd).stdout.strip()
    _git("push", "-q", "origin", f"{sha}:refs/heads/{br}", cwd=cwd)
    return f"{br} 만듦 — {sha[:12]} (origin/main 위)"


# ── 티켓 커밋 ────────────────────────────────────────────────────────────────────────────
@dataclass
class TicketCommit:
    sha: str
    subject: str
    tickets: list[int]


def tickets_of(message: str) -> list[int]:
    out: list[int] = []
    for n in TICKET_TRAILER_RE.findall(message):
        if int(n) not in out:
            out.append(int(n))
    return out


def ticket_commits(rev_range: str, cwd: Path | None = None, paths: Sequence[str] = ()) -> list[TicketCommit]:
    """merge 커밋을 뺀 범위의 커밋(오래된 것부터). 착수 표지(`Spec-Start`)는 티켓이 아니라 뺀다."""
    out = _git("log", "--reverse", "--no-merges", "--format=%H%x1f%s%x1f%B%x1e", rev_range, "--", *paths, cwd=cwd).stdout
    commits: list[TicketCommit] = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        sha, subject, body = rec.strip("\n").split("\x1f", 2)
        if re.search(rf"^{START_TRAILER}:", body, re.MULTILINE):
            continue
        commits.append(TicketCommit(sha, subject, tickets_of(body)))
    return commits


# ── push ─────────────────────────────────────────────────────────────────────────────────
PUSH_TRIES = 3  # 앞질러짐(non-fast-forward) 뒤 다시 받아 합치는 횟수 — 사슬 셋이 한꺼번에 올려도 끝난다
REJECTED = ("[rejected]", "non-fast-forward", "fetch first", "cannot lock ref", "stale info")


MIGRATION = re.compile(r"^(.+)/migrations/\d{4}_[^/]+\.py$")


def migration_overlap(br: str, cwd: Path | None) -> list[str]:
    """갈라진 뒤 양쪽이 같은 앱에 마이그레이션을 더했나 — git 충돌은 없어도 leaf 가 둘이 된다."""
    def apps(rng: str) -> set[str]:
        out = _git("diff", "--name-only", "--diff-filter=A", rng, cwd=cwd).stdout.split()
        return {m.group(1) for f in out if (m := MIGRATION.match(f))}
    return sorted(apps(f"origin/{br}...HEAD") & apps(f"HEAD...origin/{br}"))


def push(name: str, cwd: Path | None = None, before_push: Callable[[], None] | None = None) -> str:
    """작업자 워크트리의 로컬 브랜치(origin/spec/<이름> 에서 딴 것)를 스펙 브랜치에 올린다 — fetch → merge → 보통 push.

    before_push 는 시험이 「fetch 와 push 사이에 남이 먼저 올렸다」를 만들 자리다.
    """
    br = branch(name)
    dirty = _git("status", "--porcelain", "--untracked-files=no", cwd=cwd).stdout.splitlines()
    if dirty:
        raise Refused(f"작업 트리가 더럽다({len(dirty)}개) — 커밋하거나 되돌린 뒤 다시\n"
                      + "\n".join(f"  {ln}" for ln in dirty[:20]))
    _git("fetch", "-q", "origin", br, cwd=cwd)
    mine = ticket_commits(f"origin/{br}..HEAD", cwd=cwd)
    bare = [c for c in mine if not c.tickets]
    if bare:
        raise Refused(f"꼬리말 `{TICKET_TRAILER}: #<이슈>` 없는 커밋 {len(bare)}개 — `git commit --amend` 로 꼬리말을 더한 뒤 다시\n"
                      + "\n".join(f"  {c.sha[:12]} {c.subject}" for c in bare))
    for attempt in range(1, PUSH_TRIES + 1):
        if attempt > 1:
            _git("fetch", "-q", "origin", br, cwd=cwd)
        if _git("merge-base", "--is-ancestor", f"origin/{br}", "HEAD", cwd=cwd, check=False).returncode != 0:
            both = migration_overlap(br, cwd)
            if both:
                raise Refused(f"마이그레이션이 겹친다(앱 {', '.join(both)}) — 남의 사슬이 같은 앱에 먼저 올렸다. "
                              f"`git merge origin/{br}` 뒤 내 마이그레이션 파일을 그 다음 번호로 옮기고 dependencies 를 고쳐 "
                              f"커밋(`makemigrations --merge` 는 쓰지 않는다) → 다시 push")
            r = _git("merge", "--no-edit", "-q", f"origin/{br}", cwd=cwd, check=False)
            if r.returncode != 0:
                files = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd).stdout.split()
                if not files:
                    raise RuntimeError(f"git merge origin/{br}: {(r.stderr or r.stdout).strip()[:300]}")
                raise Refused(f"origin/{br} 와 충돌 {len(files)}개 — 고친 뒤 `git add` · `git commit --no-edit` · 다시 push"
                              f"(그만두려면 `git merge --abort`)\n" + "\n".join(f"  {f}" for f in files))
        head = _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()
        if head == _git("rev-parse", f"origin/{br}", cwd=cwd).stdout.strip():
            return f"{br}: 올릴 것 없음"
        if before_push:
            before_push()
        r = _git("push", "-q", "origin", f"HEAD:refs/heads/{br}", cwd=cwd, check=False)
        if r.returncode == 0:
            tickets = sorted({n for c in mine for n in c.tickets})
            again = f" · {attempt}번째에" if attempt > 1 else ""
            return f"{br}: push {head[:12]} — 티켓 {', '.join(f'#{n}' for n in tickets) or '없음'}{again}"
        if not any(k in r.stderr for k in REJECTED):
            raise RuntimeError(f"git push: {r.stderr.strip()[:300]}")
    raise Refused(f"{PUSH_TRIES}번 다시 받았는데도 앞질러졌다 — 잠시 뒤 다시 `spec.py push {name}`")


# ── sync ─────────────────────────────────────────────────────────────────────────────────
def sync_message(br: str, conflicts: int) -> str:
    return f"{br} ← main 따라잡기\n\n{SYNC_TRAILER}: {conflicts}\n"


def sync(name: str, cwd: Path | None = None) -> str:
    br = branch(name)
    _git("fetch", "-q", "origin", "main", br, cwd=cwd)
    cur = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).stdout.strip()
    if cur != br:
        raise Refused(f"지금 브랜치가 {cur} — {br} 를 체크아웃한 워크트리에서 돈다"
                      f"(git worktree add -b {br} ../codemit-wt/spec-{name} origin/{br})")
    if _git("merge", "--ff-only", "-q", f"origin/{br}", cwd=cwd, check=False).returncode != 0:
        raise Refused(f"로컬 {br} 가 origin/{br} 와 갈라졌다 — 손으로 맞춘 뒤 다시")
    said = "이미 main 을 담았다"
    if _git("merge-base", "--is-ancestor", "origin/main", "HEAD", cwd=cwd, check=False).returncode != 0:
        r = _git("merge", "--no-ff", "-m", sync_message(br, 0), "origin/main", cwd=cwd, check=False)
        if r.returncode != 0:
            files = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd).stdout.split()
            if not files:
                raise RuntimeError(f"git merge origin/main: {(r.stderr or r.stdout).strip()[:300]}")
            # 고쳐서 `git commit --no-edit` 하면 이 메시지(충돌 수 꼬리말)가 그대로 남는다 — report 가 센다
            merge_msg = _git("rev-parse", "--git-path", "MERGE_MSG", cwd=cwd).stdout.strip()
            Path(cwd or ".", merge_msg).write_text(sync_message(br, len(files)))
            raise Refused(
                f"충돌 {len(files)}개 — 고친 뒤 `git add` · `git commit --no-edit` · 다시 sync(꼬리말 {SYNC_TRAILER}: {len(files)})\n"
                + "\n".join(f"  {f}" for f in files)
            )
        said = "main 을 합쳤다(충돌 0)"
    head = _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()
    remote = _git("rev-parse", f"origin/{br}", cwd=cwd).stdout.strip()
    if head == remote:
        return f"{br}: {said} — push 할 것 없음"
    _git("push", "-q", "origin", f"HEAD:refs/heads/{br}", cwd=cwd)
    return f"{br}: {said} — push {head[:12]}"


# ── finish ───────────────────────────────────────────────────────────────────────────────
def red_path(name: str) -> list[str]:
    return [
        "붉으면 이 PR 에서 고친다 — 새 PR 을 열지 않는다:",
        f"  1. python3 scripts/spec/spec.py blame {name} <실행 번호|시험 경로>  # 그 파일을 마지막으로 바꾼 티켓",
        f"  2. 워크트리(origin/spec/{name} 에서)에서 고쳐 커밋 — 꼬리말 `{TICKET_TRAILER}: #<그 티켓>`",
        f"  3. python3 scripts/spec/spec.py push {name}  # 같은 브랜치 → 같은 PR 이 다시 검사된다",
    ]


def finish_body(name: str, commits: Sequence[TicketCommit]) -> str:
    br = branch(name)
    by: dict[int, list[TicketCommit]] = {}
    for c in commits:
        for n in c.tickets:
            by.setdefault(n, []).append(c)
    lines = [f"스펙 `{br}` → main. 병합은 `bash scripts/ci/enqueue.sh <이 PR>` — 전체 검사 한 번, 병합 하나 = 배포 하나.", "",
             "## 티켓별 커밋", ""]
    for n in sorted(by):
        lines.append(f"- #{n}")
        lines += [f"  - {c.sha[:12]} {c.subject}" for c in by[n]]
    lines += ["", *red_path(name), "", *[f"Closes #{n}" for n in sorted(by)]]
    return "\n".join(lines).rstrip() + "\n"


def finish(name: str, title: str | None, gh: Gh = _gh, cwd: Path | None = None) -> str:
    br = branch(name)
    _git("fetch", "-q", "origin", "main", br, cwd=cwd)
    commits = ticket_commits(f"origin/main..origin/{br}", cwd=cwd)
    if not any(c.tickets for c in commits):
        raise Refused(f"origin/main..origin/{br} 에 꼬리말 `{TICKET_TRAILER}: #<이슈>` 커밋이 없다 — 올린 티켓이 없다")
    body = finish_body(name, commits)
    opened = cast(list[dict[str, str]], json.loads(
        gh(["pr", "list", "--head", br, "--base", "main", "--state", "open", "--json", "url"])))
    if opened:
        gh(["pr", "edit", opened[0]["url"], "--body", body])
        url, said = opened[0]["url"], "이미 열려 있다 — 본문만 고쳤다"
    else:
        url = gh(["pr", "create", "--base", "main", "--head", br, "--title", title or f"스펙 {name}", "--body", body]).strip()
        said = "열었다"
    pr = url.rsplit("/", 1)[-1]
    return "\n".join([f"{said}: {url}", f"초록이면: bash scripts/ci/enqueue.sh {pr} --wait", *red_path(name)])


# ── blame ────────────────────────────────────────────────────────────────────────────────
# pytest `FAILED backend/x/tests/test_y.py::…`, playwright `› e2e/x.spec.ts:12` 같은 줄에서 파일 경로를 줍는다
LOG_PATH = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:py|ts|tsx|js|mjs|sh))(?=[:\s]|$)")


def failed_paths(log: str, files: Sequence[str]) -> list[str]:
    """실패 로그에 찍힌 경로 중 스펙 tip 에 있는 파일. 앱 폴더를 뺀 상대 경로(playwright)는 끝이 맞는 파일로 잇는다."""
    out: list[str] = []
    known = set(files)
    for raw in LOG_PATH.findall(log):
        hit = [raw] if raw in known else [f for f in files if f.endswith("/" + raw)]
        if len(hit) == 1 and hit[0] not in out:
            out.append(hit[0])
    return out


def blame(name: str, target: str, gh: Gh = _gh, cwd: Path | None = None) -> str:
    br = branch(name)
    _git("fetch", "-q", "origin", "main", br, cwd=cwd)
    if target.isdigit():
        files = _git("ls-tree", "-r", "--name-only", f"origin/{br}", cwd=cwd).stdout.split()
        paths = failed_paths(gh(["run", "view", target, "--log-failed"]), files)
        if not paths:
            raise Refused(f"실행 {target} 의 실패 로그에서 저장소 파일 경로를 못 찾았다 — 시험 경로를 직접 준다")
    else:
        paths = [target]
    lines: list[str] = []
    for f in paths:
        touched = ticket_commits(f"origin/main..origin/{br}", cwd=cwd, paths=[f])
        if not touched:
            lines.append(f"{f} ← 스펙이 바꾸지 않았다(main 그대로) — 이 파일이 부르는 쪽을 바꾼 티켓을 본다")
            continue
        last = touched[-1]
        who = ", ".join(f"#{n}" for n in last.tickets) or "꼬리말 없음"
        lines.append(f"{f} ← {who} {last.sha[:12]} {last.subject}")
    return "\n".join(lines)


# ── report ───────────────────────────────────────────────────────────────────────────────
class MainPr(TypedDict):
    number: int
    headRefName: str
    state: str
    mergedAt: str | None
    mergeCommit: dict[str, str] | None


class Commit(TypedDict):
    sha: str
    commit: dict[str, dict[str, str] | str]


class Run(TypedDict):
    id: int
    head_branch: str
    created_at: str


class Status(TypedDict):
    context: str
    state: str
    created_at: str


@dataclass
class Numbers:
    label: str
    started: str | None
    deployed: str | None
    tickets: int
    pr_checks: int
    queue_checks: int
    deploys: int
    last_run: int | None
    last_failures: int | None
    conflicts: int | None
    syncs: int | None

    def lines(self) -> list[str]:
        took = ""
        if self.started and self.deployed:
            d = _ts(self.deployed) - _ts(self.started)
            took = f" ({d.days}일 {d.seconds // 3600}시간 {d.seconds % 3600 // 60}분)"
        last = "—" if self.last_run is None else f"{self.last_failures} (run {self.last_run})"
        conf = "—" if self.conflicts is None else f"{self.conflicts} (sync {self.syncs}번)"
        return [
            self.label,
            f"착수 {self.started or '?'} → 배포 {self.deployed or '아직'}{took}",
            f"티켓 {self.tickets} · 전체 검사 {self.pr_checks + self.queue_checks} (PR {self.pr_checks} · 대기열 {self.queue_checks}) · 배포 {self.deploys}",
            f"마지막 전체 검사 실패 잡 {last}",
            f"main 충돌 {conf}",
        ]


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _json(gh: Gh, args: Sequence[str]) -> object:
    return json.loads(gh(args) or "null")


def _message(c: Commit) -> str:
    return cast(str, c["commit"]["message"])


def _date(c: Commit) -> str:
    return cast(dict[str, str], c["commit"]["author"])["date"]


def _runs(gh: Gh, branch_name: str, event: str) -> list[Run]:
    return cast(list[Run], _json(gh, ["api", "-X", "GET", f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs",
                                      "-f", f"branch={branch_name}", "-f", f"event={event}", "-f", "per_page=100",
                                      "-q", ".workflow_runs"]))


def _queue_runs(gh: Gh, pr: int) -> list[Run]:
    # 대기열 실행의 head_branch 는 gh-readonly-queue/main/pr-<N>-<sha> — branch 필터로는 못 고른다
    runs = cast(list[Run], _json(gh, ["api", "-X", "GET", f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs",
                                      "-f", "event=merge_group", "-f", "per_page=100", "-q", ".workflow_runs"]))
    return [r for r in runs if f"/pr-{pr}-" in r["head_branch"]]


def _deployed(gh: Gh, sha: str) -> str | None:
    statuses = cast(list[Status], _json(gh, ["api", f"repos/{{owner}}/{{repo}}/commits/{sha}/statuses", "-q", "."]))
    ok = [s["created_at"] for s in statuses if s["context"] == DEPLOY_CONTEXT and s["state"] == "success"]
    return min(ok) if ok else None


def _failures(gh: Gh, run_id: int) -> int:
    jobs = cast(list[dict[str, str | None]], _json(gh, ["api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs",
                                                        "-q", ".jobs"]))
    return sum(1 for j in jobs if j.get("conclusion") == "failure")


def measure(gh: Gh, label: str, main_prs: Sequence[MainPr], tickets: int, commits: Sequence[Commit],
            spec: bool) -> Numbers:
    pr_runs: list[Run] = []
    queue_runs: list[Run] = []
    deployed: list[str] = []
    for p in main_prs:
        pr_runs += _runs(gh, p["headRefName"], "pull_request")
        queue_runs += _queue_runs(gh, p["number"])
        if p["mergeCommit"]:
            at = _deployed(gh, p["mergeCommit"]["oid"])
            if at:
                deployed.append(at)
    started = None
    marks = [_date(c) for c in commits if f"{START_TRAILER}:" in _message(c)]
    dates = marks or [_date(c) for c in commits]
    if dates:
        started = min(dates)
    syncs = [int(m) for c in commits for m in re.findall(rf"^{SYNC_TRAILER}:\s*(\d+)", _message(c), re.MULTILINE)]
    every = pr_runs + queue_runs
    last = max(every, key=lambda r: (r["created_at"], r["id"])) if every else None
    return Numbers(
        label=label,
        started=started,
        deployed=max(deployed) if deployed else None,
        tickets=tickets,
        pr_checks=len(pr_runs),
        queue_checks=len(queue_runs),
        deploys=len(deployed),
        last_run=last["id"] if last else None,
        last_failures=_failures(gh, last["id"]) if last else None,
        conflicts=sum(syncs) if spec else None,
        syncs=len(syncs) if spec else None,
    )


def _pr_commits(gh: Gh, pr: int) -> list[Commit]:
    return cast(list[Commit], _json(gh, ["api", f"repos/{{owner}}/{{repo}}/pulls/{pr}/commits?per_page=100", "-q", "."]))


PR_FIELDS = "number,headRefName,state,mergedAt,mergeCommit"


def report_spec(name: str, gh: Gh = _gh) -> Numbers:
    br = branch(name)
    mains = cast(list[MainPr], _json(gh, ["pr", "list", "--head", br, "--base", "main", "--state", "all", "--json", PR_FIELDS]))
    mains = sorted(mains, key=lambda p: p["number"])
    if mains:
        commits = _pr_commits(gh, mains[-1]["number"])
    else:
        commits = cast(list[Commit], _json(gh, ["api", f"repos/{{owner}}/{{repo}}/compare/main...{br}", "-q", ".commits"]))
    return measure(gh, f"스펙 {br} — main PR {', '.join('#' + str(p['number']) for p in mains) or '아직 없음'}",
                   mains, len({n for c in commits for n in tickets_of(_message(c))}), commits, spec=True)


def report_prs(prs: Sequence[int], gh: Gh = _gh) -> Numbers:
    mains = [cast(MainPr, _json(gh, ["pr", "view", str(n), "--json", PR_FIELDS])) for n in prs]
    commits = [c for n in prs for c in _pr_commits(gh, n)]
    return measure(gh, f"티켓마다 main PR — {', '.join('#' + str(n) for n in prs)}", mains, len(prs), commits, spec=False)


# ── dev ──────────────────────────────────────────────────────────────────────────────────
def dev(name: str, offset: int | None, only_print: bool, cwd: Path | None = None) -> str:
    br = branch(name)
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd).stdout.strip())
    wt = common.parent.parent / "codemit-wt" / f"spec-{name}"
    _git("fetch", "-q", "origin", br, cwd=cwd)
    if wt.exists():
        _git("checkout", "-q", "--detach", f"origin/{br}", cwd=wt)
    else:
        _git("worktree", "add", "-q", "--detach", str(wt), f"origin/{br}", cwd=cwd)
    env = f"CODEMIT_DEV_OFFSET={offset} " if offset is not None else ""
    up = f'cd {wt} && eval "$({env}sh docker/dev-env.sh)" && docker compose -f docker/compose.dev.yaml up -d --build'
    if only_print:
        return up
    r = subprocess.run(["bash", "-c", up + ' && echo "프로젝트 $COMPOSE_PROJECT_NAME · 공개 앱 :$CODEMIT_WEB_PORT"'],
                       check=False)
    if r.returncode != 0:
        raise RuntimeError(f"dev 스택이 뜨지 않았다(종료 {r.returncode}) — {up}")
    return f"{wt} ({br} @ origin) — 내릴 때: cd {wt} && eval \"$({env}sh docker/dev-env.sh)\" && docker compose -f docker/compose.dev.yaml down"


# ── 진입 ─────────────────────────────────────────────────────────────────────────────────
def main(argv: Sequence[str]) -> int:
    p = argparse.ArgumentParser(prog="spec.py", description="스펙 브랜치 흐름(#1210, #1228)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start").add_argument("name")
    sub.add_parser("push").add_argument("name")
    sub.add_parser("sync").add_argument("name")
    f = sub.add_parser("finish")
    f.add_argument("name")
    f.add_argument("--title")
    bl = sub.add_parser("blame")
    bl.add_argument("name")
    bl.add_argument("target", help="pr-check 실행 번호 또는 시험 파일 경로")
    r = sub.add_parser("report")
    r.add_argument("name", nargs="?")
    r.add_argument("--prs", help="쉼표로 — 「티켓마다 main PR」 방식의 PR 들")
    d = sub.add_parser("dev")
    d.add_argument("name")
    d.add_argument("--offset", type=int)
    d.add_argument("--print", dest="only_print", action="store_true", help="워크트리만 맞추고 띄울 명령을 찍는다")
    a = p.parse_args(argv)
    try:
        if a.cmd == "start":
            print(start(a.name))
        elif a.cmd == "push":
            print(push(a.name))
        elif a.cmd == "blame":
            print(blame(a.name, a.target))
        elif a.cmd == "sync":
            print(sync(a.name))
        elif a.cmd == "finish":
            print(finish(a.name, a.title))
        elif a.cmd == "report":
            if bool(a.name) == bool(a.prs):
                p.error("report 는 <이름> 또는 --prs 하나")
            n = report_spec(a.name) if a.name else report_prs([int(x) for x in a.prs.split(",") if x.strip()])
            print("\n".join(n.lines()))
        elif a.cmd == "dev":
            print(dev(a.name, a.offset, a.only_print))
    except Refused as e:
        print(f"거절 — {e}", file=sys.stderr)
        return 1
    except (RuntimeError, json.JSONDecodeError, KeyError) as e:
        print(f"실패 — {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
