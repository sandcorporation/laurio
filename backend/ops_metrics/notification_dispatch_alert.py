"""발송 실패 운영 경보(#1123) — 알림이 나가지 않아도 사람이 사이트를 보기 전에는 알 길이 없었다(2026-11-21,
채점 완료 알림 16건). `NotificationDispatch`(발송 기록)를 스캔 하나(`notification-dispatch-alert`)가 보고,
두 규칙 중 하나라도 걸리면 운영 경보 길(`OPS_ALERT_DISCORD_WEBHOOK_URL`·`OPS_ALERT_NOTICE_WEBHOOK_URL` → `ops_metrics.alerts`)로 올린다.

- `notification-dispatch-failures` — 최근 창(기본 60분) 안의 실패 이력이 문턱(기본 5건) 이상.
- `notification-zero-reach` — 같은 창 안에 시도한 알림이 한 유형에서 문턱(기본 3건) 이상인데 **하나도 닿지 않았다**
  (성공 이력 0). 채널은 전부 외부(알림톡·SMS·LMS)다.

상태·되풀이 방지·해소 알림·웹훅이 비었을 때의 조용함은 `ops_metrics.alerts` 의 `AlertState` 를 그대로 쓴다 —
울리는 동안은 다시 보내지 않고, 풀리면 「해소」를 한 번 보낸다. 글에는 건수·채널·알림 유형만 있고 수신자·주소는
없다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q

from core.scans import ScanSpec
from notifications.models import Notification, NotificationDispatch, NotificationType

from . import alerts
from .models import AlertState

FAILURES_RULE = "notification-dispatch-failures"
ZERO_REACH_RULE = "notification-zero-reach"
_RULES = (FAILURES_RULE, ZERO_REACH_RULE)
_VALUE_MAX = 100  # AlertState.value 의 길이


def _window() -> timedelta:
    return timedelta(minutes=int(getattr(settings, "NOTIFICATION_ALERT_WINDOW_MINUTES", 60)))


def _failure_threshold() -> int:
    return int(getattr(settings, "NOTIFICATION_ALERT_FAILURE_THRESHOLD", 5))


def _zero_reach_min() -> int:
    return int(getattr(settings, "NOTIFICATION_ALERT_ZERO_REACH_MIN", 3))


def _clip(text: str) -> str:
    return text if len(text) <= _VALUE_MAX else text[: _VALUE_MAX - 1] + "…"


def read_failures(since) -> alerts.Reading:
    by_channel = dict(
        NotificationDispatch.objects.filter(
            status=NotificationDispatch.Status.FAILED, attempted_at__gte=since
        )
        .values_list("channel")
        .annotate(n=Count("id"))
    )
    total = sum(by_channel.values())
    labels = dict(NotificationDispatch.Channel.choices)
    detail = "·".join(f"{labels.get(ch, ch)} {n}" for ch, n in sorted(by_channel.items()))
    value = f"{total}건 ({detail})" if detail else "0건"
    return alerts.Reading(total >= _failure_threshold(), _clip(value), f"≥ {_failure_threshold()}건 / {_minutes()}분")


def read_zero_reach(since) -> alerts.Reading:
    rows = (
        Notification.objects.filter(created_at__gte=since, dispatches__isnull=False)
        .values_list("notification_type")
        .annotate(
            total=Count("id", distinct=True),
            reached=Count("id", filter=Q(dispatches__status=NotificationDispatch.Status.SENT), distinct=True),
        )
    )
    minimum = _zero_reach_min()
    labels = dict(NotificationType.choices)
    hits = sorted((labels.get(kind, kind), total) for kind, total, reached in rows if reached == 0 and total >= minimum)
    value = ", ".join(f"{label} {total}건" for label, total in hits) or "없음"
    return alerts.Reading(bool(hits), _clip(value), f"유형별 {minimum}건 이상 · 닿은 수신자 0 / {_minutes()}분")


def _minutes() -> int:
    return int(_window().total_seconds() // 60)


def check(*, now) -> dict[str, str]:
    """규칙 둘을 한 번 검사하고 상태가 **바뀐** 규칙 → 새 상태를 돌려준다(그대로면 빈 dict)."""

    since = now - _window()
    readings = {FAILURES_RULE: read_failures(since), ZERO_REACH_RULE: read_zero_reach(since)}
    changed: dict[str, str] = {}
    with transaction.atomic():
        AlertState.objects.bulk_create([AlertState(rule=name) for name in _RULES], ignore_conflicts=True)
        states = {s.rule: s for s in AlertState.objects.select_for_update().filter(rule__in=_RULES)}
        for name in _RULES:
            state = states[name]
            before = state.status
            alerts.advance(state, alerts.Rule(name, 1, lambda _inputs: readings[name]), readings[name], now)
            state.save()
            if state.status != before:
                changed[name] = str(state.status)
    return changed


def _candidates(as_of: Any, ctx: dict) -> list[int]:
    return [1]


def _handle_row(_row: int, as_of: Any, ctx: dict) -> dict | None:
    # 아무 일도 없으면 행을 내지 않는다 — tick 의 count 가 이 스캔 때문에 늘지 않는다.
    return check(now=as_of) or None


NOTIFICATION_DISPATCH_ALERT_SCAN = ScanSpec(
    name="notification-dispatch-alert",
    candidates=_candidates,
    handle_row=_handle_row,
    batch_size=1,
    interval_seconds=300.0,
)
