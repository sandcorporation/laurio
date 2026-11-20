"""바뀐 경로가 어느 묶음인가 — PR 검사의 계획 판정이 모두 읽는 표 하나(#1088 리팩터).

    python3 scripts/ci/paths.py <기준 커밋> [끝 커밋=HEAD]   →  TESTS=0|1  BACK=0|1  FRONT=0|1  (changed.sh 가 부른다)

`changed.sh`(어느 잡), `e2e_plan.py`·`pytest_plan.py`(어느 시험) 가
같은 경로를 따로 가르던 것을 이 표 하나로 모았다. 앱 단위의 판단은 여기 없다 — `backend/app_deps.toml` 이 들고 있다.

표는 위에서부터 처음 맞는 줄이다(`.md` 가 맨 위라 `backend/README.md` 도 문서다).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from typing import Literal

Kind = Literal["docs", "backend", "image", "front", "common"]

#: (앞부분 또는 끝부분, 묶음) — 끝부분은 `*` 로 시작한다
TABLE: tuple[tuple[str, Kind], ...] = (
    ("*.md", "docs"),
    ("docs/", "docs"),
    ("backend/", "backend"),  # 백엔드 코드·시험·uv.lock
    ("docker/", "image"),  # 이미지·compose — 백엔드 묶음을 돌리고, 시험 선택은 전부
    ("frontend/", "front"),
    ("operator/", "front"),
    ("classroom/", "front"),
    ("packages/", "front"),
)
# 그 밖(.github/·scripts/·루트 설정·pnpm-lock 등)은 common — 전부


def kind(path: str) -> Kind:
    for pattern, k in TABLE:
        if pattern.startswith("*") and path.endswith(pattern[1:]):
            return k
        if not pattern.startswith("*") and path.startswith(pattern):
            return k
    return "common"


def bundles(files: Iterable[str]) -> tuple[str, str, str]:
    """바뀐 파일 → (TESTS, BACK, FRONT). 바뀐 파일이 없으면(기준을 모르거나 main push) 전부."""

    kinds = {kind(f) for f in files if f}
    if not kinds:
        return ("1", "1", "1")
    common = "common" in kinds
    back = common or bool(kinds & {"backend", "image"})
    front = common or "front" in kinds
    tests = back or front
    return ("1" if tests else "0", "1" if back else "0", "1" if front else "0")


def diff(base: str, head: str = "HEAD") -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", base, head], check=True, capture_output=True, text=True).stdout
    return out.splitlines()


def main(argv: list[str]) -> int:
    files = diff(argv[0], argv[1] if len(argv) > 1 else "HEAD") if argv and argv[0] else []
    tests, back, front = bundles(files)
    print(f"TESTS={tests}\nBACK={back}\nFRONT={front}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
