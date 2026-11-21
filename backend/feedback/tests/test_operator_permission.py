"""운영자가 계정별로 제보 권한을 켜고 끈다 (#1238)."""

import pytest

from feedback.tests.helpers import (
    ORIGIN,
    PERMISSIONS_URL,
    Reporter,
    operator_client,
    set_permission,
)

pytestmark = pytest.mark.django_db


def test_grant_records_history_and_lists_account():
    operator = operator_client("fbp-op")
    reporter = Reporter("fbp-user")

    assert set_permission(operator, reporter.user.pk, granted=True, reason="베타 테스터").status_code == 200

    listed = operator.get(PERMISSIONS_URL, HTTP_ORIGIN=ORIGIN).json()
    assert [row["user_id"] for row in listed] == [reporter.user.pk]
    changes = operator.get(f"{PERMISSIONS_URL}/changes", HTTP_ORIGIN=ORIGIN).json()
    assert changes[0]["action"] == "granted"
    assert changes[0]["reason"] == "베타 테스터"
    assert changes[0]["operator_username"] == "fbp-op"

    found = operator.get(f"{PERMISSIONS_URL}/search", {"q": "fbp-user"}, HTTP_ORIGIN=ORIGIN).json()
    assert found[0]["is_granted"] is True


def test_reason_is_required_and_same_state_conflicts():
    operator = operator_client("fbp-op-rules")
    reporter = Reporter("fbp-rules")

    assert set_permission(operator, reporter.user.pk, granted=True, reason="  ").status_code == 422
    assert set_permission(operator, reporter.user.pk, granted=False).status_code == 409
    assert set_permission(operator, 999_999, granted=True).status_code == 404


def test_only_superuser_operator_changes_permission():
    operator = operator_client("fbp-op-plain", superuser=False)
    reporter = Reporter("fbp-plain")

    assert set_permission(operator, reporter.user.pk, granted=True).status_code == 403


def test_reporter_cannot_reach_operator_surface():
    reporter = Reporter("fbp-reporter")

    assert reporter.get(PERMISSIONS_URL).status_code in (401, 403)
