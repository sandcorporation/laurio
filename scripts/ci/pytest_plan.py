"""백엔드 pytest 를 무엇을, 몇 조각으로 돌지 — 바뀐 파일 → 앱 → 시험 파일 → 조각(#1088, spec #1079).

    python3 scripts/ci/pytest_plan.py --base <기준 커밋>   # PR: 바뀐 앱과 그 앱에 기대는 앱의 시험만
    python3 scripts/ci/pytest_plan.py --all                # 병합 대기열·main: 전부

고르는 규칙(e2e_plan.py 와 같은 꼴, 앱은 `scripts/app_deps.py` 의 `affected` 가 고른다):
- `backend/<앱>/…`                → affected 가 고른 앱(바뀐 앱 + 그 앱을 쓰는·읽는 앱 + 그 앱들이 꽂힌 앱)의 `<앱>/tests/`
- `backend/tests/**/test_*.py`     → 그 시험 파일만(시험만 고친 것)
- 그 밖의 backend(config·conftest·시험 도우미·pyproject·uv.lock) · docker/ · scripts/ · .github/ · 루트 → 전부
- 문서(.md·docs/) · 앞단(frontend/·operator/·classroom/·packages/) → pytest 없음(changed.sh 의 BACK=0)
- 앱 사이 시험(`tests/integration/`)은 **닿는 앱**(import·주소 — `tests_layout.py` 가 자리를 정한 규칙 그대로)이 고른
  앱과 겹칠 때만 돈다. 다 안 보이는 파일(전체 주소·손으로 자리를 정한 것)은 늘 돈다.
- 구조·전체 주소 시험(`tests/` 바로 아래)은 pytest 가 돌면 늘 돈다 — 경계 시험이 여기 있다.

출력(줄마다 `KEY=값`): `PYTEST=0|1`, `ALL=0|1`, `MATRIX={"include":[{"name","args"}…]}`(checks 잡 조각),
`FILES=<backend 기준 시험 파일, 빈칸으로>`(ALL=1 이면 비운다 — 조각이 저장소의 시험 전부를 나눈다).
조각 수는 시간 기록(pytest-durations.json)의 합을 SHARD_SECONDS 로 나눈 것(1~MAX_SHARDS)이라 전부면 MAX_SHARDS 다.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_deps import Declared, affected, load_table  # noqa: E402
from paths import kind  # noqa: E402
from pytest_shards import read_record, test_files  # noqa: E402
from tests_layout import touched as _touched  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
#: 조각 하나가 맡을 시험 시간(기록 기준, 초). 기록 합 ~720초 → 전부면 6조각, 조각마다 xdist 로 ~60초.
SHARD_SECONDS = 120.0
MAX_SHARDS = 6
#: 통합 시험마다 닿는 앱 — 시험 파일 전부를 읽어 1초 남짓이라 한 번만
touched = functools.cache(_touched)


def select(
    changed: Iterable[str],
    table: Mapping[str, Declared],
    files: list[str],
    reach: Mapping[str, set[str] | None],
) -> set[str] | None:
    """바뀐 파일 → 돌 시험 파일(backend 기준). None 이면 전부."""

    present = set(files)
    backend: list[str] = []
    direct: set[str] = set()
    for f in changed:
        k = kind(f)
        if k in ("docs", "front"):
            continue
        rel = f.removeprefix("backend/")
        if f.startswith("backend/tests/") and Path(f).name.startswith("test_") and f.endswith(".py"):
            if rel in present:
                direct.add(rel)
            # 지운 시험 파일은 돌릴 것이 없다
            continue
        if k != "backend":
            return None
        backend.append(f)
    apps: set[str] = set()
    if backend:
        found = affected(backend, table)
        if found is None:
            return None
        apps = found
    if not apps and not direct:
        return set()
    out = set(direct)
    for f in files:
        top = f.split("/", 1)[0]
        if top in apps:
            out.add(f)
        elif f.startswith("tests/integration/"):
            hit = reach.get(f)
            if apps and (hit is None or hit & apps):
                out.add(f)
        elif top == "tests":  # 구조·전체 주소 시험
            out.add(f)
    return out


def shard_count(chosen: Iterable[str], durations: Mapping[str, float]) -> int:
    chosen = list(chosen)
    known = list(durations.values())
    default = sum(known) / len(known) if known else 1.0
    cost = sum(durations.get(f, default) for f in chosen)
    return max(1, min(MAX_SHARDS, math.ceil(cost / SHARD_SECONDS)))


def plan(changed: list[str] | None) -> dict[str, str]:
    files = test_files()
    chosen = None if changed is None else select(changed, load_table(), files, touched())
    if chosen is not None and chosen >= set(files):
        chosen = None
    if chosen is not None and not chosen:
        return {"PYTEST": "0", "ALL": "0", "MATRIX": json.dumps({"include": []}), "FILES": ""}
    n = shard_count(files if chosen is None else chosen, read_record())
    include = [{"name": f"pytest-{i}of{n}", "args": f"pytest {i}/{n}"} for i in range(1, n + 1)]
    return {
        "PYTEST": "1",
        "ALL": "1" if chosen is None else "0",
        "MATRIX": json.dumps({"include": include}, separators=(",", ":")),
        "FILES": "" if chosen is None else " ".join(sorted(chosen)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", help="기준 커밋 — 이 뒤로 바뀐 파일만 본다")
    parser.add_argument("--all", action="store_true", help="전부(병합 대기열·main)")
    args = parser.parse_args()
    changed: list[str] | None = None
    if args.base and not args.all:
        diff = subprocess.run(["git", "diff", "--name-only", args.base, "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True)
        changed = diff.stdout.split() or None  # 바뀐 것이 없으면(main push) 전부
    for key, value in plan(changed).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
