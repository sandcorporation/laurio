#!/usr/bin/env python3
"""백엔드 pytest 를 시험 시간 기준으로 조각낸다(#1083).

    pytest_shards.py pick I N                 I번째(1부터) 조각의 시험 파일(backend/ 기준)을 한 줄씩
                                              (CODEMIT_PYTEST_FILES 가 있으면 그 파일들만 나눈다 — PR 의 선택 실행, #1088)
    pytest_shards.py update JUNIT.xml...      junit 결과로 시간 기록(pytest-durations.json)을 다시 쓴다

조각은 파일 단위다. 시간이 긴 파일부터 지금까지 가장 가벼운 조각에 넣는다(같으면 앞 조각) — 같은
파일 목록·기록이면 어느 실행기에서나 같은 조각이 나온다. 기록에 없는 파일(새 시험)은 기록된 파일의
평균값으로 센다(갱신 때 있던 파일은 junit 에 없으면 0). 기록 갱신은 `scripts/ci/pytest-durations-update.sh`(main 실행의 junit 산출물을 받아
이 스크립트의 update 를 부른다)로 사람이 하고 커밋한다.
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
RECORD = Path(__file__).resolve().parent / "pytest-durations.json"


def test_files(backend: Path = BACKEND) -> list[str]:
    """backend/ 기준 시험 파일 — `tests/`(통합·구조)와 앱마다 `<앱>/tests/`(#1087). python_files=test_*.py."""
    found = [*(backend / "tests").rglob("test_*.py"), *backend.glob("*/tests/**/test_*.py")]
    return sorted({p.relative_to(backend).as_posix() for p in found})


def chosen_files(env: str | None = None) -> list[str]:
    """나눌 시험 파일 — `CODEMIT_PYTEST_FILES`(pytest_plan.py 의 FILES, 빈칸으로)가 있으면 그것만, 없으면 전부."""
    raw = os.environ.get("CODEMIT_PYTEST_FILES", "") if env is None else env
    every = test_files()
    if not raw.strip():
        return every
    wanted = set(raw.split())
    missing = sorted(wanted - set(every))
    if missing:
        raise SystemExit(f"CODEMIT_PYTEST_FILES 에 없는 시험 파일: {', '.join(missing)}")
    return sorted(wanted)


def shards(files: Iterable[str], durations: Mapping[str, float], total: int) -> list[list[str]]:
    files = sorted(set(files))
    known = [durations[f] for f in files if f in durations]
    default = sum(known) / len(known) if known else 1.0
    cost = {f: durations.get(f, default) for f in files}
    loads = [0.0] * total
    out: list[list[str]] = [[] for _ in range(total)]
    for f in sorted(files, key=lambda f: (-cost[f], f)):
        i = min(range(total), key=lambda k: (loads[k], k))
        loads[i] += cost[f]
        out[i].append(f)
    return [sorted(s) for s in out]


def file_of(classname: str, files: set[str]) -> str | None:
    """junit classname(`tests.sub.test_x.TestY`) → `tests/sub/test_x.py`. 가장 긴 앞부분이 실제 파일인 것."""
    parts = classname.split(".")
    for n in range(len(parts), 0, -1):
        candidate = "/".join(parts[:n]) + ".py"
        if candidate in files:
            return candidate
    return None


def durations_from_junit(paths: Iterable[Path], files: set[str]) -> dict[str, float]:
    """파일별 시간 합. 지금 있는 파일인데 junit 에 없으면(기본 실행이 빼는 live 표식 시험 등) 0 — 평균으로 세지 않는다."""
    totals: dict[str, float] = dict.fromkeys(files, 0.0)
    for path in paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            f = file_of(case.get("classname", ""), files)
            if f is not None:
                totals[f] = totals.get(f, 0.0) + float(case.get("time") or 0.0)
    return {f: round(t, 2) for f, t in sorted(totals.items())}


def read_record(path: Path = RECORD) -> dict[str, float]:
    if not path.exists():
        return {}
    data: dict[str, float] = json.loads(path.read_text())
    return data


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "pick":
        idx, total = int(argv[1]), int(argv[2])
        if not 1 <= idx <= total:
            print(f"조각 번호가 범위 밖이다: {idx}/{total}", file=sys.stderr)
            return 2
        print("\n".join(shards(chosen_files(), read_record(), total)[idx - 1]))
        return 0
    if len(argv) >= 2 and argv[0] == "update":
        record = durations_from_junit((Path(p) for p in argv[1:]), set(test_files()))
        if not record:
            print("junit 에서 시험 시간을 하나도 못 읽었다", file=sys.stderr)
            return 1
        RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
        print(f"{len(record)}개 파일, 합 {sum(record.values()):.0f}초 → {RECORD.relative_to(ROOT)}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
