"""시험 CPU 한도를 실행기 속도에 맞춘다 (#1163, #1211).

PR 검사의 호스티드 실행기는 같은 일에 드는 CPU 초가 셋으로 갈린다 — 2026-11-19~21
실행 85회·조각 376개의 junit 에서 조각마다 「시험별 중앙값 대비 배율」의 중앙값을 내면
약 0.62·0.95·1.22 세 무리였고(최소 0.55, 최대 1.42), 같은 실행 안의 조각끼리도 0.59씩
벌어졌다. 한도에 걸린 시험의 CPU 초는 그 배율과 상관계수 0.87~0.98 로 움직였다 —
헛실패는 시험이 아니라 실행기가 정했다.

**잴 것은 시험들 자신이다.** 처음(#1163)에는 한도를 넘은 자리에서 고정된 순수 파이썬
일감을 돌려 쟀는데, 2026-11-21 한도에 걸린 여섯 번이 모두 배율 1.00 이었다 — 같은
조각의 다른 시험들은 중앙값보다 1.26~1.39배 느리게 돌고 있었는데도(#1211). 순수 파이썬
일감은 시험이 쓰는 CPU(ORM·psycopg·소켓 시스템 호출)의 느림을 따라가지 않았다.

그래서 이 프로세스가 이미 돌린 시험마다 「쓴 CPU 초 / 그 시험의 기준 CPU 초」를 모으고,
한도를 넘은 시험이 나오면 그 비율의 중앙값을 배율로 쓴다. 기준은 최근 병합 대기열
실행들의 junit 에서 시험마다 낸 중앙값이다(`cpu_reference.json`, 실행기 셋이 섞인 값이라
배율 1.0 이 가운데 무리다). `scripts/ci/cpu-reference-update.sh` 가 다시 쓴다.

배율은 `MIN_SCALE`~`MAX_SCALE` 안으로 묶는다 — 빠른 실행기에서 한도를 지금보다 조이지
않고, 기준이 낡았거나 측정이 튀어도 한도가 1.5배를 넘게 풀리지 않는다. 비교할 시험이
`MIN_SAMPLES` 개가 안 되면(조각의 첫머리, 로컬에서 파일 하나) 1.0 이다.

**기준이 낡았는지는 검사가 말한다**(#1222). 기준을 새로 쓴 직후에는 같은 실행들의 시험별
중앙값이라 「시험 CPU 초 / 기준」의 중앙값이 1.0 근처다. 무거운 시험을 고치거나 옮기면 그 값이
1.0 에서 멀어진다 — 낮아지면 배율이 1.0 에 붙어 느린 실행기에 한도를 풀어 주지 못하고, 높아지면
빠른 실행기에서도 한도가 풀린다. `drift` 가 최근 실행마다 그 중앙값을, 실행들의 값의 중앙값을
내고 `DRIFT_LOW`~`DRIFT_HIGH` 밖이면 종료 코드 3 으로 알린다(`scripts/ci/cpu-reference-watch.sh`).

    python3 backend/tests/cpu_speed.py update JUNIT.xml...   # 기준을 다시 쓴다
    python3 backend/tests/cpu_speed.py drift RUN_DIR...       # 기준이 낡았나 (디렉터리 하나 = 실행 하나)
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

MIN_SCALE = 1.0
MAX_SCALE = 1.5
# 이보다 적게 비교했으면 배율을 믿지 않는다 — 조각 하나의 워커는 보통 수십 개를 먼저 돈다.
MIN_SAMPLES = 10
# 기준에 넣는 시험의 중앙값 하한 — 이보다 가벼운 시험은 비율이 잡음에 휘둘린다.
MIN_REFERENCE_SECONDS = 0.2
# 기준에 넣으려면 실행 몇 번에서 잡혀야 하나.
MIN_RUNS = 3

REFERENCE = Path(__file__).with_name("cpu_reference.json")

# 실행들의 중앙값이 이 범위 밖이면 기준이 낡았다(#1222). 실행기 세 무리(약 0.62·0.95·1.22)에서
# 실행 8번을 뽑으면 가운데 무리가 중앙값을 쥔다 — 새 기준의 값은 0.95~1.0 근처다. 아래는 빠른 무리
# 쪽으로 반쯤(0.85), 위는 느린 무리(1.22)에 닿기 전(1.2)에서 끊는다.
DRIFT_LOW = 0.85
DRIFT_HIGH = 1.2


def junit_key(nodeid: str) -> str:
    """pytest 노드 ID → junit 의 `classname::name` (`_pytest.junitxml.mangle_test_address` 와 같은 규칙)."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]) + "::" + names[-1]


def load_reference(path: Path = REFERENCE) -> dict[str, float]:
    if not path.exists():
        return {}
    return {str(k): float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


class RunnerPace:
    """이 프로세스가 돈 시험들이 기준보다 얼마나 느렸나."""

    def __init__(self, reference: Mapping[str, float]) -> None:
        self._reference = reference
        self._ratios: list[float] = []

    def record(self, key: str, cpu_seconds: float) -> None:
        expected = self._reference.get(key)
        if expected:
            self._ratios.append(cpu_seconds / expected)

    @property
    def ratios(self) -> list[float]:
        return list(self._ratios)

    @property
    def samples(self) -> int:
        return len(self._ratios)

    def scale(self) -> float:
        if len(self._ratios) < MIN_SAMPLES:
            return MIN_SCALE
        return min(MAX_SCALE, max(MIN_SCALE, statistics.median(self._ratios)))


def reference_from_junit(paths: Iterable[Path]) -> dict[str, float]:
    """junit 여럿 → 시험마다 CPU 초 중앙값(`MIN_RUNS` 번 넘게 잡히고 `MIN_REFERENCE_SECONDS` 이상)."""
    seen: defaultdict[str, list[float]] = defaultdict(list)
    for path in paths:
        for case in ET.parse(path).iter("testcase"):
            props = {p.get("name"): p.get("value") for p in case.iter("property")}
            cpu = props.get("cpu_seconds")
            if cpu is not None:
                seen[f"{case.get('classname')}::{case.get('name')}"].append(float(cpu))
    out = {}
    for key, values in seen.items():
        if len(values) >= MIN_RUNS and (median := statistics.median(values)) >= MIN_REFERENCE_SECONDS:
            out[key] = round(median, 3)
    return dict(sorted(out.items()))


def run_pace(junits: Iterable[Path], reference: Mapping[str, float]) -> RunnerPace:
    """한 실행(조각 여럿)의 junit → 기준에 있는 시험마다의 비율."""
    pace = RunnerPace(reference)
    for path in junits:
        for case in ET.parse(path).iter("testcase"):
            cpu = next((p.get("value") for p in case.iter("property") if p.get("name") == "cpu_seconds"), None)
            if cpu is not None:
                pace.record(f"{case.get('classname')}::{case.get('name')}", float(cpu))
    return pace


@dataclass(frozen=True)
class Drift:
    runs: dict[str, tuple[float, int]]  # 실행 이름 → (비율 중앙값, 비교한 시험 수)
    median: float | None  # 실행들의 값의 중앙값 — 비교할 실행이 없으면 None
    low: float = DRIFT_LOW
    high: float = DRIFT_HIGH

    @property
    def stale(self) -> bool:
        return self.median is not None and not self.low <= self.median <= self.high

    def report(self) -> str:
        lines = [f"- 실행 {name}: {value:.3f} (시험 {n}개)" for name, (value, n) in self.runs.items()]
        head = "비교할 실행이 없다" if self.median is None else f"실행 {len(self.runs)}번의 중앙값 **{self.median:.3f}**"
        return "\n".join([f"{head} — 범위 {self.low}~{self.high}", "", *lines])


def drift(runs: Mapping[str, Iterable[Path]], reference: Mapping[str, float]) -> Drift:
    """실행마다 「시험 CPU 초 / 기준」의 중앙값, 그 값들의 중앙값. 비교한 시험이 `MIN_SAMPLES` 개 안 되는 실행은 뺀다."""
    out: dict[str, tuple[float, int]] = {}
    for name, junits in runs.items():
        pace = run_pace(junits, reference)
        if pace.samples >= MIN_SAMPLES:
            out[name] = (round(statistics.median(pace.ratios), 3), pace.samples)
    median = round(statistics.median(v for v, _ in out.values()), 3) if out else None
    return Drift(out, median)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "update":
        table = reference_from_junit(Path(p) for p in argv[1:])
        REFERENCE.write_text(json.dumps(table, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        print(f"{REFERENCE.name}: 시험 {len(table)}개")
        return 0
    if len(argv) >= 2 and argv[0] == "drift":
        dirs = [Path(p) for p in argv[1:]]
        result = drift({d.name: sorted(d.rglob("*.xml")) for d in dirs}, load_reference())
        print(result.report())
        return 3 if result.stale else 0
    print("\n".join(__doc__.rstrip().splitlines()[-2:]))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
