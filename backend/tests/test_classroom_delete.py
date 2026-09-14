"""삭제 — 아무도 내지 않은 클래스는 없던 일로 할 수 있다 (#330, CONTEXT.md 「Class」).

보관과 다르다: 보관은 「끝난 수업」(지난 기록이 살아 있어야 한다), 삭제는 「없던
일」(남길 것이 없다). 그래서 **제출이 하나라도 있으면 거절한다** — 그 사람이 낸
것과 그 판정은 참여자의 기록이라 강사가 지울 수 없다. 제출이 없으면(참여자가
들어와 있기만 해도) 지울 수 있고, 그 사람들의 가입도 함께 사라진다. 이 클래스에서
공개한 템플릿은 클래스를 가리키지 않는 사본이라 영향받지 않는다(#316·#319).
"""

from __future__ import annotations

from classroom.models import Class, ClassMember, Problem

CLASSES_URL = "/api/classroom/classes"
CLASS_TEMPLATES_URL = "/api/classroom/class-templates"


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


def _submit(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _publish_class(client, access: str, class_id: int, publisher_display_name="김강사"):
    return client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


# --- 제출이 없으면 지울 수 있다 -----------------------------------------------


def test_class_with_no_submissions_can_be_deleted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert response.status_code == 204
    assert not Class.objects.filter(id=created["id"]).exists()


def test_deleting_a_class_with_only_members_and_no_submissions_succeeds(client, db):
    """참여자가 들어와 있기만 하고 아무것도 안 냈다면 지울 수 있다 — 다만 그
    사람들의 가입도 함께 사라진다."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    _create_open_problem(client, instructor["access"], created["id"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    assert ClassMember.objects.filter(classroom_id=created["id"]).exists()

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert response.status_code == 204
    assert not ClassMember.objects.filter(classroom_id=created["id"]).exists()


def test_deleting_a_class_removes_its_problems_and_checklist(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], created["id"])

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert response.status_code == 204
    assert not Problem.objects.filter(id=problem_id).exists()


def test_deleted_classs_join_code_no_longer_resolves(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    join_code = created["join_code"]

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert response.status_code == 204

    preview = client.get(f"/api/classroom/join/{join_code}")
    assert preview.status_code == 404


# --- 제출이 하나라도 있으면 지울 수 없다 --------------------------------------


def test_class_with_a_submission_cannot_be_deleted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], created["id"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    _submit(client, participant["access"], created["id"], problem_id)

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert response.status_code == 403
    assert response.json()["detail"]
    assert Class.objects.filter(id=created["id"]).exists()


def test_class_out_reports_has_submissions_so_the_screen_does_not_derive_it(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], created["id"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])

    before = client.get(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert before.json()["has_submissions"] is False

    _submit(client, participant["access"], created["id"], problem_id)

    after = client.get(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert after.json()["has_submissions"] is True


# --- 남의 클래스는 지울 수 없다 -----------------------------------------------


def test_deleting_someone_elses_class_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    created = _create_class(client, a["access"], name="A의 클래스")

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(b["access"]))
    assert response.status_code == 404
    assert Class.objects.filter(id=created["id"]).exists()


# --- 공개한 템플릿은 남는다 ---------------------------------------------------


def test_published_class_template_survives_class_deletion(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"], name="1학기 웹 스터디")
    _create_open_problem(client, instructor["access"], created["id"])

    published = _publish_class(client, instructor["access"], created["id"], "김강사")
    assert published.status_code == 201, published.content
    share_code = published.json()["share_code"]

    response = client.delete(f"{CLASSES_URL}/{created['id']}", **_auth_header(instructor["access"]))
    assert response.status_code == 204

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(instructor["access"]))
    assert preview.status_code == 200
    assert preview.json()["name"] == "1학기 웹 스터디"
