#!/usr/bin/env python3
"""스펙 브랜치 흐름(#1210) — 여러 티켓짜리 스펙은 `spec/<이름>` 하나에 모아 main 에 한 번 병합·한 번 배포한다.

    python3 scripts/spec/spec.py start <이름>            # origin/main 위에 spec/<이름> 을 만들어 push(착수 표지 커밋 하나)
    python3 scripts/spec/spec.py merge-ticket <PR>       # base 가 spec/* 이고 head 의 「결과」가 초록일 때만 squash 병합
    python3 scripts/spec/spec.py sync <이름>             # spec/<이름> 워크트리에서: git merge origin/main → 보통 push
    python3 scripts/spec/spec.py finish <이름> [--title] # spec/<이름> → main PR 을 연다(모인 티켓의 Closes 목록). 그 뒤는 enqueue.sh
    python3 scripts/spec/spec.py report <이름>           # 착수→배포 시각·티켓 PR·전체 검사·배포·마지막 검사 실패·충돌
    python3 scripts/spec/spec.py report --prs 1179,1180  # 「티켓마다 main PR」 방식의 같은 숫자(비교용)
    python3 scripts/spec/spec.py dev <이름> [--offset N] [--print]  # 스펙 브랜치를 워크트리 + 오프셋 dev 스택으로 띄운다

판정은 사람 눈이 아니라 이 스크립트가 한다. 종료 코드: 0 됨 · 1 거절(까닭 한 줄) · 2 사용법·조회 실패.
force push 는 하지 않는다. 기록은 커밋 꼬리말 둘에 남는다 — `Spec-Start: <이름>`(start), `Spec-Sync-Conflicts: <수>`(sync);
report 가 그 꼬리말을 GitHub API 로 읽어 센다.
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
CHECK = "결과"  # pr-check.yml 의 필수 검사 이름 — 바꾸면 main ruleset 과 함께 바뀐다
WORKFLOW = "pr-check.yml"
DEPLOY_CONTEXT = os.environ.get("ISSUE_TRACK_DEPLOY_CONTEXT", "sandcorp/deploy")
START_TRAILER = "Spec-Start"
SYNC_TRAILER = "Spec-Sync-Conflicts"
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)

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


# ── merge-ticket ─────────────────────────────────────────────────────────────────────────
class PrInfo(TypedDict):
    number: int
    baseRefName: str
    headRefOid: str
    state: str
    isDraft: bool


class CheckRun(TypedDict):
    id: int
    status: str
    conclusion: str | None
    started_at: str | None
    html_url: str


def merge_ticket(pr: str, gh: Gh = _gh) -> str:
    info = cast(PrInfo, json.loads(gh(["pr", "view", pr, "--json", "number,baseRefName,headRefOid,state,isDraft"])))
    base = info["baseRefName"]
    if not base.startswith("spec/"):
        raise Refused(f"PR #{info['number']} 의 base 가 {base} — spec/* 만 병합한다(main 은 bash scripts/ci/enqueue.sh)")
    if info["state"] != "OPEN":
        raise Refused(f"PR #{info['number']} 가 {info['state']}")
    if info["isDraft"]:
        raise Refused(f"PR #{info['number']} 가 초안")
    sha = info["headRefOid"]
    runs = cast(
        list[CheckRun],
        json.loads(
            gh(["api", "-X", "GET", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs", "-f", f"check_name={CHECK}",
                "-f", "per_page=100", "-q", ".check_runs"])
        ),
    )
    if not runs:
        raise Refused(f"head {sha[:12]} 에 「{CHECK}」가 없다")
    last = max(runs, key=lambda r: (r["started_at"] or "", r["id"]))
    if last["status"] != "completed":
        raise Refused(f"「{CHECK}」가 아직 돈다({last['status']}) — {last['html_url']}")
    if last["conclusion"] != "success":
        raise Refused(f"「{CHECK}」가 {last['conclusion']} — {last['html_url']}")
    gh(["pr", "merge", pr, "--squash", "--match-head-commit", sha])
    return f"PR #{info['number']} → {base} squash 병합(head {sha[:12]}, 「{CHECK}」 success)"


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
class TicketPr(TypedDict):
    number: int
    title: str
    body: str


def closes(body: str) -> list[int]:
    return [int(n) for n in CLOSES.findall(body or "")]


def finish_body(br: str, tickets: Sequence[TicketPr]) -> str:
    issues: list[int] = []
    for t in sorted(tickets, key=lambda t: t["number"]):
        for n in closes(t["body"]):
            if n not in issues:
                issues.append(n)
    lines = [f"스펙 `{br}` → main. 병합은 `bash scripts/ci/enqueue.sh <이 PR>` — 대기열 검사 한 번, 병합 하나 = 배포 하나.", "",
             "## 티켓 PR", ""]
    lines += [f"- #{t['number']} {t['title']}" for t in sorted(tickets, key=lambda t: t["number"])] or ["- (없음)"]
    lines += ["", *[f"Closes #{n}" for n in issues]]
    return "\n".join(lines).rstrip() + "\n"


def finish(name: str, title: str | None, gh: Gh = _gh) -> str:
    br = branch(name)
    tickets = cast(list[TicketPr], json.loads(
        gh(["pr", "list", "--base", br, "--state", "merged", "--limit", "200", "--json", "number,title,body"])))
    body = finish_body(br, tickets)
    opened = cast(list[dict[str, str]], json.loads(
        gh(["pr", "list", "--head", br, "--base", "main", "--state", "open", "--json", "url"])))
    if opened:
        gh(["pr", "edit", opened[0]["url"], "--body", body])
        return f"이미 열려 있다 — 본문만 고쳤다: {opened[0]['url']}"
    url = gh(["pr", "create", "--base", "main", "--head", br, "--title", title or f"스펙 {name}", "--body", body]).strip()
    return f"{url}\n다음: bash scripts/ci/enqueue.sh {url.rsplit('/', 1)[-1]} --wait"


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
            f"티켓 PR {self.tickets} · 전체 검사 {self.pr_checks + self.queue_checks} (PR {self.pr_checks} · 대기열 {self.queue_checks}) · 배포 {self.deploys}",
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
    tickets = cast(list[dict[str, int]], _json(gh, ["pr", "list", "--base", br, "--state", "merged", "--limit", "200",
                                                    "--json", "number"]))
    mains = cast(list[MainPr], _json(gh, ["pr", "list", "--head", br, "--base", "main", "--state", "all", "--json", PR_FIELDS]))
    mains = sorted(mains, key=lambda p: p["number"])
    if mains:
        commits = _pr_commits(gh, mains[-1]["number"])
    else:
        commits = cast(list[Commit], _json(gh, ["api", f"repos/{{owner}}/{{repo}}/compare/main...{br}", "-q", ".commits"]))
    return measure(gh, f"스펙 {br} — main PR {', '.join('#' + str(p['number']) for p in mains) or '아직 없음'}",
                   mains, len(tickets), commits, spec=True)


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
    p = argparse.ArgumentParser(prog="spec.py", description="스펙 브랜치 흐름(#1210)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start").add_argument("name")
    sub.add_parser("merge-ticket").add_argument("pr")
    sub.add_parser("sync").add_argument("name")
    f = sub.add_parser("finish")
    f.add_argument("name")
    f.add_argument("--title")
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
        elif a.cmd == "merge-ticket":
            print(merge_ticket(a.pr))
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
