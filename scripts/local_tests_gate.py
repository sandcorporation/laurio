"""push 전에 고른 시험을 돌렸나 — `scripts/test.sh affected` 의 기록과 push 할 커밋을 맞춘다(#1331, spec local-tests).

    python3 scripts/local_tests_gate.py pre-push <원격 이름> <주소>   # .githooks/pre-push 가 부른다(표준 입력은 git 의 것)

로컬 게이트가 문서로만 있어 돌리지 않고 push 해도 아무것도 드러나지 않았다(#1328 이 계약 시험을 돌리지 않고 올려
PR 검사에서야 빨갰다). 그래서:

- `scripts/test.sh affected`(돌리기)가 끝나면 **시험한 작업 트리의 해시**·고른 수·돈 종류·통과를
  `<git-dir>/codemit-local-tests.json` 에 남긴다(`record`). 워크트리마다 따로다.
- pre-push 훅이 push 할 커밋 가운데 원격에 아직 없는 merge 아닌 커밋(= 내 작업)이 바꾼 파일을 모은다. 그 파일이
  **시험한 트리와 push 할 트리에서 같고**, 기록이 통과면 보낸다. merge·rebase 로 들어온 남의 변경은 내 파일이 아니라
  비교에서 빠진다 — `spec.py push` 의 merge 커밋, `hotfix.py` 의 rebase 를 다시 돌리지 않아도 된다.
- 내 커밋이 없거나(spec sync·브랜치 지우기) 문서(`*.md`·`docs/`)만 바꿨으면 묻지 않는다.
- **우회**: 내 커밋 하나에 꼬리말 `Local-Tests-Skipped: <까닭>` 을 단다. 커밋에 남으니 PR·스펙 마감 PR 의 커밋 목록에
  그대로 보인다. `git push --no-verify` 는 막을 수 없다 — 그래서 우회를 꼬리말로 열어 두고 문서가 그쪽을 가리킨다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

RECORD = "codemit-local-tests.json"
SKIP_TRAILER = "Local-Tests-Skipped"
ZERO = "0" * 40


@dataclass
class Record:
    tree: str  # 시험한 작업 트리(추적 + 무시되지 않은 새 파일)의 git tree 해시
    head: str
    base: str
    picked: dict[str, int]
    ran: list[str]
    passed: bool


def git(*args: str, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def record_path(root: Path) -> Path:
    gitdir = Path(git("rev-parse", "--git-dir", cwd=root).strip())
    return gitdir if gitdir.is_absolute() else root / gitdir


def work_tree(root: Path) -> str:
    """지금 작업 트리(커밋하지 않은 변경·새 파일 포함)의 tree 해시 — 진짜 index 는 건드리지 않는다."""

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", "HEAD", cwd=root, env=env)
        git("add", "-A", cwd=root, env=env)
        return git("write-tree", cwd=root, env=env).strip()


def write(root: Path, *, base: str, picked: Mapping[str, int], ran: Iterable[str], passed: bool) -> Record:
    rec = Record(work_tree(root), git("rev-parse", "HEAD", cwd=root).strip(), base, dict(picked), list(ran), passed)
    (record_path(root) / RECORD).write_text(json.dumps(asdict(rec), ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def read(root: Path) -> Record | None:
    try:
        return Record(**json.loads((record_path(root) / RECORD).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def is_doc(path: str) -> bool:
    return path.endswith(".md") or path.startswith("docs/")


def own_commits(root: Path, sha: str, remote: str) -> list[str]:
    """push 할 sha 에서 닿고 그 원격의 어느 브랜치에도 없는 merge 아닌 커밋."""

    return git("rev-list", "--no-merges", sha, "--not", f"--remotes={remote}", cwd=root).split()


def touched(root: Path, commits: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for c in commits:
        out |= set(git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", c, cwd=root).split("\n")) - {""}
    return out


def differ(root: Path, a: str, b: str, paths: Iterable[str]) -> list[str]:
    paths = sorted(paths)
    if not paths:
        return []
    return [p for p in git("diff", "--name-only", a, b, "--", *paths, cwd=root).split("\n") if p]


def verdict(root: Path, sha: str, remote: str) -> tuple[bool, str]:
    """(보내도 되나, 한 줄)."""

    mine = own_commits(root, sha, remote)
    if not mine:
        return True, "새 커밋 없음"
    for c in mine:
        body = git("log", "-1", "--format=%B", c, cwd=root)
        for line in body.splitlines():
            if line.startswith(f"{SKIP_TRAILER}:"):
                return True, f"우회 — {line.strip()} ({c[:8]})"
    paths = touched(root, mine)
    if all(is_doc(p) for p in paths):
        return True, "문서만"
    rec = read(root)
    how = "`scripts/test.sh affected` 를 돌린 뒤 다시 push 한다. 급하면 커밋에 꼬리말 `Local-Tests-Skipped: <까닭>`(PR 에 남는다)"
    if rec is None:
        return False, f"고른 시험을 돌린 기록이 없다 — {how}"
    if not rec.passed:
        return False, f"마지막 `scripts/test.sh affected` 가 실패했다({', '.join(rec.ran) or '-'}) — {how}"
    missing = [k for k, n in rec.picked.items() if n and k not in rec.ran]
    if missing:
        return False, f"고른 {', '.join(missing)} 을 돌리지 않았다(--only) — {how}"
    stale = differ(root, rec.tree, sha, paths)
    if stale:
        shown = ", ".join(stale[:3]) + (f" 외 {len(stale) - 3}" if len(stale) > 3 else "")
        return False, f"시험한 뒤 바뀐 파일: {shown} — {how}"
    return True, "시험한 내용 그대로"


def pre_push(root: Path, remote: str, lines: Iterable[str]) -> int:
    code = 0
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        _, local_sha, remote_ref, _ = parts
        if local_sha == ZERO or not remote_ref.startswith("refs/heads/"):
            continue  # 지우기·태그
        ok, why = verdict(root, local_sha, remote)
        branch = remote_ref.removeprefix("refs/heads/")
        if ok:
            if why.startswith("우회"):
                print(f"pre-push: {branch} — {why}", file=sys.stderr)
        else:
            print(f"pre-push: {branch} 로 보내지 않는다 — {why}", file=sys.stderr)
            code = 1
    return code


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "pre-push":
        root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip())
        remote = argv[2] if len(argv) > 2 else "origin"
        return pre_push(root, remote, sys.stdin.read().splitlines())
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
