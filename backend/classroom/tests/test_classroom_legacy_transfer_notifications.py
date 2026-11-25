"""「넘기려 합니다」 알림이 가리키는 요청을 모를 때와 그 요청이 끝났을 때를 가른다 (#1448 일부-6·②, #1459 ①·②).

`transfer_id` 를 싣기 전(#1441)에 만든 요청 알림과, 받는 사람이 떠나 요청 행이 지워진 알림이 「수락하세요」로
돌아가지 않게 한다. 옛 알림은 받는 사람·클래스·알림 생성 시각과 요청 생성 시각이 요청 하나로 정해질 때만 잇는다
(`classroom.transfer_notification_backfill`, `classroom.0052`) — 클래스 번호만으로 이으면 반복 요청이 섞인다.
잇지 못한 알림은 그 클래스에 그 사람 앞 대기 요청이 있으면 `unknown`(끝났다고 단정하지 않는다), 없으면 `gone`.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from classroom.models import OwnershipTransfer
from classroom.transfer_notification_backfill import link_legacy_request_notifications
from core.models import ClockOverride
from notifications.models import Notification
from tests.classroom_scenarios import (
    accept_ownership_transfer,
    add_co_instructor,
    cancel_ownership_transfer,
    co_instructor_id_of,
    create_class,
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


# --- 잇지 못한 알림은 모른다고 말한다 — 대기가 아니고, 끝났다고 단정하지도 않는다 ---------------------


def test_an_unlinked_notification_is_unknown_while_the_class_has_a_pending_request_for_them(client, db):
    """대기 중인 요청이 이 알림의 것인지 모른다 — 「끝났습니다」로 단정하면 지금 답할 요청을 놓친다(#1459 ①)."""

    owner, co, _, class_id = _three_instructors(client)
    _request(client, owner, class_id)
    _strip_transfer_ids()

    assert _requested_rows(client, co["access"])[0]["transfer_status"] == "unknown"


def test_an_unlinked_notification_is_gone_when_the_class_has_no_pending_request_for_them(client, db):
    """대기 요청이 없으면 이 알림의 요청도 대기일 수 없다 — 끝났다."""

    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)
    assert cancel_ownership_transfer(client, owner["access"], class_id, transfer["id"]).status_code == 204
    _strip_transfer_ids()

    assert _requested_rows(client, co["access"])[0]["transfer_status"] == "gone"


def test_a_pending_request_in_another_class_does_not_make_an_unlinked_notification_unknown(client, db):
    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)
    assert cancel_ownership_transfer(client, owner["access"], class_id, transfer["id"]).status_code == 204
    _strip_transfer_ids()
    other_class_id = create_class(client, owner["access"], name="알고리즘 2반")
    add_co_instructor(client, owner["access"], other_class_id, co["access"], display_name="보조 강사")
    _request(client, owner, other_class_id)

    rows = _requested_rows(client, co["access"])
    by_class = {r["context"]["class_id"]: r["transfer_status"] for r in rows}
    assert by_class == {class_id: "gone", other_class_id: "pending"}


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
    _at(start + timedelta(hours=2))
    assert cancel_ownership_transfer(client, owner["access"], class_id, second["id"]).status_code == 204
    third = _request(client, owner, class_id)
    _strip_transfer_ids()

    assert _backfill() == 3

    by_transfer = {
        n.context["transfer_id"]: n for n in Notification.objects.filter(notification_type=REQUESTED)
    }
    assert set(by_transfer) == {first["id"], second["id"], third["id"]}
    assert sorted(r["transfer_status"] for r in _requested_rows(client, co["access"])) == [
        "cancelled",
        "cancelled",
        "pending",
    ]


def test_backfill_reads_and_writes_in_a_fixed_number_of_queries(client, db):
    """알림 수에 비례하지 않는다 — 옛 알림 읽기 하나, 후보 요청 읽기 하나, `bulk_update` 하나(#1459 ②)."""

    start = timezone.now()
    _at(start)
    owner, co, _, class_id = _three_instructors(client)
    first = _request(client, owner, class_id)
    assert cancel_ownership_transfer(client, owner["access"], class_id, first["id"]).status_code == 204
    _at(start + timedelta(hours=1))
    second = _request(client, owner, class_id)
    assert decline_ownership_transfer(client, co["access"], class_id, second["id"]).status_code == 204
    _at(start + timedelta(hours=2))
    _request(client, owner, class_id)
    _strip_transfer_ids()

    with CaptureQueriesContext(connection) as queries:
        assert _backfill() == 3
    assert len(queries) == 3, [q["sql"] for q in queries]


def test_backfill_does_not_link_when_the_times_do_not_pick_one_request(client, db):
    """취소하고 곧바로 다시 요청했다 — 두 요청 모두 알림 시각 바로 앞이라 어느 쪽인지 정할 수 없다.

    둘 중 하나는 지금 대기 중인 요청의 알림이다 — 둘 다 「끝났습니다」로 단정하지 않고 모른다고 말한다(#1459 ①).
    읽음도 옮기지 않는다."""

    _at(timezone.now())
    owner, co, _, class_id = _three_instructors(client)
    first = _request(client, owner, class_id)
    assert cancel_ownership_transfer(client, owner["access"], class_id, first["id"]).status_code == 204
    _request(client, owner, class_id)
    _strip_transfer_ids()

    assert _backfill() == 0
    assert all("transfer_id" not in n.context for n in Notification.objects.filter(notification_type=REQUESTED))
    rows = _requested_rows(client, co["access"])
    assert [r["transfer_status"] for r in rows] == ["unknown", "unknown"]
    assert [r["read_at"] for r in rows] == [None, None]


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


# --- 마이그레이션 0052 가 실제로 잇는다 ---------------------------------------------------------

_LINK_MIGRATION = ("classroom", "0052_link_legacy_transfer_request_notifications")


def _apply_link_migration() -> None:
    """0051 끝의 상태에서 0052 하나만 적용한다 — 실행 기록(`django_migrations`)은 건드리지 않는다.

    helper 를 직접 부르는 위 시험들은 0052 의 `RunPython` 연결이 빠져도 통과한다 — 이 시험이 그 연결을 본다.
    classroom 을 executor 로 내렸다 올리면 기대는 앱까지 함께 오르내린다(`test_classroom_token_budget_columns_dropped`).
    """

    loader = MigrationExecutor(connection).loader
    migration = loader.graph.nodes[_LINK_MIGRATION]
    before = loader.project_state(migration.dependencies, at_end=True)
    with connection.schema_editor(atomic=migration.atomic) as editor:
        migration.apply(before, editor)


def test_migration_0052_links_an_old_notification_and_marks_it_read_when_answered(client, db):
    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)
    assert decline_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 204
    _strip_transfer_ids()
    Notification.objects.filter(notification_type=REQUESTED).update(read_at=None)

    _apply_link_migration()

    notification = Notification.objects.get(notification_type=REQUESTED)
    assert notification.context["transfer_id"] == transfer["id"]
    assert notification.read_at == OwnershipTransfer.objects.get(pk=transfer["id"]).declined_at
