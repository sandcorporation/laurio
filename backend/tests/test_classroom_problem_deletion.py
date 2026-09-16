"""삭제 — 아무도 내지 않은 문제는 없던 일로 할 수 있다 (#430, 부모 #428).

클래스 삭제(`test_classroom_delete.py`)와 같은 판정 모양이다: 시도가 하나라도
있으면 거절한다. 이 티켓은 append-only를 건드리지 않는다 — 시도가 0이면
`ClassroomScore`의 PROTECT를 애초에 만나지 않는다(강사 자신의 시도까지 지우는
일은 #431의 몫이다).
"""

from __future__ import annotations

from classroom.models import ChecklistItem, Problem

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


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_required_item(client, access: str, class_id: int, problem_id: int) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "통과 조건", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _open_problem(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> dict:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


def _submit(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _delete_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}"


def _publish_problem_template(client, access: str, class_id: int, problem_id: int, publisher="김강사"):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": publisher},
        content_type="application/json",
        **_auth_header(access),
    )


# --- 시도가 없으면 지울 수 있다 ------------------------------------------------


def test_problem_with_no_submissions_can_be_deleted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 204
    assert not Problem.objects.filter(id=problem_id).exists()


def test_deleting_a_problem_removes_its_checklist(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    item_id = _add_required_item(client, instructor["access"], created["id"], problem_id)

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 204
    assert not ChecklistItem.objects.filter(id=item_id).exists()


def test_open_problem_with_no_submissions_can_still_be_deleted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 204


# --- 시도가 하나라도 있으면 지울 수 없다 ----------------------------------------


def test_problem_with_a_participant_submission_cannot_be_deleted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    _submit(client, participant["access"], created["id"], problem_id)

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 403
    assert response.json()["detail"]
    assert Problem.objects.filter(id=problem_id).exists()


def test_problem_out_reports_deletable_matching_the_actual_delete_result(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    before = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    assert before.json()["deletable"] is True

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    _submit(client, participant["access"], created["id"], problem_id)

    after = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    assert after.json()["deletable"] is False

    # 실제 삭제 결과와 같은 답이어야 한다.
    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 403


# --- 남의 클래스 문제는 404다 --------------------------------------------------


def test_deleting_someone_elses_problem_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    created = _create_class(client, a["access"], name="A의 클래스")
    problem_id = _create_problem(client, a["access"], created["id"])

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(b["access"]))
    assert response.status_code == 404
    assert Problem.objects.filter(id=problem_id).exists()


# --- 공개한 템플릿은 남는다 ---------------------------------------------------


def test_published_problem_template_survives_problem_deletion(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"], title="1주차 과제")
    _add_required_item(client, instructor["access"], created["id"], problem_id)

    published = _publish_problem_template(client, instructor["access"], created["id"], problem_id)
    assert published.status_code == 201, published.content
    share_code = published.json()["share_code"]

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 204

    preview = client.get(
        f"/api/classroom/problem-templates/{share_code}", **_auth_header(instructor["access"])
    )
    assert preview.status_code == 200
    assert preview.json()["title"] == "1주차 과제"
