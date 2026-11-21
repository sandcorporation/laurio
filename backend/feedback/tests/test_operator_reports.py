"""운영자 제보 API·상태 알림·관리 명령·스크린샷 보관 기한 (#1239)."""

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from core.clock import Clock
from core.models import ClockOverride
from feedback.tests.helpers import ORIGIN, granted_reporter, operator_client
from storage.adapters import Bucket
from storage.adapters.fake import FakeStorageAdapter

pytestmark = pytest.mark.django_db

REPORTS_URL = "/api/operator/feedback-reports"
SCAN_URL = "/api/internal/scans/feedback-screenshot-retention"


def _set_status(operator, report_id, status, note=""):
    return operator.post(
        f"{REPORTS_URL}/{report_id}/status",
        data={"status": status, "note": note},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


def _bell(reporter, *, classroom: bool) -> list[dict]:
    query = "?classroom_only=true" if classroom else ""
    return reporter.get(f"/api/notifications/me{query}").json()["items"]


def _feedback_notices(items):
    return [n for n in items if "feedback_status_changed" in n["notification_type"]]


def _command(*args) -> str:
    out = StringIO()
    call_command("feedback_report", *args, stdout=out)
    return out.getvalue()


def _set_clock(at) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _run_scan(client):
    response = client.post(
        SCAN_URL,
        content_type="application/json",
        HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN,
    )
    assert response.status_code == 200, response.content
    return response.json()


# --- 운영자 API ------------------------------------------------------------------


def test_operator_lists_filters_and_reads_with_short_screenshot_url():
    operator = operator_client("fbr-op-list")
    reporter = granted_reporter("fbr-list", operator)
    bug = reporter.report(kind="bug", screenshot_key=reporter.upload_screenshot()).json()
    idea = reporter.report(kind="suggestion", app="classroom").json()

    rows = operator.get(REPORTS_URL, HTTP_ORIGIN=ORIGIN).json()
    assert [row["id"] for row in rows] == [idea["id"], bug["id"]]
    filtered = operator.get(REPORTS_URL, {"app": "classroom"}, HTTP_ORIGIN=ORIGIN).json()
    assert [row["id"] for row in filtered] == [idea["id"]]
    assert operator.get(REPORTS_URL, {"kind": "bug"}, HTTP_ORIGIN=ORIGIN).json()[0]["id"] == bug["id"]

    detail = operator.get(f"{REPORTS_URL}/{bug['id']}", HTTP_ORIGIN=ORIGIN).json()
    assert detail["user_agent"] == "Mozilla/5.0 시험"
    assert detail["screen_width"] == 1440
    assert detail["screenshot_url"].startswith(FakeStorageAdapter.base_url)
    assert operator.get(f"{REPORTS_URL}/{idea['id']}", HTTP_ORIGIN=ORIGIN).json()["screenshot_url"] is None


def test_reporter_cannot_use_operator_report_surface():
    reporter = granted_reporter("fbr-nonop", operator_client("fbr-op-nonop"))
    report_id = reporter.report().json()["id"]

    assert reporter.get(REPORTS_URL).status_code in (401, 403)
    assert reporter.post(f"{REPORTS_URL}/{report_id}/status", {"status": "deployed"}).status_code in (
        401,
        403,
    )


def test_status_change_notifies_once_in_contest_bell_only():
    operator = operator_client("fbr-op-contest")
    reporter = granted_reporter("fbr-contest", operator)
    report_id = reporter.report(app="contest").json()["id"]

    response = _set_status(operator, report_id, "in_progress", "확인 중입니다")

    assert response.status_code == 200, response.content
    assert response.json()["history"][0]["actor"] == "fbr-op-contest"
    contest_bell = _feedback_notices(_bell(reporter, classroom=False))
    assert len(contest_bell) == 1
    assert contest_bell[0]["notification_type"] == "feedback_status_changed"
    assert contest_bell[0]["context"]["report_id"] == report_id
    assert _feedback_notices(_bell(reporter, classroom=True)) == []


def test_classroom_report_notifies_in_classroom_bell_only():
    operator = operator_client("fbr-op-class")
    reporter = granted_reporter("fbr-class", operator)
    report_id = reporter.report(app="classroom").json()["id"]

    assert _set_status(operator, report_id, "declined", "의도된 동작입니다").status_code == 200

    classroom_bell = _feedback_notices(_bell(reporter, classroom=True))
    assert [n["notification_type"] for n in classroom_bell] == ["classroom_feedback_status_changed"]
    assert _feedback_notices(_bell(reporter, classroom=False)) == []


def test_reporter_sees_status_note_history_and_close():
    operator = operator_client("fbr-op-hist")
    reporter = granted_reporter("fbr-hist", operator)
    report_id = reporter.report().json()["id"]
    _set_status(operator, report_id, "in_progress")
    _set_status(operator, report_id, "deployed", "고쳐서 배포했습니다")

    detail = reporter.get(f"/api/feedback/reports/{report_id}").json()

    assert detail["status"] == "deployed"
    assert detail["resolution_note"] == "고쳐서 배포했습니다"
    assert detail["closed_at"] is not None
    assert [(h["from_status"], h["to_status"]) for h in detail["history"]] == [
        ("received", "in_progress"),
        ("in_progress", "deployed"),
    ]


def test_same_status_conflicts_and_unknown_report_is_404():
    operator = operator_client("fbr-op-conflict")
    reporter = granted_reporter("fbr-conflict", operator)
    report_id = reporter.report().json()["id"]

    assert _set_status(operator, report_id, "received").status_code == 409
    assert _set_status(operator, 999_999, "deployed").status_code == 404
    assert _set_status(operator, report_id, "done").status_code == 422
    assert _feedback_notices(_bell(reporter, classroom=False)) == []


# --- 관리 명령 ---------------------------------------------------------------------


def test_command_status_sends_same_notice_as_operator():
    reporter = granted_reporter("fbr-cmd", operator_client("fbr-op-cmd"))
    report_id = reporter.report().json()["id"]

    _command("status", str(report_id), "in_progress", "--note", "보고 있습니다")

    detail = reporter.get(f"/api/feedback/reports/{report_id}").json()
    assert detail["history"][0]["actor"] == "대장(명령)"
    assert detail["resolution_note"] == "보고 있습니다"
    assert len(_feedback_notices(_bell(reporter, classroom=False))) == 1
    with pytest.raises(CommandError):
        _command("status", str(report_id), "in_progress")


def test_command_show_reads_without_screenshot_contents():
    reporter = granted_reporter("fbr-show", operator_client("fbr-op-show"))
    key = reporter.upload_screenshot()
    report_id = reporter.report(body="버튼이 안 눌려요", screenshot_key=key).json()["id"]

    out = _command("show", str(report_id))

    assert f"제보 #{report_id}" in out
    assert "버튼이 안 눌려요" in out
    assert "스크린샷: 있음" in out
    assert key not in out


def test_take_never_returns_same_report_twice_until_lease_expires():
    reporter = granted_reporter("fbr-take", operator_client("fbr-op-take"))
    first = reporter.report().json()["id"]
    second = reporter.report(kind="suggestion").json()["id"]

    taken = [json.loads(line) for line in _command("take", "--limit", "1").splitlines()]
    assert [row["id"] for row in taken] == [first]
    assert set(taken[0]) == {"id", "kind", "app", "received_at"}
    again = [json.loads(line)["id"] for line in _command("take").splitlines()]
    assert again == [second]
    assert _command("take") == ""

    _command("mark-forwarded", str(first))
    _command("untake", str(second))
    assert [json.loads(line)["id"] for line in _command("list").splitlines()] == [second]
    with pytest.raises(CommandError):
        _command("mark-forwarded", str(first))

    _command("take")
    _set_clock(Clock.now() + timedelta(minutes=16))
    assert [json.loads(line)["id"] for line in _command("take").splitlines()] == [second]


# --- 보관 기한 -----------------------------------------------------------------------


def test_retention_scan_removes_only_expired_screenshots():
    operator = operator_client("fbr-op-ret")
    reporter = granted_reporter("fbr-ret", operator)
    start = Clock.now()
    _set_clock(start)
    closed_key = reporter.upload_screenshot()
    closed_id = reporter.report(screenshot_key=closed_key).json()["id"]
    open_key = reporter.upload_screenshot()
    open_id = reporter.report(screenshot_key=open_key).json()["id"]
    _set_status(operator, closed_id, "declined")

    _set_clock(start + timedelta(days=29))
    _run_scan(operator)
    assert reporter.get(f"/api/feedback/reports/{closed_id}").json()["has_screenshot"] is True

    _set_clock(start + timedelta(days=31))
    _run_scan(operator)
    closed = reporter.get(f"/api/feedback/reports/{closed_id}").json()
    assert closed["has_screenshot"] is False
    assert closed["body"]
    assert FakeStorageAdapter().read_object(closed_key, bucket=Bucket.PRIVATE) is None
    assert reporter.get(f"/api/feedback/reports/{open_id}").json()["has_screenshot"] is True

    _set_clock(start + timedelta(days=181))
    _run_scan(operator)
    assert reporter.get(f"/api/feedback/reports/{open_id}").json()["has_screenshot"] is False
    assert FakeStorageAdapter().read_object(open_key, bucket=Bucket.PRIVATE) is None
