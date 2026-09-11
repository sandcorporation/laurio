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


def _create_class(
    client, access: str, name: str = "웹 스터디", instructor_display_name: str = "강사"
) -> dict:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": instructor_display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def _join_url(code: str) -> str:
    return f"/api/classroom/join/{code}"


def test_join_preview_shows_class_name_instructor_display_name_problem_count_and_participant_count(
    client, db
):
    instructor = _login(client, uid="instructor-1", email="teacher@example.com")
    created = _create_class(
        client, instructor["access"], name="웹 스터디", instructor_display_name="김강사"
    )
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
    assert body["instructor_display_name"] == "김강사"
    assert body["problem_count"] == 1
    assert body["participant_count"] == 0


def test_join_preview_never_leaks_the_instructors_email(client, db):
    instructor = _login(client, uid="instructor-1", email="secret@example.com")
    created = _create_class(client, instructor["access"])

    response = client.get(_join_url(created["join_code"]))
    body = response.json()
    assert "instructor_email" not in body
    assert "secret@example.com" not in response.content.decode()


def test_join_preview_omits_instructor_display_name_when_blank(client, db):
    """이 필드가 생기기 전에 만든 클래스(ORM으로 직접 만든, API 검증을 거치지
    않은 행)는 빈 문자열이고, 미리보기는 그것을 `None`으로 내려 화면이 그 줄
    자체를 생략하게 한다."""

    from django.contrib.auth import get_user_model

    from classroom.models import Class

    instructor_user = get_user_model().objects.create_user(
        username="instructor-blank", email="blank@example.com"
    )
    class_obj = Class.objects.create(instructor=instructor_user, name="예전 클래스")

    response = client.get(_join_url(class_obj.join_code))
    assert response.status_code == 200
    assert response.json()["instructor_display_name"] is None


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


def test_join_preview_reports_the_class_id(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])

    response = client.get(_join_url(created["join_code"]))

    assert response.json()["class_id"] == created["id"]


def test_join_preview_for_an_anonymous_visitor_is_not_already_joined(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])

    response = client.get(_join_url(created["join_code"]))

    assert response.json()["already_joined"] is False


def test_join_preview_for_a_logged_in_non_member_is_not_already_joined(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    stranger = _login(client, uid="stranger-1")

    response = client.get(
        _join_url(created["join_code"]), **_auth_header(stranger["access"])
    )

    assert response.json()["already_joined"] is False


def test_reopening_the_join_link_reports_already_joined_so_the_screen_skips_the_name_form(
    client, db
):
    """티켓 #300 — 이미 가입한 사람이 링크를 다시 열면 이름 입력 폼이 아니라
    문제 목록으로 곧장 보내야 한다. 그 판단의 근거가 이 신호다."""

    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    client.post(
        _join_url(created["join_code"]),
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    response = client.get(
        _join_url(created["join_code"]), **_auth_header(participant["access"])
    )

    assert response.json()["already_joined"] is True


def test_an_expelled_member_still_reports_already_joined(client, db):
    """내보내진 사람도 다시 링크를 열면 문제 목록으로 보낸다(#300 AC) —
    가입 폼으로 돌아가지 않는다."""

    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    client.post(
        _join_url(created["join_code"]),
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    member = ClassMember.objects.get(
        classroom_id=created["id"], user__username__contains="participant-1"
    )
    client.post(
        f"{CLASSES_URL}/{created['id']}/members/{member.id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.get(
        _join_url(created["join_code"]), **_auth_header(participant["access"])
    )

    assert response.json()["already_joined"] is True


def test_reopening_the_join_link_does_not_re_admit_an_expelled_member(client, db):
    """가입 링크를 다시 타도 내보낸 것이 무효가 되지 않는다(#300 AC)."""

    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    client.post(
        _join_url(created["join_code"]),
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    member = ClassMember.objects.get(
        classroom_id=created["id"], user__username__contains="participant-1"
    )
    client.post(
        f"{CLASSES_URL}/{created['id']}/members/{member.id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.post(
        _join_url(created["join_code"]),
        data={"display_name": "다시 왔어요"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 200
    member.refresh_from_db()
    assert member.expelled_at is not None


def test_join_model_points_directly_to_user_not_a_role_profile():
    from django.contrib.auth import get_user_model

    field = ClassMember._meta.get_field("user")
    assert field.related_model is get_user_model()
