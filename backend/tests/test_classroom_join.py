"""링크로 들어오면 회원가입과 클래스 가입이 한 번에 끝난다 (#280,
CONTEXT.md 「강의실」, ADR-0037).

핵심 대상: 가입 링크를 연 사람이 클래스 미리보기(이름·강사·문제 수·참여자 수)를
보고, 로그인만 되어 있으면 「이 클래스에서 불릴 이름」을 받아 그대로 참여자가
된다 — 두 단계로 나뉘지 않는다. 같은 사람이 같은 클래스에 두 번 들어가지
않고, 죽은 링크(재발급으로 죽었거나 애초에 없는 코드)는 그 이유가 보인다.
"""

from __future__ import annotations

from classroom.models import ClassMember

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
        data={"name": name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def _join_url(code: str) -> str:
    return f"/api/classroom/join/{code}"


def test_join_preview_shows_class_name_instructor_problem_count_and_participant_count(
    client, db
):
    instructor = _login(client, uid="instructor-1", email="teacher@example.com")
    created = _create_class(client, instructor["access"], name="웹 스터디")
    class_id = created["id"]
    client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_format": "source"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.get(_join_url(created["join_code"]))
    assert response.status_code == 200
    body = response.json()
    assert body["class_name"] == "웹 스터디"
    assert body["instructor_email"] == "teacher@example.com"
    assert body["problem_count"] == 1
    assert body["participant_count"] == 0


def test_join_preview_requires_no_authentication(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])

    response = client.get(_join_url(created["join_code"]))
    assert response.status_code == 200


def test_join_preview_for_unknown_code_is_404_with_a_reason(client, db):
    response = client.get(_join_url("no-such-code"))
    assert response.status_code == 404
    assert response.json()["detail"]


def test_join_preview_for_regenerated_code_is_404(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    old_code = created["join_code"]

    client.post(
        f"{CLASSES_URL}/{created['id']}/join-link/regenerate",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.get(_join_url(old_code))
    assert response.status_code == 404


def test_joining_requires_authentication(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])

    response = client.post(
        _join_url(created["join_code"]),
        data={"display_name": "익명"},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_authenticated_user_joins_with_a_class_specific_name(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")

    response = client.post(
        _join_url(created["join_code"]),
        data={"display_name": "참여자닉네임"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["class_id"] == created["id"]
    assert body["display_name"] == "참여자닉네임"

    member = ClassMember.objects.get(classroom_id=created["id"], user__username__contains="participant-1")
    assert member.display_name == "참여자닉네임"


def test_joined_participant_is_counted_in_the_preview(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")

    client.post(
        _join_url(created["join_code"]),
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    preview = client.get(_join_url(created["join_code"]))
    assert preview.json()["participant_count"] == 1


def test_the_same_person_does_not_join_the_same_class_twice(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")

    client.post(
        _join_url(created["join_code"]),
        data={"display_name": "첫이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    second = client.post(
        _join_url(created["join_code"]),
        data={"display_name": "둘째이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert second.status_code == 200
    assert second.json()["display_name"] == "첫이름"
    assert ClassMember.objects.filter(classroom_id=created["id"]).count() == 1


def test_instructor_can_join_their_own_class(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])

    response = client.post(
        _join_url(created["join_code"]),
        data={"display_name": "강사 본인"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200
    assert ClassMember.objects.filter(
        classroom_id=created["id"], user__username__contains="instructor-1"
    ).exists()


def test_joining_a_dead_link_is_404_with_a_reason(client, db):
    participant = _login(client, uid="participant-1")

    response = client.post(
        _join_url("no-such-code"),
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert response.status_code == 404
    assert response.json()["detail"]


def test_join_model_points_directly_to_user_not_a_role_profile():
    from django.contrib.auth import get_user_model

    field = ClassMember._meta.get_field("user")
    assert field.related_model is get_user_model()
