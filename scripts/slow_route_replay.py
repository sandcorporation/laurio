"""느린 경로 규칙(#971)을 지난 요청 지표에 돌려 본다 — 1분 검사와 같은 판정 함수(`ops_metrics.slow_routes`).

입력은 `ops_metrics_requestminute` 를 내보낸 CSV(epoch 초, method, route, status, requests, duration_buckets)다.
운영 DB 는 읽기 전용으로만 내보낸다(`docs/ops/operations.md` 「느린 경로 경고」). CSV 는 저장소에 넣지 않는다.

    uv run --project backend python scripts/slow_route_replay.py rows.csv --since 2026-11-04

출력: 실시간·일일 규칙이 울리기 시작한 시각(서울)과 경로, 경로별 횟수.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import dataclasses
import json
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from core.metrics import DURATION_BOUNDS  # noqa: E402
from ops_metrics.quantile import add_counts  # noqa: E402
from ops_metrics.slow_routes import (  # noqa: E402
    DAILY,
    REALTIME,
    Criteria,
    Latch,
    SlowRoute,
    advance,
    candidates,
    judge,
)

SEOUL = timezone(timedelta(hours=9))
Series = dict[str, list[tuple[int, list[int]]]]


def load(path: Path) -> Series:
    by_route: dict[str, dict[int, list[int]]] = defaultdict(dict)
    with path.open() as handle:
        for epoch, method, route, _status, _requests, buckets in csv.reader(handle):
            key = f"{method} {route}"
            minute = int(epoch)
            by_route[key][minute] = add_counts(by_route[key].get(minute, []), json.loads(buckets))
    return {key: sorted(minutes.items()) for key, minutes in by_route.items()}


def between(series: Series, route: str, start: int, end: int) -> list[int]:
    """[start, end) 의 칸별 수 합."""

    rows = series.get(route, [])
    minutes = [minute for minute, _ in rows]
    total: list[int] = []
    for _, counts in rows[bisect.bisect_left(minutes, start) : bisect.bisect_left(minutes, end)]:
        total = add_counts(total, counts)
    return total


def usual_of(series: Series, routes: list[str], start: int, criteria: Criteria) -> dict[str, list[int]]:
    return {route: between(series, route, start - criteria.usual_days * 86400, start) for route in routes}


def _seoul(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, SEOUL).strftime("%m-%d %H:%M")


def _line(at: int, found: SlowRoute) -> str:
    return (
        f"{_seoul(at)}  {found.route}  지금 {found.median_seconds:.2f}s ({found.requests}건)"
        f"  평소 {found.usual_median_seconds * 1000:.0f}ms ({found.usual_requests}건)  ×{found.ratio:.0f}"
    )


def replay_realtime(series: Series, since: int, until: int, criteria: Criteria = REALTIME) -> list[tuple[int, SlowRoute]]:
    """1분마다 최근 `window_minutes` 분을 본다. 울리기 시작한 순간만 돌려준다(해소 뒤 다시 울리면 또)."""

    span = criteria.window_minutes * 60
    by_minute: dict[int, list[tuple[str, list[int]]]] = defaultdict(list)
    for route, rows in series.items():
        for minute, counts in rows:
            by_minute[minute].append((route, counts))
    window: dict[str, list[int]] = defaultdict(list)
    recent: deque[int] = deque()
    latches: dict[str, Latch] = {}
    fired: list[tuple[int, SlowRoute]] = []
    for now in range(since - span + 60, until + 60, 60):
        for route, counts in by_minute.get(now, []):
            window[route] = add_counts(window[route], counts)
        recent.append(now)
        while recent and recent[0] <= now - span:
            gone = recent.popleft()
            for route, counts in by_minute.get(gone, []):
                window[route] = [a - b for a, b in zip(window[route], counts + [0] * (len(window[route]) - len(counts)))]
        if now < since:
            continue
        start = now - span + 60
        live = {route: counts for route, counts in window.items() if sum(counts)}
        slow = {found.route: found for found in judge(live, usual_of(series, candidates(live, DURATION_BOUNDS, criteria), start, criteria), DURATION_BOUNDS, criteria)}
        _latch(latches, slow, criteria, now, fired)
    return fired


def _latch(latches: dict[str, Latch], slow: dict[str, SlowRoute], criteria: Criteria, at: int, fired: list) -> None:
    for route in set(latches) | set(slow):
        latches[route], event = advance(latches.get(route, Latch()), route in slow, criteria)
        if event == "firing":
            fired.append((at, slow[route]))


def replay_daily(series: Series, since: int, until: int, criteria: Criteria = DAILY) -> list[tuple[int, SlowRoute]]:
    """서울 하루마다 그날을 본다(다음 날 00:10 에 판정). 전날도 울렸으면 새로 세지 않는다."""

    latches: dict[str, Latch] = {}
    fired: list[tuple[int, SlowRoute]] = []
    day = datetime.fromtimestamp(since, SEOUL).replace(hour=0, minute=0)
    while int(day.timestamp()) + 86400 <= until + 60:
        start = int(day.timestamp())
        window = {route: between(series, route, start, start + 86400) for route in series}
        window = {route: counts for route, counts in window.items() if sum(counts)}
        slow = {found.route: found for found in judge(window, usual_of(series, candidates(window, DURATION_BOUNDS, criteria), start, criteria), DURATION_BOUNDS, criteria)}
        _latch(latches, slow, criteria, start + 86400 + 600, fired)
        day += timedelta(days=1)
    return fired


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--since", default="2026-11-04", help="서울 날짜")
    parser.add_argument("--set", action="append", default=[], help="기준 덮어쓰기, 예 usual_days=28 (두 규칙 모두)")
    args = parser.parse_args()
    changes = {name: type(getattr(REALTIME, name))(value) for name, value in (item.split("=", 1) for item in args.set)}
    realtime, daily = dataclasses.replace(REALTIME, **changes), dataclasses.replace(DAILY, **changes)
    series = load(args.csv)
    since = int(datetime.fromisoformat(args.since).replace(tzinfo=SEOUL).timestamp())
    until = max(rows[-1][0] for rows in series.values())
    print(f"기간 {_seoul(since)} ~ {_seoul(until)} (서울), 경로 {len(series)}개")
    for name, fired in (("실시간", replay_realtime(series, since, until, realtime)), ("일일", replay_daily(series, since, until, daily))):
        print(f"\n## {name} — 울림 {len(fired)}회")
        for at, found in fired:
            print(_line(at, found))
        for route, n in Counter(found.route for _, found in fired).most_common():
            print(f"  {n}회  {route}")


if __name__ == "__main__":
    main()
