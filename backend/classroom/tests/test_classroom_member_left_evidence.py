"""참여자 행의 「나감」 판정이 `left_by_self` 를 모르는 쓰기도 견딘다(#1503 ①②).

`left_by_self` 를 모르는 쓰기는 둘이다 — 0054 가 칸을 더하기 전에 닫힌 행(칸이 생길 때 전부 거짓)과, 이행
뒤 겹쳐 배포 중인 옛 서버·코드만 되돌린 서버가 `expelled_at` 만 채운 행. 공동 강사의 떠나기·내보내기는 그런
쓰기에서 둘을 가를 흔적이 없지만, 탈퇴는 `accounts.Withdrawal` 이 남는다 — 그 흔적으로 읽을 때 판정한다
(`classroom.departures.left_member_ids`). 공동 강사였던 이력은 수락한 공동 강사 초대와, 초대 없이 공동 강사
줄을 만드는 수락된 소유권 이전의 넘긴 사람(`ownership_transfers.accept`) 둘이다."""

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
    login,
    remove_co_instructor,
    transfer_ownership,
)

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
    """옛 코드 꼴 — `depart` 가 `left_by_self` 를 모르고 `expelled_at` 만 채운 것과 같은 상태로 만든다."""

    with connection.cursor() as cursor:
        cursor.execute("UPDATE classroom_classmember SET left_by_self = false WHERE expelled_at IS NOT NULL")


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
