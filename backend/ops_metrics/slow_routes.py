"""느린 경로 판정(#971) — 경로(메서드 + URL 패턴)마다 「지금」과 「평소」의 중앙값을 견준다.

순수 함수만 둔다(Django·DB 를 부르지 않는다) — 1분 검사(`ops_metrics.alerts`)와 지난 기록 재생
(`scripts/slow_route_replay.py`)이 **같은 함수**로 판정하게 하려는 것이다.

**입력**은 경로 → 요청 시간 칸별 수(`core.metrics.DURATION_BOUNDS` 칸, 마지막이 +Inf)다. 중앙값은
`histogram_quantile(0.5, …)` — 칸 안을 선형 보간하므로 값은 근삿값이다(1초 칸 경계 위아래는 맞다).

**왜 평소 대비인가.** 원래 느린 경로(LLM 채점·업로드·스캔)가 울리지 않게, 제외 목록을 손으로 들지 않게.
평소 기록이 없는 경로(새 경로)는 울리지 않는다 — 견줄 것이 없다.

**왜 전체 평균이 아닌가.** 요청 적은 경로(하루 몇 건)가 묻힌다(#958 의 `api/contests/mine`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .quantile import add_counts, histogram_quantile

#: 경로 → 요청 시간 칸별 수.
Histograms = Mapping[str, list[int]]


@dataclass(frozen=True)
class Criteria:
    """한 규칙의 기준 — 창 길이와 「느리다」의 세 조건."""

    #: 「지금」 창의 길이(분).
    window_minutes: int
    #: 창 안 요청이 이만큼은 있어야 본다.
    min_requests: int
    #: 창 중앙값이 이 초 이상이어야 한다.
    min_median_seconds: float
    #: 창 중앙값 ÷ 평소 중앙값이 이 배수 이상이어야 한다.
    min_ratio: float
    #: 「평소」 = 창 바로 앞 이 날수.
    usual_days: int = 14
    #: 울리는 경로가 해소되려면 연속으로 느리지 않아야 하는 검사 수.
    clear_checks: int = 1


#: 1분 검사 — 최근 30분 요청 3건 이상, 중앙값 1초 이상, 평소(앞 14일)의 5배 이상. 60번(1시간) 연속 괜찮아야 해소.
REALTIME = Criteria(window_minutes=30, min_requests=3, min_median_seconds=1.0, min_ratio=5.0, clear_checks=60)
#: 하루 한 번 — 어제(서울) 하루치. 하루 몇 건뿐인 경로를 잡는 몫이라 최소 요청을 1건으로 낮춘다.
DAILY = Criteria(window_minutes=24 * 60, min_requests=1, min_median_seconds=1.0, min_ratio=5.0)


@dataclass(frozen=True)
class SlowRoute:
    route: str
    requests: int
    median_seconds: float
    usual_median_seconds: float
    usual_requests: int

    @property
    def ratio(self) -> float:
        return self.median_seconds / self.usual_median_seconds if self.usual_median_seconds > 0 else float("inf")


def median(bounds: tuple[float, ...], counts: list[int]) -> float | None:
    return histogram_quantile(0.5, bounds, counts)


def candidates(window: Histograms, bounds: tuple[float, ...], criteria: Criteria) -> list[str]:
    """평소를 보기 전에 창만으로 걸러지는 경로 — 요청 수와 절대 중앙값을 넘은 것(평소를 읽는 비용을 아낀다)."""

    found = []
    for route, counts in window.items():
        if sum(counts) < criteria.min_requests:
            continue
        value = median(bounds, counts)
        if value is not None and value >= criteria.min_median_seconds:
            found.append(route)
    return sorted(found)


def judge(window: Histograms, usual: Histograms, bounds: tuple[float, ...], criteria: Criteria) -> list[SlowRoute]:
    """창이 느린 경로 — 후보 가운데 평소 중앙값의 `min_ratio` 배를 넘은 것. 경로 이름 순."""

    slow = []
    for route in candidates(window, bounds, criteria):
        usual_counts = usual.get(route, [])
        usual_median = median(bounds, usual_counts)
        if usual_median is None:
            continue
        now_median = median(bounds, window[route])
        assert now_median is not None  # 후보는 요청이 있다
        found = SlowRoute(route, sum(window[route]), now_median, usual_median, sum(usual_counts))
        if found.ratio >= criteria.min_ratio:
            slow.append(found)
    return slow


@dataclass(frozen=True)
class Latch:
    """한 경로의 울림 상태 — 울리는가, 그리고 울리는 중 연속으로 괜찮았던 검사 수."""

    firing: bool = False
    clear: int = 0


def advance(latch: Latch, slow: bool, criteria: Criteria) -> tuple[Latch, str | None]:
    """한 번의 검사 결과로 상태를 옮긴다. 울리기 시작하면 `"firing"`, 해소되면 `"resolved"`, 그 밖은 None.

    울리는 중에는 느린 검사가 끼면 `clear` 가 0 으로 돌아간다 — 요청이 띄엄띄엄인 경로가 창에서 빠졌다
    들어왔다 하며 몇 분 사이에 해소·재발을 거듭하지 않게(재생에서 4분 만에 다시 울린 일이 있었다).
    """

    if slow:
        return Latch(True, 0), (None if latch.firing else "firing")
    if not latch.firing:
        return latch, None
    if latch.clear + 1 >= criteria.clear_checks:
        return Latch(), "resolved"
    return Latch(True, latch.clear + 1), None


def merge(rows: Iterable[tuple[str, list[int]]]) -> dict[str, list[int]]:
    """(경로, 칸별 수) 행들을 경로마다 더한다."""

    merged: dict[str, list[int]] = {}
    for route, counts in rows:
        merged[route] = add_counts(merged.get(route, []), list(counts))
    return merged
