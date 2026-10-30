"""칸별 수에서 분위수를 낸다 — prometheus `histogram_quantile` 과 같은 선형 보간(#827).

순위 = q × 전체 수. 누적 수가 처음으로 순위에 닿는 칸에서, 그 칸의 아래 경계(첫 칸이면 0)와 위 경계
사이를 칸 안의 위치로 나눈다. 그 칸이 +Inf 면 가장 큰 유한 경계를 낸다. 수가 0 이면 None.
"""

from __future__ import annotations


def histogram_quantile(q: float, bounds: tuple, counts: list[int]) -> float | None:
    total = sum(counts)
    if total <= 0:
        return None
    rank = q * total
    cumulative = 0
    for index, count in enumerate(counts):
        previous = cumulative
        cumulative += count
        if cumulative >= rank and count > 0:
            if index >= len(bounds):
                return float(bounds[-1])
            lower = 0.0 if index == 0 else float(bounds[index - 1])
            upper = float(bounds[index])
            return lower + (upper - lower) * (rank - previous) / count
    return float(bounds[-1])


def add_counts(into: list[int], counts: list[int]) -> list[int]:
    """칸별 수를 더한다 — 길이가 다르면(경계가 늘었다) 긴 쪽에 맞춘다."""

    if len(into) < len(counts):
        into = into + [0] * (len(counts) - len(into))
    for index, count in enumerate(counts):
        into[index] += int(count)
    return into
