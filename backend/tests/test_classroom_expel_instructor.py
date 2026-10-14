"""강사의 자기 참여자 행은 내보낼 수 없다(#669) — 그 행은 집계에서 이미 빠지므로 내보낼 이유가 없고,
내보내면 강사가 자기 클래스에 다시 낼 길만 막힌다. 소유자·공동 강사 모두, 참여자였다가 공동 강사가 된
사람도 강사다(CONTEXT 「공동 강사」)."""

from __future__ import annotations

from tests.classroom_scenarios import (
    add_co_instructor,
    auth_header,
    create_class,
    join_class,
    login,
)

CLASSES_URL = "/api/classroom/classes"


def _members(client, access: str, class_id: int) -> dict[str, int]:
    response = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(access))
    return {m["display_name"]: m["id"] for m in response.json()}


def _expel(client, access: str, class_id: int, member_id: int):
    return client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **auth_header(access),
    )


def test_an_instructors_own_member_row_cannot_be_expelled(client, db):
    owner = login(client, "owner-1")
    class_id = create_class(client, owner["access"])
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="소유자")
    joined_first = login(client, "co-1")
    join_class(client, joined_first["access"], class_id, instructor_access=owner["access"], display_name="먼저 들어온 사람")
    add_co_instructor(client, owner["access"], class_id, joined_first["access"])
    participant = login(client, "participant-1")
    join_class(client, participant["access"], class_id, instructor_access=owner["access"], display_name="참여자")
    members = _members(client, owner["access"], class_id)

    for name in ("소유자", "먼저 들어온 사람"):
        response = _expel(client, owner["access"], class_id, members[name])
        assert response.status_code == 403, name
        assert response.json()["detail"] == "강사는 내보낼 수 없습니다."
    assert _expel(client, joined_first["access"], class_id, members["참여자"]).status_code == 200

    expelled = {m["display_name"]: m["expelled"] for m in client.get(
        f"{CLASSES_URL}/{class_id}/members", **auth_header(owner["access"])
    ).json()}
    assert expelled == {"소유자": False, "먼저 들어온 사람": False, "참여자": True}
