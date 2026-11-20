"""보관 — 읽기 전용이 된다 (#294, 뜻은 #438이 넓혔다, CONTEXT.md 「Class」, ADR-0037).

핵심 대상: 강사가 클래스를 보관하고 되돌릴 수 있고, 보관된 클래스는 새 가입·새
제출과 문제·체크리스트를 만들거나 바꾸는 모든 것이 닫힌다 — 지난 문제·제출물·
판정은 그대로 읽힌다. 「내 클래스」에서 진행중과 보관이 갈려 보이도록 `archived`가
각 행에 실린다.
"""

from __future__ import annotations

from classroom.models import Class
from tests.classroom_scenarios import (
    archive_class,
    create_class,
    create_open_problem,
    login,
)

CLASSES_URL = "/api/classroom/classes"


def _login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _create_class(client, access: str, name: str = "웹 스터디") -> dict:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def _create_open_problem(
    client, access: str, class_id: int, submission_format: str = "repository"
) -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": [submission_format]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "통과 조건", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> dict:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


# --- 보관/되돌리기 -----------------------------------------------------------


def test_class_starts_out_not_archived(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    assert created["archived"] is False


def test_instructor_archives_their_class(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200
    assert response.json()["archived"] is True

    class_obj = Class.objects.get(id=created["id"])
    assert class_obj.archived_at is not None


def test_archiving_is_idempotent(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])

    first = client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    first_archived_at = Class.objects.get(id=created["id"]).archived_at

    second = client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert second.status_code == 200
    assert Class.objects.get(id=created["id"]).archived_at == first_archived_at
    assert first.status_code == 200


def test_instructor_unarchives_their_class(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/unarchive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200
    assert response.json()["archived"] is False
    assert Class.objects.get(id=created["id"]).archived_at is None


def test_archiving_someone_elses_class_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    created = _create_class(client, a["access"], name="A의 클래스")

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(b["access"]),
    )
    assert response.status_code == 404
    assert Class.objects.get(id=created["id"]).archived_at is None


def test_my_classes_list_shows_archived_flag(client, db):
    instructor = _login(client)
    ongoing = _create_class(client, instructor["access"], name="진행중")
    archived = _create_class(client, instructor["access"], name="보관됨")
    client.post(
        f"{CLASSES_URL}/{archived['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    listing = client.get(CLASSES_URL, **_auth_header(instructor["access"]))
    by_id = {row["id"]: row["archived"] for row in listing.json()}
    assert by_id[ongoing["id"]] is False
    assert by_id[archived["id"]] is True


# --- 보관되면 가입 링크로 들어올 수 없다 -------------------------------------


def test_join_preview_of_archived_class_shows_archived_true_not_404(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.get(f"/api/classroom/join/{created['join_code']}")
    assert response.status_code == 200
    assert response.json()["archived"] is True


def test_joining_an_archived_class_is_rejected(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    participant = _login(client, uid="participant-1")

    response = client.post(
        f"/api/classroom/join/{created['join_code']}",
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


# --- 보관되면 새 제출을 낼 수 없다, 그러나 읽기는 남는다 --------------------


def test_existing_member_cannot_submit_to_an_archived_class(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], created["id"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])

    client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_archived_classs_past_problems_and_members_are_still_readable(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], created["id"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    # 강사: 클래스 상세·문제 목록·명단
    class_detail = client.get(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert class_detail.status_code == 200
    problems = client.get(
        f"{CLASSES_URL}/{created['id']}/problems", **_auth_header(instructor["access"])
    )
    assert problems.status_code == 200
    members = client.get(
        f"{CLASSES_URL}/{created['id']}/members", **_auth_header(instructor["access"])
    )
    assert members.status_code == 200

    # 참여자: 내 문제 목록·내 제출물
    mine = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/mine", **_auth_header(participant["access"])
    )
    assert mine.status_code == 200
    my_problem = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/mine",
        **_auth_header(participant["access"]),
    )
    assert my_problem.status_code == 200
    assert len(my_problem.json()["submissions"]) == 1


# --- 보관 = 읽기 전용: 문제·체크리스트를 만들거나 바꾸는 모든 것이 막힌다 (#438) --


def test_creating_a_problem_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "새 문제", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_updating_a_problem_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}",
        data={"title": "고친 제목"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_deleting_a_problem_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    response = client.delete(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_hiding_a_problem_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_reopening_a_problem_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    hidden = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert hidden.status_code == 200
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/reopen",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_opening_a_draft_problem_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, open=False)
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_reordering_problems_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    first = create_open_problem(client, instructor["access"], class_id, title="1주차")
    second = create_open_problem(client, instructor["access"], class_id, title="2주차")
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/reorder",
        data={"problem_ids": [second.id, first.id]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_creating_a_checklist_item_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/checklist-items",
        data={"label": "새 항목", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_updating_a_checklist_item_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/checklist-items/{problem.item_id}",
        data={"label": "고친 항목"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_deleting_a_checklist_item_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    response = client.delete(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/checklist-items/{problem.item_id}",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_reordering_checklist_items_in_an_archived_class_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client, instructor["access"], class_id, required_labels=["항목1", "항목2"]
    )
    archive_class(client, instructor["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/checklist-items/reorder",
        data={"item_ids": list(reversed(problem.item_ids))},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


# --- 보관 = 읽기 전용이지만 열려 있는 것은 그대로 열려 있다 (#438) -----------


def test_class_settings_can_still_be_patched_while_archived(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    archive_class(client, instructor["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"name": "새 이름"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "새 이름"


def test_class_can_still_be_deleted_while_archived(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    archive_class(client, instructor["access"], class_id)

    response = client.delete(
        f"{CLASSES_URL}/{class_id}",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 204
    assert not Class.objects.filter(id=class_id).exists()
