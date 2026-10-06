"""강사마다 이 클래스에서 불릴 강사 이름 (#565, spec #558, ADR-0055, CONTEXT.md 「공동 강사」).

강사 누구나 **자기** 이름만 바꾼다 — 경로가 `instructors/me` 라 다른 강사를 가리킬 자리가 없다.
소유자의 이름 칸(클래스 설정의 `instructor_display_name`)은 여전히 소유자 전용이다. 가입 미리보기는
강사 전원의 이름을 보여 준다. 준비와 확인은 전부 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`).
"""

from __future__ import annotations

from classroom.models import Class
from tests.classroom_scenarios import (
    add_co_instructor,
    archive_class,
    create_class,
    get_class,
    join,
    join_code,
    join_preview,
    list_instructors,
    login,
    rename_my_instructor_name,
    transfer_ownership,
)


def _names(client, access, class_id) -> list[tuple[str, str]]:
    return [(row["role"], row["display_name"]) for row in list_instructors(client, access, class_id)]


def test_a_co_instructor_renames_only_themselves(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    other = login(client, "other")
    class_id = create_class(client, owner["access"])  # 소유자의 강사 이름은 「강사」
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, other["access"], display_name="조교")

    response = rename_my_instructor_name(client, co["access"], class_id, "박조교")

    assert response.status_code == 200, response.content
    assert _names(client, owner["access"], class_id) == [
        ("owner", "강사"),
        ("co_instructor", "박조교"),
        ("co_instructor", "조교"),
    ]


def test_the_owner_renames_themselves_through_the_same_route(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")

    response = rename_my_instructor_name(client, owner["access"], class_id, "김강사")

    assert response.status_code == 200, response.content
    assert (response.json()["role"], response.json()["is_me"]) == ("owner", True)
    assert _names(client, co["access"], class_id) == [("owner", "김강사"), ("co_instructor", "보조 강사")]
    # 클래스 설정이 읽는 소유자의 이름 칸도 같은 값이다.
    assert get_class(client, co["access"], class_id)["instructor_display_name"] == "김강사"


def test_the_class_screen_carries_the_viewers_own_instructor_name(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")

    assert get_class(client, owner["access"], class_id)["my_instructor_display_name"] == "강사"
    seen_by_co = get_class(client, co["access"], class_id)
    assert seen_by_co["my_instructor_display_name"] == "보조 강사"
    # 소유자의 이름 칸은 공동 강사에게도 소유자의 이름이다.
    assert seen_by_co["instructor_display_name"] == "강사"


def test_the_owners_name_field_in_class_settings_stays_closed_to_a_co_instructor(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")

    response = client.patch(
        f"/api/classroom/classes/{class_id}",
        data={"instructor_display_name": "가로챈 이름"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {co['access']}",
    )

    assert response.status_code == 403
    assert _names(client, owner["access"], class_id)[0] == ("owner", "강사")


def test_a_banned_instructor_name_is_refused(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")

    response = rename_my_instructor_name(client, co["access"], class_id, "운영자")

    assert response.status_code == 422
    assert _names(client, owner["access"], class_id)[1] == ("co_instructor", "보조 강사")


def test_a_blank_instructor_name_is_refused(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])

    assert rename_my_instructor_name(client, owner["access"], class_id, "").status_code == 422


def test_names_can_be_changed_in_an_archived_class(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    archive_class(client, owner["access"], class_id)

    assert rename_my_instructor_name(client, co["access"], class_id, "지난 기수 조교").status_code == 200
    assert _names(client, owner["access"], class_id)[1] == ("co_instructor", "지난 기수 조교")


def test_a_participant_or_a_stranger_has_no_instructor_name_to_change(client, db):
    owner = login(client, "owner")
    participant = login(client, "participant")
    stranger = login(client, "stranger")
    class_id = create_class(client, owner["access"])
    join(client, participant["access"], join_code(client, owner["access"], class_id))

    assert rename_my_instructor_name(client, participant["access"], class_id, "강사 행세").status_code == 404
    assert rename_my_instructor_name(client, stranger["access"], class_id, "강사 행세").status_code == 404
    assert _names(client, owner["access"], class_id) == [("owner", "강사")]


def test_after_an_ownership_transfer_each_instructor_keeps_and_renames_their_own_name(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="보조 강사")

    assert rename_my_instructor_name(client, owner["access"], class_id, "넘긴 강사").status_code == 200

    assert _names(client, co["access"], class_id) == [("owner", "보조 강사"), ("co_instructor", "넘긴 강사")]
    assert get_class(client, owner["access"], class_id)["my_instructor_display_name"] == "넘긴 강사"


# --- 가입 미리보기 --------------------------------------------------------------------


def test_the_join_preview_shows_every_instructors_name_owner_first(client, db):
    owner = login(client, "owner")
    first = login(client, "first")
    second = login(client, "second")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, first["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, second["access"], display_name="조교")
    rename_my_instructor_name(client, second["access"], class_id, "박조교")

    preview = join_preview(client, join_code(client, owner["access"], class_id))  # 로그인하지 않은 방문자

    assert preview["instructor_display_names"] == ["강사", "보조 강사", "박조교"]


def test_the_join_preview_leaves_out_a_blank_owner_name(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    # 강사 이름 칸이 생기기 전에 만들어진 클래스(#299)는 HTTP 로 만들 수 없다 — 그 옛 상태만 흉내 낸다.
    Class.objects.filter(id=class_id).update(instructor_display_name="")

    preview = join_preview(client, join_code(client, owner["access"], class_id))

    assert preview["instructor_display_names"] == ["보조 강사"]


def test_the_join_preview_has_no_names_when_every_name_is_blank(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    Class.objects.filter(id=class_id).update(instructor_display_name="")

    preview = join_preview(client, join_code(client, owner["access"], class_id))

    assert preview["instructor_display_names"] == []
