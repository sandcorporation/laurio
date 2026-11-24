"""새 제보 접수 알림 — 접수가 커밋된 뒤 한 건, 번호·종류만 (#1366)."""

import logging

import pytest
from django.db import transaction

from feedback.models import FeedbackReport
from feedback.tests.helpers import granted_reporter, operator_client

pytestmark = pytest.mark.django_db

SECRET_URL = "https://hooks.invalid/secret-token-xyz"


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("ops_metrics.alerts.post_webhook", lambda url, content: calls.append((url, content)))
    return calls


@pytest.fixture
def reporter():
    return granted_reporter("fb-notice", operator_client("fb-notice-op"))


def test_sends_one_line_with_number_and_kind_only_and_marks_forwarded(
    settings, sent, reporter, django_capture_on_commit_callbacks
):
    settings.FEEDBACK_NOTICE_WEBHOOK_URL = SECRET_URL

    with django_capture_on_commit_callbacks(execute=True):
        response = reporter.report(
            kind="bug", app="classroom", body="ZZ-특이한-본문-ZZ", page_url="https://x.test/ZZ-url"
        )

    assert response.status_code == 201
    report = FeedbackReport.objects.get()
    assert sent == [(SECRET_URL, f"📮 [Codemit] 새 제보 #{report.pk} · 버그 · classroom")]
    assert "ZZ" not in sent[0][1]
    assert report.forwarded_at is not None


def test_unset_url_sends_nothing_and_leaves_unforwarded(
    settings, sent, reporter, django_capture_on_commit_callbacks
):
    settings.FEEDBACK_NOTICE_WEBHOOK_URL = ""

    with django_capture_on_commit_callbacks(execute=True):
        assert reporter.report().status_code == 201

    assert sent == []
    assert FeedbackReport.objects.get().forwarded_at is None


def test_failed_send_keeps_report_unmarked_and_logs_no_address(
    settings, monkeypatch, reporter, caplog, django_capture_on_commit_callbacks
):
    settings.FEEDBACK_NOTICE_WEBHOOK_URL = SECRET_URL

    def boom(url, content):
        raise RuntimeError(f"connect to {url} failed")

    monkeypatch.setattr("ops_metrics.alerts.post_webhook", boom)

    with caplog.at_level(logging.WARNING), django_capture_on_commit_callbacks(execute=True):
        assert reporter.report().status_code == 201

    assert FeedbackReport.objects.count() == 1
    assert FeedbackReport.objects.get().forwarded_at is None
    assert "RuntimeError" in caplog.text
    assert "secret-token" not in caplog.text
    assert "hooks.invalid" not in caplog.text


def test_rolled_back_report_sends_nothing(settings, sent, reporter, django_capture_on_commit_callbacks):
    from feedback import services

    settings.FEEDBACK_NOTICE_WEBHOOK_URL = SECRET_URL
    user = reporter.user
    data = services.NewReport(
        kind="bug", body="b", app="contest", page_url="", user_agent="", screen_width=None,
        screen_height=None, screenshot_key="",
    )

    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                services.create_report(reporter=user, data=data)
                raise RuntimeError("roll back")
        except RuntimeError:
            pass

    assert FeedbackReport.objects.count() == 0
    assert sent == []
