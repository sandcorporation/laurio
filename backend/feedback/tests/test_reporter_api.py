"""제보자 API — 계정별 권한, 비공개 스크린샷, 하루 상한 (#1238)."""

import pytest

from feedback.tests.helpers import (
    GIF,
    PNG,
    REPORTS_URL,
    UPLOAD_URL,
    Reporter,
    granted_reporter,
    operator_client,
    set_permission,
)

pytestmark = pytest.mark.django_db


def test_account_without_permission_is_refused_everywhere():
    reporter = Reporter("fb-none")

    assert reporter.get("/api/feedback/permission").json() == {"granted": False}
    assert reporter.post(UPLOAD_URL, {"content_type": "image/png"}).status_code == 403
    assert reporter.report().status_code == 403
    assert reporter.get(REPORTS_URL).status_code == 403
    assert reporter.get(f"{REPORTS_URL}/1").status_code == 403
    assert reporter.get(f"{REPORTS_URL}/1/screenshot").status_code == 403


def test_anonymous_is_refused():
    from django.test import Client

    assert Client().get("/api/feedback/permission").status_code == 401


def test_revoked_account_is_refused_again():
    operator = operator_client("fb-op-revoke")
    reporter = granted_reporter("fb-revoke", operator)
    assert reporter.report().status_code == 201

    assert set_permission(operator, reporter.user.pk, granted=False).status_code == 200

    assert reporter.get("/api/feedback/permission").json() == {"granted": False}
    assert reporter.report().status_code == 403


def test_granted_account_creates_lists_and_reads_own_report():
    reporter = granted_reporter("fb-ok", operator_client("fb-op-ok"))
    assert reporter.get("/api/feedback/permission").json() == {"granted": True}
    key = reporter.upload_screenshot()

    created = reporter.report(kind="suggestion", app="classroom", screenshot_key=key)

    assert created.status_code == 201, created.content
    body = created.json()
    assert body["status"] == "received"
    assert body["kind"] == "suggestion"
    assert body["app"] == "classroom"
    assert body["has_screenshot"] is True
    assert body["history"] == []

    listed = reporter.get(REPORTS_URL).json()
    assert [row["id"] for row in listed] == [body["id"]]
    assert "screenshot_key" not in listed[0]

    detail = reporter.get(f"{REPORTS_URL}/{body['id']}").json()
    assert detail["page_url"] == "https://codemit.kr/contests/1"
    assert detail["resolution_note"] == ""

    shot = reporter.get(f"{REPORTS_URL}/{body['id']}/screenshot")
    assert shot.status_code == 200, shot.content
    assert key in shot.json()["download_url"]


def test_report_without_screenshot_has_no_screenshot_to_open():
    reporter = granted_reporter("fb-noshot", operator_client("fb-op-noshot"))
    report_id = reporter.report().json()["id"]

    assert reporter.get(f"{REPORTS_URL}/{report_id}/screenshot").status_code == 404


def test_other_accounts_report_and_screenshot_are_not_found():
    operator = operator_client("fb-op-other")
    owner = granted_reporter("fb-owner", operator)
    stranger = granted_reporter("fb-stranger", operator)
    report_id = owner.report(screenshot_key=owner.upload_screenshot()).json()["id"]

    assert stranger.get(f"{REPORTS_URL}/{report_id}").status_code == 404
    assert stranger.get(f"{REPORTS_URL}/{report_id}/screenshot").status_code == 404
    assert stranger.get(REPORTS_URL).json() == []


def test_cannot_attach_someone_elses_screenshot():
    operator = operator_client("fb-op-steal")
    owner = granted_reporter("fb-steal-owner", operator)
    thief = granted_reporter("fb-steal-thief", operator)
    key = owner.upload_screenshot()

    assert thief.report(screenshot_key=key).status_code == 422


def test_screenshot_cannot_be_attached_twice():
    reporter = granted_reporter("fb-twice", operator_client("fb-op-twice"))
    key = reporter.upload_screenshot()
    assert reporter.report(screenshot_key=key).status_code == 201

    assert reporter.report(screenshot_key=key).status_code == 422


def test_upload_refuses_other_image_formats():
    reporter = granted_reporter("fb-format", operator_client("fb-op-format"))

    assert reporter.post(UPLOAD_URL, {"content_type": "image/gif"}).status_code == 422


def test_report_refuses_bytes_that_are_not_an_allowed_image():
    reporter = granted_reporter("fb-sniff", operator_client("fb-op-sniff"))
    key = reporter.upload_screenshot(content=GIF, content_type="image/png")

    assert reporter.report(screenshot_key=key).status_code == 422


def test_report_refuses_screenshot_over_5mb():
    reporter = granted_reporter("fb-big", operator_client("fb-op-big"))
    key = reporter.upload_screenshot(content=PNG + b"\x00" * (5 * 1024 * 1024))

    assert reporter.report(screenshot_key=key).status_code == 422


def test_report_refuses_screenshot_not_yet_uploaded():
    reporter = granted_reporter("fb-missing", operator_client("fb-op-missing"))
    response = reporter.post(UPLOAD_URL, {"content_type": "image/png"})

    assert reporter.report(screenshot_key=response.json()["object_key"]).status_code == 422


def test_body_limits():
    reporter = granted_reporter("fb-body", operator_client("fb-op-body"))

    assert reporter.report(body="   ").status_code == 422
    assert reporter.report(body="가" * 4001).status_code == 422
    assert reporter.report(body="가" * 4000).status_code == 201
    assert reporter.report(kind="praise").status_code == 422


def test_twenty_reports_a_day_then_429():
    reporter = granted_reporter("fb-limit", operator_client("fb-op-limit"))
    for _ in range(20):
        assert reporter.report().status_code == 201

    response = reporter.report()

    assert response.status_code == 429, response.content
