"""느린 경로 경고(#971) — 경로별 중앙값을 평소와 견줘 GlitchTip 경고로 올린다.

판정(`ops_metrics.slow_routes`)은 순수 함수라 칸별 수를 넘겨 직접 본다. 1분 검사는 beat 가 부르는
`ops_metrics.alerts.check_alerts` 를 시각을 넘겨 부르고, 하루 판정은 `slow_route_check.check_daily` 를 부른다.
GlitchTip 은 `slow_route_check.report` 를 가짜로 바꾸거나 `sentry_sdk.capture_message` 를 가로챈다.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from core.metrics import DURATION_BOUNDS
from django.core.management import call_command
from ops_metrics import alerts, recorder, slow_route_check
from ops_metrics.models import AlertState, RequestMinute
from ops_metrics.recorder import REQUEST
from ops_metrics.request_buffer import request_fields
from ops_metrics.slow_routes import (
    DAILY,
    REALTIME,
    Criteria,
    Latch,
    SlowRoute,
    advance,
    candidates,
    judge,
)
from ops_metrics.store import memory_store

#: 2026-11-19 08:00 UTC(서울 17:00).
T0 = int(datetime(2026, 11, 19, 8, 0, tzinfo=dt_timezone.utc).timestamp())
MINE = "GET api/contests/mine"
SIZE = len(DURATION_BOUNDS) + 1


def _counts(seconds: float, n: int) -> list[int]:
    counts = [0] * SIZE
    index = next((i for i, bound in enumerate(DURATION_BOUNDS) if seconds <= bound), len(DURATION_BOUNDS))
    counts[index] = n
    return counts


@pytest.fixture(autouse=True)
def store():
    memory_store().clear()
    recorder._failing = False
    yield memory_store()
    memory_store().clear()


@pytest.fixture
def reported(monkeypatch):
    """GlitchTip 으로 간 경고들 — (경로, 검사 종류, 지금 중앙값)."""

    sent: list[tuple[str, str, float]] = []
    monkeypatch.setattr(slow_route_check, "report", lambda found, check, criteria: sent.append((found.route, check, found.median_seconds)))
    return sent


def _row(at: int, seconds: float, n: int = 1, *, route: str = "api/contests/mine", status: int = 200) -> None:
    """DB 집계 행(이미 옮겨진 분)."""

    RequestMinute.objects.create(
        minute=datetime.fromtimestamp(at - at % 60, tz=dt_timezone.utc),
        method="GET",
        route=route,
        status=status,
        requests=n,
        duration_buckets=_counts(seconds, n),
        duration_sum_ms=int(seconds * 1000 * n),
    )


def _live(at: int, seconds: float, n: int = 1, *, route: str = "api/contests/mine") -> None:
    """아직 Redis 에만 있는 분(flush 전)."""

    for _ in range(n):
        recorder._add(REQUEST, request_fields(method="GET", route=route, status=200, seconds=seconds), {}, at)


def _usual(days: int = 3, per_day: int = 5, seconds: float = 0.04) -> None:
    for day in range(1, days + 1):
        _row(T0 - day * 86400, seconds, per_day)


def _check(at: int) -> None:
    assert alerts.check_alerts(now=datetime.fromtimestamp(at, tz=dt_timezone.utc)) is not None


# --- 판정(순수 함수) ---------------------------------------------------------------------------


def test_a_route_needs_enough_requests_a_slow_median_and_a_jump_from_usual():
    usual = {MINE: _counts(0.04, 40)}
    criteria = REALTIME
    assert judge({MINE: _counts(2.0, 2)}, usual, DURATION_BOUNDS, criteria) == []  # 2건 < 3건
    assert judge({MINE: _counts(0.9, 5)}, usual, DURATION_BOUNDS, criteria) == []  # 중앙값 < 1초
    [found] = judge({MINE: _counts(2.0, 3)}, usual, DURATION_BOUNDS, criteria)
    assert found.route == MINE and found.requests == 3 and found.usual_requests == 40
    assert found.median_seconds >= 1.0 and found.ratio >= 5


def test_an_always_slow_route_and_a_route_without_history_do_not_fire():
    slow_usual = {MINE: _counts(1.5, 40)}  # 원래 느린 경로(LLM·업로드)
    assert judge({MINE: _counts(2.0, 5)}, slow_usual, DURATION_BOUNDS, REALTIME) == []
    assert judge({MINE: _counts(2.0, 5)}, {}, DURATION_BOUNDS, REALTIME) == []


def test_the_daily_rule_takes_a_single_request():
    assert candidates({MINE: _counts(3.0, 1)}, DURATION_BOUNDS, DAILY) == [MINE]
    assert candidates({MINE: _counts(3.0, 1)}, DURATION_BOUNDS, REALTIME) == []


def test_a_firing_route_resolves_only_after_enough_clear_checks_in_a_row():
    criteria = Criteria(window_minutes=30, min_requests=3, min_median_seconds=1, min_ratio=5, clear_checks=3)
    latch, event = advance(Latch(), True, criteria)
    assert event == "firing"
    latch, event = advance(latch, True, criteria)
    assert event is None  # 울리는 중에는 다시 보내지 않는다
    latch, _ = advance(latch, False, criteria)
    latch, _ = advance(latch, False, criteria)
    latch, event = advance(latch, True, criteria)  # 느린 검사가 끼면 처음부터
    assert event is None and latch == Latch(True, 0)
    for _ in range(2):
        latch, event = advance(latch, False, criteria)
        assert event is None
    latch, event = advance(latch, False, criteria)
    assert event == "resolved" and latch == Latch()


# --- 1분 검사 ---------------------------------------------------------------------------------


def test_realtime_reports_once_while_firing_and_never_posts_to_discord(db, reported, settings, monkeypatch):
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = "https://discord.invalid/api/webhooks/test"
    posted: list[str] = []
    monkeypatch.setattr(alerts, "post_webhook", lambda url, content: posted.append(content))
    _usual()
    _row(T0 - 120, 2.2, 2)
    _live(T0, 2.2, 1)  # 지금 분은 아직 Redis 에만 있다

    _check(T0)
    assert reported == [(MINE, "realtime", pytest.approx(reported[0][2]))]
    assert reported[0][2] >= 1.0
    state = AlertState.objects.get(rule=slow_route_check.REALTIME_PREFIX + MINE)
    assert state.status == AlertState.Status.FIRING and state.started_at is not None

    _check(T0 + 60)
    assert len(reported) == 1
    assert not any("slow-route" in line for line in posted)
    assert {s.rule for s in alerts.firing()}.isdisjoint({state.rule})  # 운영자 「경보」 목록은 디스코드 규칙만


def test_realtime_resolves_after_an_hour_clear_and_reports_again_on_return(db, reported):
    _usual()
    _row(T0, 2.2, 3)
    _check(T0)
    assert len(reported) == 1
    # 창(30분)을 벗어나 59번 괜찮아도 아직 울린다 — 60번째에 해소.
    for minute in range(31, 31 + REALTIME.clear_checks - 1):
        slow_route_check.check_realtime(now=datetime.fromtimestamp(T0 + minute * 60, tz=dt_timezone.utc))
    rule = slow_route_check.REALTIME_PREFIX + MINE
    assert AlertState.objects.get(rule=rule).status == AlertState.Status.FIRING
    _check(T0 + (31 + REALTIME.clear_checks - 1) * 60)
    assert AlertState.objects.get(rule=rule).status == AlertState.Status.RESOLVED

    again = T0 + 3 * 3600
    _row(again, 2.2, 3)
    _check(again)
    assert [route for route, _, _ in reported] == [MINE, MINE]


def test_realtime_ignores_a_fast_route_and_a_route_that_was_already_slow(db, reported):
    _usual()
    for day in range(1, 4):  # 같은 날들에 더 많은 느린 기록 — 평소 중앙값이 올라간다
        _row(T0 - day * 86400, 1.5, 10, status=201)
    _row(T0, 2.2, 3)
    _row(T0, 0.03, 50, route="api/contests")
    _check(T0)
    assert reported == []


# --- 하루 판정 --------------------------------------------------------------------------------


def test_daily_catches_a_single_slow_request_yesterday_and_resolves_the_next_day(db, reported):
    # 서울 11-19 00:10 에 11-18 하루를 본다.
    now = datetime(2026, 11, 18, 15, 10, tzinfo=dt_timezone.utc)
    yesterday_noon = int(datetime(2026, 11, 18, 3, 0, tzinfo=dt_timezone.utc).timestamp())
    _row(yesterday_noon, 2.8, 1)
    for day in range(1, 4):
        _row(yesterday_noon - day * 86400, 0.04, 2)
    _row(int(now.timestamp()) - 60, 9.0, 5)  # 오늘(서울) 몫은 보지 않는다

    assert slow_route_check.check_daily(now=now) == [MINE]
    assert reported == [(MINE, "daily", pytest.approx(reported[0][2]))]
    assert slow_route_check.check_daily(now=now) == [MINE]
    assert len(reported) == 1  # 다시 돌아도 한 번

    assert slow_route_check.check_daily(now=now + timedelta(days=2)) == []
    assert AlertState.objects.get(rule=slow_route_check.DAILY_PREFIX + MINE).status == AlertState.Status.RESOLVED


def test_daily_job_is_on_the_beat_schedule():
    from config.celery import SCHEDULED_JOBS

    job = SCHEDULED_JOBS["ops-metrics:slow-routes-daily"]
    assert job["task"] == "ops_metrics.check_slow_routes_daily"
    assert job["schedule"].hour == {0} and job["schedule"].minute == {10}


# --- GlitchTip --------------------------------------------------------------------------------


def _capture(monkeypatch) -> list[dict]:
    import sentry_sdk

    captured: list[dict] = []

    def capture_message(text, level=None, **_kw):
        scope = sentry_sdk.get_current_scope()
        captured.append(
            {"text": text, "level": level, "fingerprint": list(scope._fingerprint), "tags": dict(scope._tags), "contexts": dict(scope._contexts)}
        )

    monkeypatch.setattr(sentry_sdk, "capture_message", capture_message)
    return captured


def test_report_is_a_warning_fingerprinted_by_route_with_numbers_only(monkeypatch):
    captured = _capture(monkeypatch)
    found = SlowRoute("GET api/classroom/classes/<class_id>/problems", 6, 2.17, 0.04, 40)
    slow_route_check.report(found, "realtime", REALTIME)

    [event] = captured
    assert event["level"] == "warning"
    assert event["fingerprint"] == ["slow-route", "GET api/classroom/classes/<class_id>/problems"]
    assert event["tags"]["alert"] == "slow-route" and event["tags"]["slow_route_check"] == "realtime"
    assert event["text"] == (
        "느린 경로 GET api/classroom/classes/<class_id>/problems — 중앙값 2.17초, 평소 40ms의 54배 (최근 30분 6건)"
    )
    context = event["contexts"]["slow_route"]
    assert context["median_ms"] == 2170 and context["usual_median_ms"] == 40 and context["requests"] == 6


def test_sample_command_sends_a_tagged_warning_without_touching_the_db(db, monkeypatch, settings):
    import sentry_sdk

    settings.SENTRY_ENABLED = True
    monkeypatch.setattr(sentry_sdk, "flush", lambda timeout=None: None)
    captured = _capture(monkeypatch)
    call_command("slow_routes", "--send-sample", stdout=io.StringIO())
    [event] = captured
    assert event["fingerprint"] == ["slow-route", "sample"] and event["tags"]["slow_route_sample"] == "1"
    assert not AlertState.objects.exists()


def test_print_command_only_reads(db, reported):
    now = int(datetime.now(dt_timezone.utc).timestamp())
    for day in range(1, 4):
        _row(now - day * 86400, 0.04, 5)
    _row(now, 2.2, 3)
    out = io.StringIO()
    call_command("slow_routes", stdout=out)
    assert MINE in out.getvalue()
    assert reported == [] and not AlertState.objects.exists()
