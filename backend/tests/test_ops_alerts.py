"""운영 경보(#830) — 기록(Redis 분 해시) → flush → 1분마다 검사 → 디스코드 · 운영자 API.

기록은 `recorder`(채점 경로가 부르는 그 함수, 시각을 넘긴다)로 만들고, 검사는 beat 가 부르는
`ops_metrics.alerts.check_alerts` 를 시각을 넘겨 부른다. 디스코드는 `post_webhook` 을 가짜로 바꾼다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest

from ops_metrics import alerts, recorder
from ops_metrics.flush import flush_closed_minutes
from ops_metrics.models import AlertState
from ops_metrics.store import memory_store
from tests.test_ops_metrics import OPS_URL, _operator_client

#: 2026-10-30 03:00 UTC.
T0 = int(datetime(2026, 10, 30, 3, 0, tzinfo=dt_timezone.utc).timestamp())
HOOK = "https://discord.invalid/api/webhooks/test"


@pytest.fixture(autouse=True)
def store():
    memory_store().clear()
    recorder._failing = False
    yield memory_store()
    memory_store().clear()


@pytest.fixture
def sent(monkeypatch, settings):
    """디스코드로 보낸 문장들. 웹훅이 설정돼 있다."""

    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = HOOK
    settings.OPERATOR_WEB_ORIGIN = "https://console.example"
    messages: list[str] = []
    monkeypatch.setattr(alerts, "post_webhook", lambda url, content: messages.append(content))
    return messages


def _calls(result: str, n: int, at: int) -> None:
    for _ in range(n):
        recorder.record_llm_call(product="classroom", model="gpt-4o-mini", result=result, seconds=1, at=at)


def _waits(seconds: float, n: int, at: int) -> None:
    for _ in range(n):
        asyncio.run(recorder.record_queue_wait_async(product="classroom", seconds=seconds, at=at))


def _check(at: int, *, grader_alive: bool = True) -> dict[str, str]:
    if grader_alive:
        asyncio.run(recorder.beat_async("grader", at=at))
    result = alerts.check_alerts(now=datetime.fromtimestamp(at, tz=dt_timezone.utc))
    assert result is not None
    return result


def _firing(at: int, **kw) -> set[str]:
    return {rule for rule, status in _check(at, **kw).items() if status == "firing"}


# --- 규칙마다 경계 -----------------------------------------------------------------------------


def test_quota_exhausted_fires_on_the_first_rejection_in_ten_minutes(db, sent):
    assert _firing(T0 + 30) == set()
    _calls("quota_exhausted", 1, T0 + 40)
    assert _firing(T0 + 50) == {"LLMQuotaExhausted"}
    # 10분 창 = 지금 분과 앞의 9분 — 10분째에는 빠진다.
    assert _firing(T0 + 9 * 60 + 5) == {"LLMQuotaExhausted"}
    assert _firing(T0 + 10 * 60 + 5) == set()


def test_rate_limited_needs_five_in_ten_minutes(db, sent):
    _calls("rate_limited", 4, T0)
    assert _firing(T0 + 10) == set()
    _calls("rate_limited", 1, T0 + 20)
    assert _firing(T0 + 30) == {"LLMRateLimited"}


def test_auth_rejected_looks_back_thirty_minutes(db, sent):
    _calls("auth", 1, T0)
    assert _firing(T0 + 29 * 60) == {"LLMAuthRejected"}
    assert _firing(T0 + 30 * 60) == set()


def test_timeout_ratio_above_a_fifth_fires_after_five_consecutive_checks(db, sent):
    _calls("ok", 4, T0)
    _calls("timeout", 1, T0)  # 정확히 20% — 넘지 않는다
    for minute in range(6):
        assert _firing(T0 + minute * 60 + 30) == set()

    _calls("timeout", 1, T0 + 6 * 60)  # 2/6 = 33%
    for minute in range(6, 10):
        assert _firing(T0 + minute * 60 + 30) == set(), minute
    assert _firing(T0 + 10 * 60 + 30) == {"LLMTimeoutRatioHigh"}
    assert sent == ["🔥 [Codemit] LLMTimeoutRatioHigh 발생 — 33% (2/6) · 기준 > 20% / 15분, 5분 지속 · https://console.example/ops"]


def test_a_false_check_resets_the_streak(db, sent):
    _calls("timeout", 1, T0)
    for minute in range(4):
        assert _firing(T0 + minute * 60 + 30) == set()
    _calls("ok", 10, T0 + 4 * 60)  # 1/11 — 한 번 거짓
    assert _firing(T0 + 4 * 60 + 30) == set()
    _calls("timeout", 10, T0 + 5 * 60)  # 11/21 — 다시 처음부터 다섯 번
    for minute in range(5, 9):
        assert _firing(T0 + minute * 60 + 30) == set()
    assert _firing(T0 + 9 * 60 + 30) == {"LLMTimeoutRatioHigh"}


def test_queue_wait_p95_over_five_minutes_fires_after_ten_checks(db, sent):
    _waits(250, 20, T0)  # (120,300] 칸 — p95 291초
    for minute in range(10):
        assert _firing(T0 + minute * 60 + 30) == set()

    _waits(400, 20, T0 + 10 * 60)  # (300,600] 칸 — p95 585초
    for minute in range(10, 19):
        assert _firing(T0 + minute * 60 + 30) == set(), minute
    assert _firing(T0 + 19 * 60 + 30) == {"ClassroomScoringQueueSlow"}
    assert AlertState.objects.get(rule="ClassroomScoringQueueSlow").value == "p95 585초"


def test_grader_down_after_three_minutes_without_a_heartbeat(db, sent):
    assert _firing(T0, grader_alive=False) == {"GraderDown"}  # 신호가 한 번도 없다
    asyncio.run(recorder.beat_async("grader", at=T0))
    assert _firing(T0 + 180, grader_alive=False) == set()
    assert _firing(T0 + 181, grader_alive=False) == {"GraderDown"}
    assert AlertState.objects.get(rule="GraderDown").value == "마지막 신호 181초 전"


# --- 입력: 옮기지 않은 분 + 옮긴 분 + 늦게 닿은 기록 -----------------------------------------------------


def test_flushed_rows_unflushed_minutes_and_late_writes_all_count(db, sent):
    _calls("rate_limited", 2, T0)
    flush_closed_minutes(now=T0 + 65)  # T0 분이 DB 로
    _calls("rate_limited", 1, T0 + 59)  # 그 분에 늦게 닿았다 — 아직 Redis
    _calls("rate_limited", 1, T0 + 70)  # 닫혔지만 옮기지 않은 분
    assert _firing(T0 + 125) == set()  # 4회
    _calls("rate_limited", 1, T0 + 126)  # 지금 분
    assert _firing(T0 + 130) == {"LLMRateLimited"}


def test_a_redis_failure_still_checks_the_flushed_rows(db, sent, store, caplog):
    _calls("quota_exhausted", 1, T0)
    flush_closed_minutes(now=T0 + 65)
    asyncio.run(recorder.beat_async("grader", at=T0 + 70))
    store.fail = True
    result = alerts.check_alerts(now=datetime.fromtimestamp(T0 + 70, tz=dt_timezone.utc))
    assert result["LLMQuotaExhausted"] == "firing"
    assert "DB 만 본다" in caplog.text


# --- 보내기: 억제 · 해소 한 번 · 꺼짐 · 재시도 ---------------------------------------------------------------


def test_a_firing_rule_is_sent_once_and_resolved_once(db, sent):
    _calls("auth", 1, T0)
    _check(T0 + 10)
    _check(T0 + 70)  # 아직 울린다 — 다시 보내지 않는다
    assert sent == ["🔥 [Codemit] LLMAuthRejected 발생 — 1회 · 기준 > 0회 / 30분 · https://console.example/ops"]

    _check(T0 + 30 * 60 + 10)  # 창을 벗어났다
    _check(T0 + 31 * 60 + 10)
    assert sent[1:] == ["✅ [Codemit] LLMAuthRejected 해소 — 30분 지속"]
    state = AlertState.objects.get(rule="LLMAuthRejected")
    assert (state.status, state.pending_notice) == ("resolved", "")


def test_without_a_webhook_nothing_is_sent_but_the_state_is_kept(db, sent, settings, client):
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = ""
    _calls("auth", 1, T0)
    _check(T0 + 10)
    _check(T0 + 30 * 60 + 10)
    _calls("auth", 1, T0 + 30 * 60 + 20)
    _check(T0 + 30 * 60 + 30)
    assert sent == []
    assert AlertState.objects.get(rule="LLMAuthRejected").status == "firing"


def test_a_failed_send_is_retried_on_the_next_check(db, sent, monkeypatch, caplog):
    attempts: list[str] = []

    def flaky(url, content):
        attempts.append(content)
        if len(attempts) == 1:
            raise ConnectionError("discord unreachable")
        sent.append(content)

    monkeypatch.setattr(alerts, "post_webhook", flaky)
    _calls("auth", 1, T0)
    _check(T0 + 10)
    assert sent == [] and "다음 검사에서 다시 보낸다" in caplog.text
    assert HOOK not in caplog.text
    _check(T0 + 70)
    _check(T0 + 130)
    assert sent == [attempts[0]] and len(attempts) == 2


def test_a_rule_resolved_before_its_alert_got_through_sends_nothing(db, sent, monkeypatch):
    def down(url, content):
        raise ConnectionError("discord unreachable")

    monkeypatch.setattr(alerts, "post_webhook", down)
    _calls("quota_exhausted", 1, T0)
    _check(T0 + 10)
    monkeypatch.setattr(alerts, "post_webhook", lambda url, content: sent.append(content))
    _check(T0 + 10 * 60 + 10)
    assert sent == []


def test_the_console_link_comes_from_settings(db, sent, settings):
    settings.OPERATOR_WEB_ORIGIN = ""
    _calls("auth", 1, T0)
    _check(T0 + 10)
    assert sent == ["🔥 [Codemit] LLMAuthRejected 발생 — 1회 · 기준 > 0회 / 30분"]


# --- 운영자 API · 일정 -------------------------------------------------------------------------------


def test_the_api_lists_firing_alerts_next_to_the_metrics(db):
    operator = _operator_client()
    assert operator.get(OPS_URL).json()["alerts"] == []

    _calls("auth", 1, T0)
    _check(T0 + 10)
    body = operator.get(OPS_URL).json()
    assert body["alerts"] == [
        {"rule": "LLMAuthRejected", "since": "2026-10-30T03:00:10Z", "value": "1회", "threshold": "> 0회 / 30분"}
    ]


def test_the_beat_schedule_checks_alerts_every_minute():
    from config.celery import SCHEDULED_JOBS

    job = SCHEDULED_JOBS["ops-metrics:alerts"]
    assert job["task"] == "ops_metrics.check_alerts"
    assert job["schedule"].minute == set(range(60))
