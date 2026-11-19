"""느린 경로 경고(#971) — 요청 지표(`RequestMinute` + 아직 옮기지 않은 Redis 분)를 경로별로 보고 GlitchTip 에 올린다.

판정은 `ops_metrics.slow_routes`(순수 함수 — 지난 기록 재생도 같은 함수)이고, 여기는 DB 읽기·상태·보내기다.

- **1분 검사** — `ops_metrics.check_alerts`(beat 1분)가 같은 advisory 잠금 안에서 `check_realtime` 을 부른다. 창은
  운영 경보와 같다: 지금 분(쓰는 중)과 그 앞의 29개 닫힌 분.
- **하루 판정** — beat 가 매일 00:10(서울) `ops_metrics.check_slow_routes_daily` 로 `check_daily` 를 부른다. 창은 어제
  (서울) 하루다.

**보내는 곳은 GlitchTip 이다**(디스코드가 아니다 — 2026-11-19 대표 결정). `warning` 등급 메시지 하나, 지문
`["slow-route", "<메서드> <URL 패턴>"]` — 1분 검사와 하루 판정이 같은 경로를 보면 이슈 하나에 모인다. 울리기 시작할 때만
보낸다(해소는 보내지 않는다 — SDK 로는 이슈를 닫을 수 없고, 닫는 것은 자동 진단·사람의 몫이다). 보내는 값은 URL 패턴
(`resolver_match.route`)과 수치뿐이다 — 실제 경로·사용자는 없다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from core.metrics import DURATION_BOUNDS
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q

from .flush import _buckets, _grouped
from .models import AlertState, RequestMinute
from .quantile import add_counts
from .recorder import REQUEST, minute_key, minute_of
from .slow_routes import (
    DAILY,
    REALTIME,
    Criteria,
    Histograms,
    Latch,
    SlowRoute,
    advance,
    candidates,
    judge,
    merge,
)
from .store import get_store

logger = logging.getLogger("codemit.ops_metrics")

REALTIME_PREFIX = "slow-route:"
DAILY_PREFIX = "slow-route-daily:"
#: 하루 판정이 겹쳐 돌면 기다린다(두 번째는 이미 울리는 상태를 보고 다시 보내지 않는다).
_DAILY_LOCK_ID = 971_000_001
#: GlitchTip 태그 값 길이 한도.
_TAG_MAX = 200

Send = Callable[[SlowRoute, str, Criteria], None]


def route_key(method: str, route: str) -> str:
    return f"{method} {route}"


def _at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=dt_timezone.utc)


def histograms(start: datetime, end: datetime, routes: Collection[str] | None = None) -> dict[str, list[int]]:
    """[start, end) 의 DB 집계 행을 경로마다 더한다. `routes` 를 주면 그 경로만 읽는다(빈 목록이면 읽지 않는다)."""

    rows = RequestMinute.objects.filter(minute__gte=start, minute__lt=end)
    if routes is not None:
        if not routes:
            return {}
        wanted = Q()
        for key in routes:
            method, route = key.split(" ", 1)
            wanted |= Q(method=method, route=route)
        rows = rows.filter(wanted)
    values = rows.values_list("method", "route", "duration_buckets").order_by()
    return merge((route_key(method, route), list(buckets)) for method, route, buckets in values.iterator())


def _add_unflushed(window: dict[str, list[int]], first: int, current: int) -> None:
    store = get_store()
    size = len(DURATION_BOUNDS) + 1
    for minute in range(first, current + 1, 60):
        for (method, route, _status), metrics in _grouped(store.read(minute_key(REQUEST, minute)), 3).items():
            if metrics.get("n"):
                key = route_key(method, route)
                window[key] = add_counts(window.get(key, []), _buckets(metrics, size))


def find_slow(window: Histograms, window_start: datetime, criteria: Criteria) -> list[SlowRoute]:
    """창에서 느린 경로 — 후보에만 평소(창 바로 앞 `usual_days` 일)를 읽는다."""

    routes = candidates(window, DURATION_BOUNDS, criteria)
    usual = histograms(window_start - timedelta(days=criteria.usual_days), window_start, routes)
    return judge(window, usual, DURATION_BOUNDS, criteria)


# --- GlitchTip -------------------------------------------------------------------------------


def _ms(seconds: float) -> str:
    return f"{seconds:.2f}초" if seconds >= 1 else f"{seconds * 1000:.0f}ms"


def period_label(criteria: Criteria) -> str:
    return "어제 하루" if criteria.window_minutes >= 24 * 60 else f"최근 {criteria.window_minutes}분"


def message(found: SlowRoute, criteria: Criteria) -> str:
    return (
        f"느린 경로 {found.route} — 중앙값 {_ms(found.median_seconds)}, 평소 {_ms(found.usual_median_seconds)}의 "
        f"{found.ratio:.0f}배 ({period_label(criteria)} {found.requests}건)"
    )


def report(found: SlowRoute, check: str, criteria: Criteria) -> None:
    """GlitchTip 에 경고 하나. SDK 가 꺼져 있으면(DSN 없는 dev·CI) 아무 데도 가지 않는다."""

    import sentry_sdk

    text = message(found, criteria)
    with sentry_sdk.new_scope() as scope:
        scope.fingerprint = ["slow-route", found.route]
        scope.set_tag("alert", "slow-route")
        scope.set_tag("slow_route", found.route[:_TAG_MAX])
        scope.set_tag("slow_route_check", check)
        scope.set_context(
            "slow_route",
            {
                "route": found.route,
                "check": check,
                "period": period_label(criteria),
                "requests": found.requests,
                "median_ms": round(found.median_seconds * 1000),
                "usual_median_ms": round(found.usual_median_seconds * 1000),
                "usual_requests": found.usual_requests,
                "usual_days": criteria.usual_days,
                "ratio": round(found.ratio, 1),
                "threshold": threshold(criteria),
            },
        )
        sentry_sdk.capture_message(text, level="warning")
    logger.warning("운영 경보: %s", text)


def threshold(criteria: Criteria) -> str:
    return (
        f"{period_label(criteria)} {criteria.min_requests}건 이상 · 중앙값 ≥ {criteria.min_median_seconds:g}초 · "
        f"평소({criteria.usual_days}일) × {criteria.min_ratio:g} 이상"
    )


# --- 상태 ------------------------------------------------------------------------------------


def _advance(prefix: str, slow: list[SlowRoute], criteria: Criteria, at: datetime, check: str, send: Send) -> list[str]:
    """경로마다 상태를 옮기고 울리기 시작한 경로에 한 번 보낸다. 지금 울리는 경로 목록을 돌려준다."""

    found = {prefix + item.route: item for item in slow}
    states = {
        state.rule: state
        for state in AlertState.objects.filter(
            Q(rule__in=list(found)) | Q(rule__startswith=prefix, status=AlertState.Status.FIRING)
        )
    }
    for rule in found:
        states.setdefault(rule, AlertState(rule=rule))
    firing = []
    for rule, state in sorted(states.items()):
        item = found.get(rule)
        latch, event = advance(Latch(state.status == AlertState.Status.FIRING, state.clear_streak), item is not None, criteria)
        state.last_checked_at = at
        state.streak = state.streak + 1 if item else 0
        state.clear_streak = latch.clear
        state.status = AlertState.Status.FIRING if latch.firing else AlertState.Status.RESOLVED
        if item:
            state.value = f"중앙값 {_ms(item.median_seconds)} ({item.requests}건), 평소 {_ms(item.usual_median_seconds)}"[:100]
            state.threshold = f"평소 × {criteria.min_ratio:g}, ≥ {criteria.min_median_seconds:g}초"
        if event == "firing":
            state.started_at, state.resolved_at = at, None
            send(item, check, criteria)
        elif event == "resolved":
            state.resolved_at = at
        state.save()
        if latch.firing:
            firing.append(rule[len(prefix) :])
    return firing


def check_realtime(*, now: datetime, send: Send | None = None) -> list[str]:
    """1분 검사 한 번 — `check_alerts` 가 잠금·트랜잭션 안에서 부른다. 지금 울리는 경로를 돌려준다."""

    criteria = REALTIME
    current = minute_of(now.timestamp())
    first = current - (criteria.window_minutes - 1) * 60
    window = histograms(_at(first), _at(current + 60))
    try:
        _add_unflushed(window, first, current)
    except Exception as exc:  # noqa: BLE001 - Redis 가 멈춰도 DB 몫으로 검사는 돈다
        logger.warning("느린 경로: Redis 의 아직 옮기지 않은 분을 읽지 못해 DB 만 본다: %s", type(exc).__name__)
    slow = find_slow(window, _at(first), criteria)
    return _advance(REALTIME_PREFIX, slow, criteria, now, "realtime", send or report)


def yesterday(now: datetime) -> tuple[datetime, datetime]:
    """`now` 의 서울 날짜 앞 하루 [시작, 끝)."""

    local = now.astimezone(ZoneInfo(settings.TIME_ZONE))
    end = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = (end - timedelta(days=1)).replace(hour=0)
    return start, end


def check_daily(*, now: datetime, send: Send | None = None) -> list[str]:
    """하루 판정 한 번 — 어제(서울) 하루를 본다. 지금 울리는 경로를 돌려준다."""

    criteria = DAILY
    start, end = yesterday(now)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_DAILY_LOCK_ID])
        slow = find_slow(histograms(start, end), start, criteria)
        return _advance(DAILY_PREFIX, slow, criteria, now, "daily", send or report)
