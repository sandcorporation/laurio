#!/usr/bin/env python3
"""main push 하나를 셋으로 가른다(#1325) — after-push.yml 의 kind 잡이 부른다.

    python3 scripts/ci/push_kind.py --sha <after> --before <before>

표준출력에 `kind=…` 와 `unmarked=…`(빈칸으로 나눈 짧은 sha) 두 줄을 낸다 — 워크플로가 그대로 GITHUB_OUTPUT 에 붙인다.

- queue   병합 대기열이 올린 커밋. 그 sha 그대로 `merge_group` 실행(PR 검사)이 있었다 — 대기열은 검사한 머지 커밋으로
          main 을 앞으로 옮기므로 push 머리 = 대기열이 검사한 sha 다. 뒤따른 검사를 다시 돌리지 않는다(#1090).
- hotfix  대기열 커밋이 아니고, before..after 의 커밋이 모두 `Hotfix:` 꼬리말을 달았다(scripts/hotfix.py 가 단다).
- direct  그 밖 — 표식 없는 main 직접 push. 뒤따른 검사를 돌리고 대장에게 알린다.

대기열 실행 조회가 실패하면 direct 로 본다(조용히 넘어가지 않게 — 시끄러운 쪽으로 틀린다).
GH_REPO·GH_TOKEN 은 환경에서(actions: read).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

TRAILER = "Hotfix"
ZERO = "0" * 40

Gh = Callable[[Sequence[str]], str]


def _gh(args: Sequence[str]) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def _git(cwd: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def queue_ran(sha: str, repo: str, gh: Gh = _gh) -> bool:
    """이 sha 로 병합 대기열 실행이 있었나. 조회 실패는 RuntimeError."""
    out = gh(["api", f"repos/{repo}/actions/runs?head_sha={sha}&event=merge_group&per_page=1", "-q", ".total_count"])
    return int(out.strip() or "0") > 0


def pushed_commits(sha: str, before: str, cwd: Path | None = None) -> list[str]:
    """이 push 가 main 에 올린 커밋. before 가 없거나(새 브랜치·0) 조상이 아니면 머리 하나만 본다."""
    if before and before != ZERO and _git(cwd, "merge-base", "--is-ancestor", before, sha).returncode == 0:
        r = _git(cwd, "rev-list", f"{before}..{sha}")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()
    return [sha]


def marked(commit: str, cwd: Path | None = None) -> bool:
    r = _git(cwd, "log", "-1", f"--format=%(trailers:key={TRAILER},valueonly)", commit)
    return r.returncode == 0 and bool(r.stdout.strip())


def classify(sha: str, before: str, repo: str, cwd: Path | None = None, gh: Gh = _gh) -> tuple[str, list[str]]:
    """(kind, 표식 없는 커밋의 짧은 sha 목록)."""
    try:
        if queue_ran(sha, repo, gh):
            return "queue", []
    except (RuntimeError, ValueError) as e:
        print(f"::warning::대기열 실행 조회 실패 — 표식 없는 push 로 본다: {e}", file=sys.stderr)
        return "direct", [sha[:12]]
    unmarked = [c[:12] for c in pushed_commits(sha, before, cwd) if not marked(c, cwd)]
    return ("direct" if unmarked else "hotfix"), unmarked


def main(argv: Sequence[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--before", default="")
    p.add_argument("--repo", default="")
    a = p.parse_args(argv)
    repo = a.repo or os.environ.get("GH_REPO", "")
    if not repo:
        print("GH_REPO 가 필요하다", file=sys.stderr)
        return 2
    kind, unmarked = classify(a.sha, a.before, repo)
    print(f"kind={kind}")
    print(f"unmarked={' '.join(unmarked)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
