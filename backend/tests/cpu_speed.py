"""시험 CPU 한도를 실행기 속도에 맞춘다 (#1163).

PR 검사의 호스티드 실행기는 같은 일에 드는 CPU 초가 셋으로 갈린다 — 2026-11-19~21
실행 85회·조각 376개의 junit 에서 조각마다 「시험별 중앙값 대비 배율」의 중앙값을 내면
약 0.62·0.95·1.22 세 무리였고(최소 0.55, 최대 1.42), 같은 실행 안의 조각끼리도 0.59씩
벌어졌다. 한도에 걸린 시험의 CPU 초는 그 배율과 상관계수 0.87~0.98 로 움직였다 —
헛실패는 시험이 아니라 실행기가 정했다.

그래서 한도를 넘은 시험이 나오면 그 자리에서 고정된 순수 파이썬 일감을 돌려 실행기가
기준보다 얼마나 느린지 재고, 그만큼 한도를 늘려 준다. 기준(`REFERENCE_SECONDS`)은 위
가운데 무리의 실행기가 이 일감에 쓰는 CPU 초를 겨냥한다. 배율은 `MIN_SCALE`~`MAX_SCALE`
안으로 묶는다 — 빠른 실행기에서 한도를 지금보다 조이지 않고, 기준을 잘못 잡았거나 측정이
튀어도 한도가 1.5배를 넘게 풀리지 않는다.
"""

from __future__ import annotations

import statistics
import time

# 가운데 무리(배율 약 1.0)의 실행기가 `_work()` 한 번에 쓰는 CPU 초.
# 개발 머신(i7-8700, 한 코어 고정, load 5 안팎)에서 0.0247초였고, 같은 머신에서 한도 근처
# 시험 다섯의 CPU 초는 CI 중앙값의 1/2.68~1/2.94(평균 1/2.78)였다 — 0.0247 × 2.78 ≈ 0.070.
# 일감 한 번의 값이 0.07초라 한도를 넘은 시험 하나에 0.35초(다섯 번)가 붙는다 — 드물다.
# junit 의 `cpu_scale` 로 실제 실행기의 값을 보고 다시 맞춘다.
REFERENCE_SECONDS = 0.070
MIN_SCALE = 1.0
MAX_SCALE = 1.5
_REPEATS = 5


def _work() -> int:
    """정해진 양의 순수 파이썬 일 — 딕셔너리·문자열·정렬(ORM·직렬화가 하는 일의 모양)."""
    table: dict[str, int] = {}
    for i in range(120_000):
        key = f"k{i % 997}"
        table[key] = table.get(key, 0) + i
    rows = sorted(table.items(), key=lambda kv: (kv[1] % 13, kv[0]))
    return sum(len(k) + v % 7 for k, v in rows)


def work_seconds() -> float:
    """`_work()` 를 몇 번 돌린 CPU 초의 중앙값 — 한두 번 끊기는 것에 휘둘리지 않는다."""
    samples = []
    for _ in range(_REPEATS):
        started = time.process_time()
        _work()
        samples.append(time.process_time() - started)
    return statistics.median(samples)


def scale_for(seconds: float) -> float:
    """일감 CPU 초 → 한도에 곱할 배율(`MIN_SCALE`~`MAX_SCALE`)."""
    return min(MAX_SCALE, max(MIN_SCALE, seconds / REFERENCE_SECONDS))


def measured_scale() -> float:
    return scale_for(work_seconds())
