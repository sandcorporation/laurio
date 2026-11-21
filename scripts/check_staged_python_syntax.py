#!/usr/bin/env python3
"""staged 된 백엔드 파이썬 파일이 파싱되는지 본다(#1226).

닫히지 않은 docstring 같은 문법 오류는 push 뒤 CI 의 `plan` 잡에서야 잡혔다. 커밋 훅이 부른다 —
`ast.parse` 라 `__pycache__` 를 쓰지 않고, 파일당 밀리초다. 백엔드의 파이썬(`uv run python`)으로
돌려야 그 버전의 문법으로 읽는다.

인자로 파일 경로를 받는다(없으면 staged 된 `backend/**/*.py`).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def staged_backend_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [p for p in out.splitlines() if p.startswith("backend/") and p.endswith(".py")]


def main(argv: list[str]) -> int:
    files = argv or staged_backend_files()
    bad = 0
    for name in files:
        path = ROOT / name
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=name)
        except SyntaxError as e:
            bad += 1
            print(f"{name}:{e.lineno}: 문법 오류 — {e.msg}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
