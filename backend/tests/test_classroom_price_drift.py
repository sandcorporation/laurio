"""모델 단가 표 대조(#798) — 녹화 응답(LiteLLM 파일 발췌)으로, 바깥에 나가지 않는다.

받는 함수와 알리는 함수를 주입한다. 갈래: 같음 · 1% 초과 · 표에 없는 쓰인 모델 · 받기 실패 · 형식 바뀜,
그리고 알림이 GlitchTip 자동 진단이 거르는 예외 이름·지문을 달고 나가는지.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from celery.schedules import crontab
from django.test import override_settings

from classroom import price_drift, scoring_cost
from config.celery import app as celery_app
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    respond_with_verdicts,
    run_scan,
    submit_source,
    user_id,
)

# LiteLLM 파일의 발췌 — 우리 표와 같은 값(USD/토큰). gpt-5.5 는 27.2만 초과 구간까지.
SAME = {
    "sample_spec": {"note": "형식 설명 항목"},
    "gpt-4o-mini": {"input_cost_per_token": 1.5e-7, "output_cost_per_token": 6e-7, "cache_read_input_token_cost": 7.5e-8},
    "gpt-5.5": {
        "input_cost_per_token": 5e-6,
        "output_cost_per_token": 3e-5,
        "input_cost_per_token_above_272k_tokens": 1e-5,
        "output_cost_per_token_above_272k_tokens": 4.5e-5,
    },
    "claude-haiku-5-5": {"input_cost_per_token": 1e-7, "output_cost_per_token": 5e-7},
}


def _recorded(**overrides):
    data = copy.deepcopy(SAME)
    data.update(overrides)
    return data


class Alerts:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def __call__(self, kind, body):
        self.sent.append((kind, body))


def _run(data, alerts):
    return price_drift.run_price_drift_check(lambda: data, alert=alerts)


def test_same_prices_send_nothing(db):
    alerts = Alerts()
    result = _run(_recorded(), alerts)
    assert result == {"kind": None}
    assert alerts.sent == []


def test_a_difference_within_one_percent_is_not_drift(db):
    alerts = Alerts()
    data = _recorded()
    data["gpt-4o-mini"]["input_cost_per_token"] = 1.5e-7 * 1.009
    _run(data, alerts)
    assert alerts.sent == []


def test_more_than_one_percent_names_model_field_and_both_values(db):
    alerts = Alerts()
    data = _recorded()
    data["gpt-4o-mini"]["output_cost_per_token"] = 8e-7
    result = _run(data, alerts)
    assert result["kind"] == "drift"
    (kind, body), = alerts.sent
    assert kind == "drift"
    assert "gpt-4o-mini / 출력 USD/100만 토큰 / 0.6 / 0.8" in body
    assert "자동으로 고치지 않는다" in body
    assert scoring_cost.PRICES["gpt-4o-mini"].output_usd_per_million == 0.6  # 표는 그대로


def test_the_long_context_tier_is_compared_too(db):
    alerts = Alerts()
    data = _recorded()
    data["gpt-5.5"]["input_cost_per_token_above_272k_tokens"] = 2e-5
    _run(data, alerts)
    (_, body), = alerts.sent
    assert "gpt-5.5 / 구간(272k 초과) 입력 / 10 / 20" in body


def test_a_model_the_file_does_not_know_is_listed_but_does_not_alert_alone(db):
    alerts = Alerts()
    result = _run(_recorded(), alerts)
    assert result == {"kind": None}
    assert "gpt-5.1" in price_drift.compare(_recorded(), []).not_compared


def test_a_model_used_this_week_but_missing_from_the_table_alerts(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_source(
        client, participant["access"], class_id, problem.id,
        participant_user_id=user_id("participant-1"), files={"main.py": "a = 1\n"},
    )
    with force_real_scoring_adapter():
        respond_with_verdicts(
            monkeypatch,
            [{"requirement_id": problem.item_id, "is_met": True, "reasoning": "x"}],
            model="gpt-9-turbo-2026-11-01",
        )
        run_scan(client)

    alerts = Alerts()
    result = _run(_recorded(), alerts)
    assert result["kind"] == "drift"
    assert result["unpriced_used"] == ["gpt-9-turbo-2026-11-01"]
    assert "gpt-9-turbo-2026-11-01" in alerts.sent[0][1]


def test_a_dated_variant_of_a_priced_model_is_not_unpriced(db):
    assert price_drift.compare(_recorded(), ["gpt-4o-mini-2024-07-18"]).unpriced_used == []


def test_fetch_failure_alerts_instead_of_passing_silently(db):
    alerts = Alerts()

    def _fail():
        raise price_drift.FetchFailed("HTTP 503")

    result = price_drift.run_price_drift_check(_fail, alert=alerts)
    assert result == {"kind": "fetch-failed"}
    assert alerts.sent[0][0] == "fetch-failed" and "HTTP 503" in alerts.sent[0][1]


@pytest.mark.parametrize(
    "data",
    [["not", "an", "object"], {}, {"gpt-4o-mini": {"price": 1}, "gpt-5.5": {"price": 2}}],
)
def test_a_changed_format_alerts(db, data):
    alerts = Alerts()
    result = _run(data, alerts)
    assert result == {"kind": "format-changed"}
    assert alerts.sent[0][0] == "format-changed"


def test_real_fetcher_maps_transport_problems_without_going_out(monkeypatch):
    class _Resp:
        def __init__(self, status, chunks):
            self.status_code, self._chunks = status, chunks

        def iter_content(self, chunk_size):
            return iter(self._chunks)

        def close(self):
            pass

    monkeypatch.setattr(price_drift.requests, "get", lambda *a, **k: _Resp(404, []))
    with pytest.raises(price_drift.FetchFailed):
        price_drift.fetch_litellm_prices()
    monkeypatch.setattr(price_drift.requests, "get", lambda *a, **k: _Resp(200, [b"<html>"]))
    with pytest.raises(price_drift.FormatChanged):
        price_drift.fetch_litellm_prices()
    monkeypatch.setattr(price_drift, "MAX_BYTES", 4)
    monkeypatch.setattr(price_drift.requests, "get", lambda *a, **k: _Resp(200, [b"{}" * 8]))
    with pytest.raises(price_drift.FetchFailed):
        price_drift.fetch_litellm_prices()


def test_without_an_error_collector_the_job_does_not_go_out(db, monkeypatch):
    monkeypatch.setattr(
        price_drift, "fetch_litellm_prices", lambda: pytest.fail("바깥에 나가면 안 된다")
    )
    with override_settings(SENTRY_ENABLED=False):
        assert price_drift.run_price_drift_check() == {"kind": None, "skipped": True}


def test_the_alert_is_a_warning_with_a_fingerprint_per_kind_and_a_name_triage_skips(monkeypatch):
    import sentry_sdk

    captured = []

    def _capture(exc):
        scope = sentry_sdk.get_current_scope()
        captured.append((type(exc).__name__, scope._level, list(scope._fingerprint), dict(scope._tags)))

    monkeypatch.setattr(sentry_sdk, "capture_exception", _capture)
    price_drift.send_alert("drift", "본문")
    name, level, fingerprint, tags = captured[0]
    assert (name, level, fingerprint) == ("PriceDriftAlert", "warning", ["price-drift", "drift"])
    assert tags["alert"] == "price-drift"

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import glitchtip_pick
    finally:
        sys.path.pop(0)
    assert name in glitchtip_pick.DELIBERATE_EXCEPTION_TYPES


def test_beat_runs_it_daily_at_0410():
    entry = celery_app.conf.beat_schedule["classroom:price-drift"]
    assert entry["task"] == "classroom.check_price_drift"
    assert isinstance(entry["schedule"], crontab)
    assert (entry["schedule"].hour, entry["schedule"].minute) == ({4}, {10})
