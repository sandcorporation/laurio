"""참여자가 클래스에서 불릴 이름을 스스로 바꾼다 (#372, CONTEXT.md
「ClassMember」).

핵심 대상: 참여자 본인만 자기 ClassMember 이름을 클래스마다 따로 바꿀 수
있다. 강사는 바꾸지 못한다 — 이 엔드포인트가 찾는 행은 언제나 요청자
자신이다. 바꾸면 명단(#281)과 지난 제출물(#291)이 비정규화 없이 곧장 새
이름을 보여준다. 내보내진 참여자와 보관된 클래스는 거절되고, 검증 규칙은
가입 때(`test_classroom_join.py`)와 같다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from classroom.models import ClassMember, Class

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


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> dict:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


def _rename_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/members/me"


def test_participant_renames_their_own_display_name(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    class_obj = Class.objects.get(id=class_id)
    _join(client, participant["access"], class_obj.join_code, "오타난이름")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "고친이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "고친이름"
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    assert member.display_name == "고친이름"


def test_renaming_is_scoped_per_class(client, db):
    """같은 사람이 두 클래스에 다른 이름으로 들어가 있으면, 한 클래스에서의
    변경이 다른 클래스의 이름에 번지지 않는다."""

    instructor = _login(client, uid="instructor-1")
    class_a = _create_class(client, instructor["access"], name="A반")
    class_b = _create_class(client, instructor["access"], name="B반")
    participant = _login(client, uid="participant-1")

    _join(client, participant["access"], Class.objects.get(id=class_a).join_code, "A반이름")
    _join(client, participant["access"], Class.objects.get(id=class_b).join_code, "B반이름")

    response = client.patch(
        _rename_url(class_a),
        data={"display_name": "A반새이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert response.status_code == 200

    member_a = ClassMember.objects.get(
        classroom_id=class_a, user__username__contains="participant-1"
    )
    member_b = ClassMember.objects.get(
        classroom_id=class_b, user__username__contains="participant-1"
    )
    assert member_a.display_name == "A반새이름"
    assert member_b.display_name == "B반이름"


def test_display_name_change_appears_in_the_roster(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "옛이름")

    client.patch(
        _rename_url(class_id),
        data={"display_name": "새이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    roster = client.get(f"{CLASSES_URL}/{class_id}/members", **_auth_header(instructor["access"]))
    names = [m["display_name"] for m in roster.json()]
    assert "새이름" in names
    assert "옛이름" not in names


def test_display_name_change_appears_in_past_submissions(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    ).json()
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}/checklist-items",
        data={"label": "테스트 통과", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert opened.status_code == 200

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "옛이름")
    submitted = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}/submissions",
        data={"value": "https://github.com/laurio/example"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert submitted.status_code == 201

    client.patch(
        _rename_url(class_id),
        data={"display_name": "새이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    submissions = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}/submissions",
        **_auth_header(instructor["access"]),
    ).json()
    assert len(submissions) == 1
    assert submissions[0]["member_display_name"] == "새이름"


def test_a_non_member_cannot_rename_in_this_class(client, db):
    """이 클래스에 가입하지 않은 다른 참여자는 여기 닿지 못한다 — 남의
    클래스의 제출/문제 엔드포인트와 같은 존재-숨김 규칙이다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    stranger = _login(client, uid="stranger-1")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "몰래바꾸기"},
        content_type="application/json",
        **_auth_header(stranger["access"]),
    )

    assert response.status_code == 404


def test_instructor_who_has_not_joined_cannot_rename(client, db):
    """강사는 참여자의 이름을 바꿀 길이 없다 — 자기 클래스에 참여자로
    가입한 적이 없으면 강사 본인도 여기 닿지 못한다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "강사가바꾼이름"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 404


def test_anonymous_cannot_rename(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "누구세요"},
        content_type="application/json",
    )

    assert response.status_code == 401


def test_expelled_member_cannot_rename(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "옛이름")
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    client.post(
        f"{CLASSES_URL}/{class_id}/members/{member.id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "다시이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 403
    member.refresh_from_db()
    assert member.display_name == "옛이름"


def test_archived_class_member_cannot_rename(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "옛이름")
    archive = client.post(
        f"{CLASSES_URL}/{class_id}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert archive.status_code == 200

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "새이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 403
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    assert member.display_name == "옛이름"


def test_blank_display_name_is_rejected(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "옛이름")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": ""},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 422
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    assert member.display_name == "옛이름"


def test_overlong_display_name_is_rejected(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "옛이름")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "가" * 101},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 422
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    assert member.display_name == "옛이름"


def test_my_problems_response_includes_current_display_name_and_flags(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], Class.objects.get(id=class_id).join_code, "지금이름")

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/mine", **_auth_header(participant["access"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["member_display_name"] == "지금이름"
    assert body["member_expelled"] is False
    assert body["archived"] is False
    assert body["problems"] == []
