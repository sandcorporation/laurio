"""에이전트 계정 거절 경보(#1058) — 공모전 채점·완성도·강의실 세 길이 같은 자리에서 GlitchTip 으로 보낸다.

같은 원인(벤더 + 종류)은 한 시간에 한 번, 지문은 같다. 이벤트에는 키도 응답 원문도 없다."""

from __future__ import annotations

import json

import pytest
import sentry_sdk
from django.core.cache import caches

from core import agent_refusal_alert, agent_scoring
from tests.integration.test_agent_scoring import (
    USAGE_LIMIT_MESSAGE,
    _FakeRunner,
    _two_closed_submissions,
    _use,
    _vendor_error_stream,
    agent_method,  # noqa: F401 - 픽스처
    category,  # noqa: F401 - 픽스처
    claude_vendor,  # noqa: F401 - 픽스처
    landing_type,  # noqa: F401 - 픽스처
)
from tests.integration.test_agent_scoring import _run_pending
from payouts.tests.test_contest_quality import _run_quality, closed  # noqa: F401 - 픽스처

SECRET_MARKER = "RESPONSE-BODY-MUST-NOT-LEAK"


@pytest.fixture
def sent(monkeypatch):
    """GlitchTip 으로 나가는 이벤트 — (문구, 지문, 태그, 수준)."""

    caches["rate_limits"].clear()
    events: list[tuple[str, list[str], dict, str | None]] = []

    def _capture(exc, *args, **kwargs):
        scope = sentry_sdk.get_current_scope()
        events.append((str(exc), list(scope._fingerprint), dict(scope._tags), scope._level))

    monkeypatch.setattr(sentry_sdk, "capture_exception", _capture)
    return events


@pytest.mark.django_db
def test_contest_scoring_refusals_send_one_event_per_hour_with_a_fixed_fingerprint(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor, sent  # noqa: F811
):
    _two_closed_submissions(client, category, landing_type)
    _use(monkeypatch, _FakeRunner(_vendor_error_stream(400, f"{USAGE_LIMIT_MESSAGE} {SECRET_MARKER}"), exit_code=1))

    _run_pending(client)  # 첫 스캔
    _run_pending(client)  # 다음 스캔 — 같은 원인

    assert len(sent) == 1
    message, fingerprint, tags, level = sent[0]
    assert fingerprint == ["agent-account-refusal", "anthropic", "usage_limit"]
    assert tags["vendor"] == "anthropic" and tags["refusal_kind"] == "usage_limit"
    assert level == "warning"
    assert SECRET_MARKER not in json.dumps([message, tags]) and "usage limits" not in message

    # 한 시간이 지나면(키가 사라지면) 같은 원인도 다시 한 번 간다.
    caches["rate_limits"].delete("agent-account-refusal:alert:anthropic:usage_limit")
    _run_pending(client)
    assert len(sent) == 2 and sent[1][1] == sent[0][1]


@pytest.mark.django_db
def test_a_different_kind_is_its_own_issue_and_the_last_refusal_is_remembered(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor, sent  # noqa: F811
):
    _two_closed_submissions(client, category, landing_type)
    runner = _use(monkeypatch, _FakeRunner(_vendor_error_stream(400, USAGE_LIMIT_MESSAGE), exit_code=1))
    _run_pending(client)
    runner.stdouts = [_vendor_error_stream(429, "API Error: 429 rate_limit_error: per-minute")]
    _run_pending(client)

    assert [e[1][2] for e in sent] == ["usage_limit", "rate_limit"]
    last = agent_refusal_alert.last_account_refusal()
    assert last is not None and (last["vendor"], last["kind"]) == ("anthropic", "rate_limit")  # 보내지 않은 거절도 갱신한다


@pytest.mark.django_db
def test_contest_quality_refusal_sends_through_the_same_place(
    client, closed, monkeypatch, agent_method, claude_vendor, sent  # noqa: F811
):
    _use(monkeypatch, _FakeRunner(_vendor_error_stream(400, USAGE_LIMIT_MESSAGE), exit_code=1))

    rows = _run_quality(client)["rows"]

    assert {r["status"] for r in rows} == {"deferred"}
    assert [e[1] for e in sent] == [["agent-account-refusal", "anthropic", "usage_limit"]]


def test_classroom_refusal_sends_through_the_same_place(client, db, monkeypatch, sent):
    from classroom.tests.test_classroom_agent_method import _Runner, _claude_key_class
    from tests.classroom_scenarios import run_scan, submit_repository

    _owner, participant, class_id, problem = _claude_key_class(client, monkeypatch)
    stream = _vendor_error_stream(400, f"{USAGE_LIMIT_MESSAGE} {SECRET_MARKER}")
    monkeypatch.setattr(agent_scoring, "request_run", _Runner(lambda: stream))

    submit_repository(client, participant["access"], class_id, problem.id)
    run_scan(client)

    assert [e[1] for e in sent] == [["agent-account-refusal", "anthropic", "usage_limit"]]
    assert SECRET_MARKER not in json.dumps(sent[0][:3])


def test_other_vendor_errors_send_nothing(sent):
    assert agent_scoring.account_refusal_kind("success api_error_status=400 invalid_request_error: schema") is None
    assert sent == []


def test_kinds_cover_every_marker():
    assert {agent_scoring.account_refusal_kind(m) for m in agent_scoring.ACCOUNT_REFUSAL_MARKERS} == {
        "usage_limit",
        "credit",
        "rate_limit",
    }


def test_an_alert_failure_never_breaks_scoring(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("sentry down")

    monkeypatch.setattr(agent_refusal_alert, "capture_grouped_warning", boom)
    caches["rate_limits"].clear()
    agent_refusal_alert.report_account_refusal("openai", "credit")  # 던지지 않는다
    last = agent_refusal_alert.last_account_refusal()
    assert last is not None and last["vendor"] == "openai"
