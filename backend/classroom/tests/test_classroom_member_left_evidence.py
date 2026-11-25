"""참여자 행의 「나감」 판정이 `left_by_self` 를 모르는 쓰기도 견딘다(#1503 ①②).

`left_by_self` 를 모르는 쓰기는 둘이다 — 0054 가 칸을 더하기 전에 닫힌 행과, 이행
뒤 겹쳐 배포 중인 옛 서버·코드만 되돌린 서버가 `expelled_at` 만 채운 행 — 둘 다 칸이 NULL(사유 불명)이다. 공동 강사의 떠나기·내보내기는 그런
쓰기에서 둘을 가를 흔적이 없지만, 탈퇴는 `accounts.Withdrawal` 이 남는다 — 그 흔적으로 읽을 때 판정한다
(`classroom.departures.left_member_ids`). 공동 강사였던 이력은 수락한 공동 강사 초대와, 초대 없이 공동 강사
줄을 만드는 수락된 소유권 이전의 넘긴 사람(`ownership_transfers.accept`) 둘이다."""

from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    auth_header,
    co_instructor_id_of,
    create_class,
    join_class,
    leave_class,
    login,
    remove_co_instructor,
    transfer_ownership,
)

from classroom.models import ClassMember
from notifications.models import Notification, NotificationType

WITHDRAWAL_URL = "/api/accounts/withdrawal"
_ADD = ("classroom", "0054_classmember_left_by_self")
_BEFORE = ("classroom", "0053_class_signal_rev")


def _members(client, access: str, class_id: int) -> dict[str, tuple[bool, bool]]:
    response = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(access))
    assert response.status_code == 200, response.content
    return {m["display_name"]: (m["expelled"], m["left"]) for m in response.json()}


def _withdraw(client, access: str) -> None:
    response = client.post(WITHDRAWAL_URL, content_type="application/json", **auth_header(access))
    assert response.status_code == 200, response.content


def _readd_left_by_self_column() -> None:
    """0054 만 되돌렸다가 다시 적용한다 — 칸이 생기기 전에 닫힌 행이 된다(실행 기록은 건드리지 않는다,
    `test_classroom_signal_rev_migration.py` 와 같은 까닭)."""

    loader = MigrationExecutor(connection).loader
    migration = loader.graph.nodes[_ADD]
    before = loader.project_state(_BEFORE, at_end=True)
    with connection.schema_editor(atomic=migration.atomic) as editor:
        migration.unapply(before, editor)
    with connection.schema_editor(atomic=migration.atomic) as editor:
        migration.apply(before, editor)


def _old_code_close_only_sets_expelled_at() -> None:
    """옛 코드 꼴 — `depart`·내보내기가 `left_by_self` 를 모르고 `expelled_at` 만 채운 것과 같은 상태로 만든다.
    칸을 모르는 쓰기는 칸을 건드리지 않으므로 칸의 DB 기본값(불명, NULL)이 남는다."""

    with connection.cursor() as cursor:
        cursor.execute("UPDATE classroom_classmember SET left_by_self = NULL WHERE expelled_at IS NOT NULL")


@pytest.mark.django_db(transaction=True)
def test_a_former_owner_who_co_taught_after_a_transfer_and_withdrew_before_0054_shows_as_left(client):
    """① 소유권을 넘겨 공동 강사가 된 이전 소유자 — 공동 강사 초대를 수락한 적이 없다."""

    giver = login(client, "giver")
    taker = login(client, "taker")
    class_id = create_class(client, giver["access"])
    join_class(client, giver["access"], class_id, instructor_access=giver["access"], display_name="넘긴 사람")
    add_co_instructor(client, giver["access"], class_id, taker["access"], display_name="받는 사람")
    transfer_ownership(client, giver["access"], class_id, taker["access"], recipient_name="받는 사람")
    _withdraw(client, giver["access"])

    _readd_left_by_self_column()

    assert _members(client, taker["access"], class_id)["넘긴 사람"] == (True, True)


@pytest.mark.django_db
def test_a_withdrawal_handled_by_old_code_after_0054_still_shows_as_left(client):
    """② 이행 뒤 옛 서버가 처리한 탈퇴 — 일회성 행 채우기는 이미 끝났어도 「나감」이다. 소유자가 내보낸
    뒤 탈퇴한 공동 강사, 강사가 내보낸 참여자, 탈퇴 직후 내보낸 학생(공동 강사였던 적이 없다)은 「내보냄」이다."""

    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    co = login(client, "co")
    removed = login(client, "removed")
    learner = login(client, "learner")
    quitter = login(client, "quitter")
    join_class(client, co["access"], class_id, instructor_access=owner["access"], display_name="탈퇴한 조교")
    join_class(client, removed["access"], class_id, instructor_access=owner["access"], display_name="내보낸 조교")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="내보낸 학생")
    join_class(client, quitter["access"], class_id, instructor_access=owner["access"], display_name="탈퇴한 학생")
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="조교1")
    add_co_instructor(client, owner["access"], class_id, removed["access"], display_name="조교2")
    co_id = co_instructor_id_of(client, owner["access"], class_id, "조교2")
    assert remove_co_instructor(client, owner["access"], class_id, co_id).status_code == 204
    _withdraw(client, co["access"])
    _withdraw(client, removed["access"])  # 내보낸 뒤의 탈퇴 — 행은 탈퇴 전에 닫혔다
    _withdraw(client, quitter["access"])
    for name in ("내보낸 학생", "탈퇴한 학생"):
        member_id = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(owner["access"])).json()
        member_id = next(m["id"] for m in member_id if m["display_name"] == name)
        expelled = client.post(f"{CLASSES_URL}/{class_id}/members/{member_id}/expel", **auth_header(owner["access"]))
        assert expelled.status_code == 200, expelled.content
    _old_code_close_only_sets_expelled_at()

    assert _members(client, owner["access"], class_id) == {
        "탈퇴한 조교": (True, True),
        "내보낸 조교": (True, False),
        "내보낸 학생": (True, False),
        "탈퇴한 학생": (True, False),
    }


def _expel(client, access: str, class_id: int, name: str) -> dict:
    members = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(access)).json()
    member_id = next(m["id"] for m in members if m["display_name"] == name)
    expelled = client.post(f"{CLASSES_URL}/{class_id}/members/{member_id}/expel", **auth_header(access))
    assert expelled.status_code == 200, expelled.content
    return expelled.json()


def _former_co_instructor_joins_withdraws_and_is_expelled(client) -> tuple[dict, int, ClassMember]:
    """#1509 ① — 공동 강사였다 떠난 사람이 참여자로 가입 → 탈퇴 → 강사가 1분 안에 내보낸다. 탈퇴 흔적·공동 강사
    이력이 모두 「나감」 추론의 조건을 채운다."""

    owner = login(client, "owner")
    former = login(client, "former")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, former["access"], display_name="옛 조교")
    assert leave_class(client, former["access"], class_id).status_code == 204
    join_class(client, former["access"], class_id, instructor_access=owner["access"], display_name="옛 조교 학생")
    _withdraw(client, former["access"])
    expelled = _expel(client, owner["access"], class_id, "옛 조교 학생")
    assert (expelled["expelled"], expelled["left"]) == (True, False)
    member = ClassMember.objects.get(classroom_id=class_id, display_name="옛 조교 학생")
    assert member.expelled_at - member.user.withdrawal.withdrawn_at < timedelta(minutes=1)
    return owner, class_id, member


@pytest.mark.django_db
def test_new_code_expelling_a_former_co_instructor_after_withdrawal_stays_expelled(client):
    """#1509 ① 새 코드가 내보낸 행은 사유가 확정이다 — 과거 공동 강사 이력·탈퇴 시각의 추론이 덮지 않는다.
    명단·한 명(내보내기 응답)·알림이 같은 「내보냄」을 말한다."""

    owner, class_id, member = _former_co_instructor_joins_withdraws_and_is_expelled(client)

    assert _members(client, owner["access"], class_id)["옛 조교 학생"] == (True, False)
    assert Notification.objects.filter(
        recipient_id=member.user_id, notification_type=NotificationType.CLASSROOM_MEMBER_EXPELLED
    ).exists()


@pytest.mark.django_db
def test_the_same_close_written_by_old_code_still_falls_back_to_inference(client):
    """#1509 ① 같은 행을 옛 코드가 닫았다면(사유 칸을 모르는 쓰기 — 불명) 추론이 그대로 돈다. 옛 코드의 내보내기와
    탈퇴를 가를 길은 없으므로 흔적이 맞으면 「나감」이다(받아들인 한계)."""

    owner, class_id, _ = _former_co_instructor_joins_withdraws_and_is_expelled(client)
    _old_code_close_only_sets_expelled_at()

    assert _members(client, owner["access"], class_id)["옛 조교 학생"] == (True, True)
