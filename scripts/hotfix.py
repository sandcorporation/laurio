#!/usr/bin/env python3
"""핫픽스 길(#1325) — 커밋 하나를 PR·검사·병합 대기열 없이 main 에 올린다. 대장이 지시서에 「핫픽스 길」이라 적은 일만.

    python3 scripts/hotfix.py push --issue <N> [--dry-run]   # 워크트리에서: 표식 → 따라잡기 → main push → run 보이기
    python3 scripts/hotfix.py runs [<sha>]                   # 그 커밋의 release·뒤따른 검사 run 과 배포 상태(기본 origin/main)

push 가 하는 것:
1. 워크트리가 깨끗하고, origin/main 위의 커밋이 정확히 하나인지 본다(둘 이상이면 하나로 합쳐 오라고 거절한다).
2. 그 커밋에 `Hotfix: #<N>` 꼬리말이 없으면 단다(amend). 이 표식이 없으면 after-push.yml 이 「표식 없는 main 직접 push」로
   대장에게 알린다.
3. main 이 앞서 있으면 그 위로 rebase(충돌이면 되돌리고 거절), `git push origin HEAD:main`. 남이 먼저 올리면 세 번까지
   따라잡아 다시 올린다. force push 는 하지 않는다.
4. push 뒤 release(이미지 → production 승격 → Jenkins 배포)와 main 뒤따른 검사(after-push.yml) run 을 찾아 보인다.
`--dry-run` 은 1·2·3 의 따라잡기까지 하고 push 는 `git push --dry-run` 으로만 한다.

ruleset 이 막으면(우회가 아직 열리지 않았다) 까닭 한 줄로 거절한다 — docs/ops/deploy-paths.md 「대표 몫」.
종료 코드: 0 됨 · 1 거절(까닭 한 줄) · 2 사용법·조회 실패.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypedDict

TRAILER = "Hotfix"
DEPLOY_CONTEXT = os.environ.get("ISSUE_TRACK_DEPLOY_CONTEXT", "sandcorp/deploy")
WORKFLOWS = ("release", "main 뒤따른 검사")
RACED = ("[rejected]", "non-fast-forward", "fetch first", "cannot lock ref", "stale info")
RULESET = ("GH013", "GH006", "protected branch", "Repository rule violations", "merge queue")

Gh = Callable[[Sequence[str]], str]


class Refused(Exception):
    """거절 — 까닭 한 줄. 종료 코드 1."""


class Run(TypedDict):
    workflowName: str
    status: str
    conclusion: str
    url: str


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


def marked(rev: str, cwd: Path | None = None) -> bool:
    out = _git("log", "-1", f"--format=%(trailers:key={TRAILER},valueonly)", rev, cwd=cwd).stdout
    return bool(out.strip())


def prepare(issue: int | None, cwd: Path | None = None) -> str:
    """깨끗한지·커밋 하나인지 보고, 표식을 달고, origin/main 위로 따라잡는다. 머리 sha 를 돌려준다."""
    if _git("status", "--porcelain", "--untracked-files=no", cwd=cwd).stdout.strip():
        raise Refused("워크트리에 커밋하지 않은 변경이 있다 — 커밋하거나 치운 뒤 다시")
    _git("fetch", "-q", "origin", "main", cwd=cwd)
    ahead = _git("rev-list", "origin/main..HEAD", cwd=cwd).stdout.split()
    if not ahead:
        raise Refused("origin/main 위에 올릴 커밋이 없다")
    if len(ahead) > 1:
        raise Refused(f"origin/main 위 커밋이 {len(ahead)}개다 — 핫픽스는 커밋 하나다(합친 뒤 다시)")
    if not marked("HEAD", cwd):
        if issue is None:
            raise Refused(f"커밋에 `{TRAILER}:` 꼬리말이 없다 — --issue <N> 을 주면 단다")
        _git("commit", "-q", "--amend", "--no-edit", "--trailer", f"{TRAILER}: #{issue}", cwd=cwd)
    catch_up(cwd)
    return _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


def catch_up(cwd: Path | None = None) -> None:
    if _git("merge-base", "--is-ancestor", "origin/main", "HEAD", cwd=cwd, check=False).returncode == 0:
        return
    if _git("rebase", "-q", "origin/main", cwd=cwd, check=False).returncode != 0:
        _git("rebase", "--abort", cwd=cwd, check=False)
        raise Refused("origin/main 위로 따라잡다 충돌이 났다 — 되돌렸다. 충돌을 풀어 커밋 하나로 만든 뒤 다시")


def push(issue: int | None, cwd: Path | None = None, *, dry: bool = False, tries: int = 3) -> str:
    sha = prepare(issue, cwd)
    for attempt in range(tries):
        args = ["push", "--porcelain", *(["--dry-run"] if dry else []), "origin", "HEAD:main"]
        r = _git(*args, cwd=cwd, check=False)
        if r.returncode == 0:
            return _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()
        out = r.stdout + r.stderr
        if any(m in out for m in RULESET):
            raise Refused("main ruleset 이 막았다 — 핫픽스 우회가 아직 열리지 않았다(docs/ops/deploy-paths.md 「대표 몫」)")
        if attempt + 1 < tries and any(m in out for m in RACED):
            _git("fetch", "-q", "origin", "main", cwd=cwd)
            catch_up(cwd)
            continue
        raise Refused(f"push 실패: {out.strip().splitlines()[-1] if out.strip() else r.returncode}")
    raise Refused(f"main 이 계속 앞서 나가 {sha[:12]} 을 올리지 못했다")


def runs(sha: str, gh: Gh = _gh) -> list[Run]:
    data: list[Run] = json.loads(gh(["run", "list", "--commit", sha, "--limit", "20",
                                     "--json", "workflowName,status,conclusion,url"]))
    return [r for r in data if r["workflowName"] in WORKFLOWS]


def deploy_state(sha: str, repo: str, gh: Gh = _gh) -> str:
    out = gh(["api", f"repos/{repo}/commits/{sha}/status",
              "-q", f'[.statuses[]|select(.context=="{DEPLOY_CONTEXT}")][0]|.state+" "+.target_url'])
    return out.strip() or "아직 없음"


def show(sha: str, repo: str, gh: Gh = _gh, *, wait: float = 90, step: float = 10) -> None:
    """release·뒤따른 검사 run 이 보일 때까지(최대 wait 초) 기다렸다 한 번 보인다."""
    deadline = time.monotonic() + wait
    found: list[Run] = []
    while True:
        try:
            found = runs(sha, gh)
        except (RuntimeError, ValueError) as e:
            print(f"run 조회 실패: {e}", file=sys.stderr)
        if len({r["workflowName"] for r in found}) >= len(WORKFLOWS) or time.monotonic() >= deadline:
            break
        time.sleep(step)
    print(f"커밋 {sha[:12]}")
    for r in found:
        print(f"  {r['workflowName']}: " + " ".join(x for x in (r["status"], r["conclusion"], r["url"]) if x))
    missing = [w for w in WORKFLOWS if w not in {r["workflowName"] for r in found}]
    for w in missing:
        print(f"  {w}: 아직 없음")
    try:
        print(f"  배포({DEPLOY_CONTEXT}): {deploy_state(sha, repo, gh)}")
    except RuntimeError as e:
        print(f"  배포({DEPLOY_CONTEXT}): 조회 실패 {e}")
    print(f"  다시 보기: python3 scripts/hotfix.py runs {sha[:12]}")


def repo_name(cwd: Path | None = None) -> str:
    url = _git("remote", "get-url", "origin", cwd=cwd).stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    return os.environ.get("GH_REPO") or (m.group(1) if m else "")


def main(argv: Sequence[str]) -> int:
    p = argparse.ArgumentParser(prog="hotfix.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("push")
    pp.add_argument("--issue", type=int)
    pp.add_argument("--dry-run", action="store_true")
    pr = sub.add_parser("runs")
    pr.add_argument("sha", nargs="?")
    a = p.parse_args(argv)
    try:
        if a.cmd == "push":
            sha = push(a.issue, dry=a.dry_run)
            if a.dry_run:
                print(f"dry-run — {sha[:12]} 을 main 에 올릴 수 있다(올리지 않았다)")
                return 0
            print(f"main ← {sha[:12]} (핫픽스)")
            show(sha, repo_name())
            return 0
        sha = a.sha or _git("rev-parse", "origin/main").stdout.strip()
        show(sha, repo_name(), wait=0)
        return 0
    except Refused as e:
        print(f"거절: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"실패: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
