"""새 제보 접수 알림 — 접수가 커밋된 뒤 작업을 큐에 넣고, 작업이 번호·종류만 보낸다 (#1366)."""

import logging

import pytest
from django.db import transaction

from feedback import services
from feedback.models import FeedbackReport
from feedback.tasks import send_feedback_notice
from feedback.tests.helpers import granted_reporter, operator_client

pytestmark = pytest.mark.django_db

SECRET_URL = "https://hooks.invalid/secret-token-xyz"


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("ops_metrics.alerts.post_webhook", lambda url, content: calls.append((url, content)))
    return calls


@pytest.fixture
def delayed(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(send_feedback_notice, "delay", lambda report_id: calls.append(report_id))
    return calls


@pytest.fixture
def reporter():
    return granted_reporter("fb-notice", operator_client("fb-notice-op"))


def _new_report(reporter, **overrides) -> FeedbackReport:
    """접수만 한다 — 커밋 뒤 콜백은 돌리지 않는다(작업은 따로 부른다)."""

    assert reporter.report(**overrides).status_code == 201
    return FeedbackReport.objects.get()


def test_task_sends_one_line_with_number_and_kind_only_and_marks_forwarded(settings, sent, reporter):
    settings.FEEDBACK_NOTICE_WEBHOOK_URL = SECRET_URL
    report = _new_report(
        reporter, kind="bug", app="classroom", body="ZZ-특이한-본문-ZZ", page_url="https://x.test/ZZ-url"
    )

    send_feedback_notice(report.pk)

    assert sent == [(SECRET_URL, f"📮 [Codemit] 새 제보 #{report.pk} · 버그 · classroom")]
    assert "ZZ" not in sent[0][1]
    report.refresh_from_db()
    assert report.forwarded_at is not None


def test_task_with_unset_url_sends_nothing_and_leaves_unforwarded(settings, sent, reporter):
    settings.FEEDBACK_NOTICE_WEBHOOK_URL = ""
    report = _new_report(reporter)

    send_feedback_notice(report.pk)

    assert sent == []
    report.refresh_from_db()
    assert report.forwarded_at is None


def test_task_failure_keeps_report_unmarked_and_logs_no_address(settings, monkeypatch, reporter, caplog):
    settings.FEEDBACK_NOTICE_WEBHOOK_URL = SECRET_URL

    def boom(url, content):
        raise RuntimeError(f"connect to {url} failed")

    monkeypatch.setattr("ops_metrics.alerts.post_webhook", boom)
    report = _new_report(reporter)

    with caplog.at_level(logging.WARNING):
        send_feedback_notice(report.pk)

    report.refresh_from_db()
    assert report.forwarded_at is None
    assert "RuntimeError" in caplog.text
    assert "secret-token" not in caplog.text
    assert "hooks.invalid" not in caplog.text


def test_commit_enqueues_the_task_once_with_the_report_number(delayed, reporter, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        assert reporter.report().status_code == 201

    assert delayed == [FeedbackReport.objects.get().pk]


def test_rolled_back_report_enqueues_nothing(delayed, reporter, django_capture_on_commit_callbacks):
    data = services.NewReport(
        kind="bug", body="b", app="contest", page_url="", user_agent="", screen_width=None,
        screen_height=None, screenshot_key="",
    )

    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                services.create_report(reporter=reporter.user, data=data)
                raise RuntimeError("roll back")
        except RuntimeError:
            pass

    assert FeedbackReport.objects.count() == 0
    assert delayed == []


def test_enqueue_failure_does_not_break_the_report(monkeypatch, reporter, caplog, django_capture_on_commit_callbacks):
    def broker_down(report_id):
        raise ConnectionError("redis://secret-broker:6379 down")

    monkeypatch.setattr(send_feedback_notice, "delay", broker_down)

    with caplog.at_level(logging.WARNING), django_capture_on_commit_callbacks(execute=True):
        assert reporter.report().status_code == 201

    assert FeedbackReport.objects.count() == 1
    assert "ConnectionError" in caplog.text
    assert "secret-broker" not in caplog.text
