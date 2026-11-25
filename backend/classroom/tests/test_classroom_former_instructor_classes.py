"""한때 강사였던 클래스 목록 (#1465 2) — 강사에서 빠진 사람에게만 「더 이상 강사가 아닙니다」라고 말하려고
화면이 읽는다. 처음부터 관계 없던 사람·초대를 받기만 한 사람·지금도 강사인 사람에게는 비어 있어야 한다
(없는 클래스·남의 클래스의 존재를 말하지 않는다, #278)."""

from __future__ import annotations

from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    auth_header,
    create_class,
    create_co_instructor_invite,
    leave_class,
    list_instructors,
    login,
    remove_co_instructor,
)

URL = f"{CLASSES_URL}/former-instructor"


def _former_ids(client, access: str) -> list[int]:
    response = client.get(URL, **auth_header(access))
    assert response.status_code == 200, response.content
    return [row["id"] for row in response.json()]


def _co_id(client, owner_access: str, class_id: int) -> int:
    return [r for r in list_instructors(client, owner_access, class_id) if r["co_instructor_id"] is not None][0][
        "co_instructor_id"
    ]


def test_a_co_instructor_the_owner_removed_is_listed(client, db):
    owner, co = login(client, "owner"), login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    assert _former_ids(client, co["access"]) == []

    assert remove_co_instructor(client, owner["access"], class_id, _co_id(client, owner["access"], class_id)).status_code == 204

    assert _former_ids(client, co["access"]) == [class_id]


def test_a_co_instructor_who_left_is_listed(client, db):
    owner, co = login(client, "owner"), login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])

    assert leave_class(client, co["access"], class_id).status_code == 204

    assert _former_ids(client, co["access"]) == [class_id]


def test_nobody_else_learns_the_class_exists(client, db):
    owner, co, stranger, invited = login(client, "owner"), login(client, "co"), login(client, "stranger"), login(client, "invited")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    create_co_instructor_invite(client, owner["access"], class_id)  # 받기만 하고 수락하지 않은 초대
    remove_co_instructor(client, owner["access"], class_id, _co_id(client, owner["access"], class_id))

    assert _former_ids(client, stranger["access"]) == []
    assert _former_ids(client, invited["access"]) == []
    assert _former_ids(client, owner["access"]) == []


def test_a_current_co_instructor_is_not_listed(client, db):
    owner, co = login(client, "owner"), login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])

    assert _former_ids(client, co["access"]) == []
