"""요청을 찾지 못한 「넘기려 합니다」 알림은 끝난 요청이다 — 옛 알림은 정확한 요청에 잇는다 (#1448 일부-6·②).

`transfer_id` 를 싣기 전(#1441)에 만든 요청 알림과, 받는 사람이 떠나 요청 행이 지워진 알림이 「수락하세요」로
돌아가지 않게 한다. 옛 알림은 받는 사람·클래스·알림 생성 시각과 요청 생성 시각이 요청 하나로 정해질 때만 잇는다
(`classroom.transfer_notification_backfill`) — 클래스 번호만으로 이으면 반복 요청이 섞인다.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from classroom.models import OwnershipTransfer
from classroom.transfer_notification_backfill import link_legacy_request_notifications
from core.models import ClockOverride
from notifications.models import Notification
from tests.classroom_scenarios import (
    accept_ownership_transfer,
    cancel_ownership_transfer,
    co_instructor_id_of,
    decline_ownership_transfer,
    remove_co_instructor,
)

from .test_classroom_ownership_transfer_notifications import (
    REQUESTED,
    _notifications,
    _request,
    _three_instructors,
)


def _strip_transfer_ids() -> None:
    """#1441 전의 모양 — 요청 알림의 `context` 에 `transfer_id` 가 없다."""

    for notification in Notification.objects.filter(notification_type=REQUESTED):
        notification.context.pop("transfer_id", None)
        notification.save(update_fields=["context"])


def _requested_rows(client, access: str) -> list[dict]:
    return [r for r in _notifications(client, access) if r["notification_type"] == REQUESTED]


def _backfill() -> int:
    return link_legacy_request_notifications(Notification, OwnershipTransfer)


def _at(moment) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": moment})


# --- 찾지 못함은 대기가 아니다 ------------------------------------------------------------


def test_a_request_notification_without_a_transfer_id_is_gone_not_pending(client, db):
    owner, co, _, class_id = _three_instructors(client)
    _request(client, owner, class_id)
    _strip_transfer_ids()

    assert _requested_rows(client, co["access"])[0]["transfer_status"] == "gone"


def test_a_request_whose_row_was_deleted_when_the_recipient_left_is_gone(client, db):
    owner, co, _, class_id = _three_instructors(client)
    _request(client, owner, class_id)
    row_id = co_instructor_id_of(client, owner["access"], class_id, "보조 강사")
    assert remove_co_instructor(client, owner["access"], class_id, row_id).status_code == 204
    assert not OwnershipTransfer.objects.exists()

    assert _requested_rows(client, co["access"])[0]["transfer_status"] == "gone"


# --- 옛 알림을 정확한 요청에 잇는다 ---------------------------------------------------------


def test_backfill_links_each_old_notification_to_its_own_request(client, db):
    """같은 사람·같은 클래스의 반복 요청 — 시각으로 각자의 요청에 이어져 상태가 섞이지 않는다."""

    start = timezone.now()
    _at(start)
    owner, co, _, class_id = _three_instructors(client)
    first = _request(client, owner, class_id)
    assert cancel_ownership_transfer(client, owner["access"], class_id, first["id"]).status_code == 204
    _at(start + timedelta(hours=1))
    second = _request(client, owner, class_id)
    _strip_transfer_ids()

    assert _backfill() == 2

    by_transfer = {
        n.context["transfer_id"]: n for n in Notification.objects.filter(notification_type=REQUESTED)
    }
    assert set(by_transfer) == {first["id"], second["id"]}
    assert sorted(r["transfer_status"] for r in _requested_rows(client, co["access"])) == ["cancelled", "pending"]


def test_backfill_does_not_link_when_the_times_do_not_pick_one_request(client, db):
    """취소하고 곧바로 다시 요청했다 — 두 요청 모두 알림 시각 바로 앞이라 어느 쪽인지 정할 수 없다."""

    _at(timezone.now())
    owner, co, _, class_id = _three_instructors(client)
    first = _request(client, owner, class_id)
    assert cancel_ownership_transfer(client, owner["access"], class_id, first["id"]).status_code == 204
    _request(client, owner, class_id)
    _strip_transfer_ids()

    assert _backfill() == 0
    assert all("transfer_id" not in n.context for n in Notification.objects.filter(notification_type=REQUESTED))
    assert [r["transfer_status"] for r in _requested_rows(client, co["access"])] == ["gone", "gone"]


def test_backfill_leaves_notifications_with_a_transfer_id_alone(client, db):
    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)

    assert _backfill() == 0
    assert Notification.objects.get(notification_type=REQUESTED).context["transfer_id"] == transfer["id"]


def test_backfill_marks_an_answered_old_request_notification_read(client, db):
    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)
    _strip_transfer_ids()
    # #1441 전에는 답해도 알림이 안 읽은 채 남았다.
    assert decline_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 204
    assert _requested_rows(client, co["access"])[0]["read_at"] is None

    assert _backfill() == 1

    row = _requested_rows(client, co["access"])[0]
    assert row["transfer_status"] == "declined"
    assert row["read_at"] is not None


def test_answering_after_the_backfill_marks_the_old_notification_read(client, db):
    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)
    _strip_transfer_ids()
    _backfill()
    assert _requested_rows(client, co["access"])[0]["read_at"] is None

    assert accept_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 200

    assert _requested_rows(client, co["access"])[0]["read_at"] is not None


def test_other_notification_types_still_carry_no_transfer_state(client, db):
    owner, co, _, class_id = _three_instructors(client)
    _request(client, owner, class_id)
    _strip_transfer_ids()

    rows = [r for r in _notifications(client, co["access"]) if r["notification_type"] != REQUESTED]
    assert all(r["transfer_status"] is None for r in rows)
