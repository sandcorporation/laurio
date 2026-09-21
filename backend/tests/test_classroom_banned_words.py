"""클래스 참여자 이름에 금칙어(사칭·욕설)가 있으면 거절된다 (spec #474, #475).

핵심 대상: 「이 클래스에서 불릴 이름」은 가입할 때(`POST /join/{code}`)와
나중에 스스로 바꿀 때(`PATCH .../members/me`) 둘 다 같은 검사를 받는다 —
가입할 때만 막으면 그 뒤에 이름을 사칭으로 바꾸면 그만이기 때문이다. 이
필드에는 사칭·욕설 두 목록이 모두 걸린다. 거절 응답의 `detail`은 걸린
낱말이 아니라 종류만 말하는 문자열이다.

HTTP만 친다(이 저장소의 유일한 백엔드 시임) — `core.banned_words`의 판정
함수를 직접 부르지 않는다.
"""

from __future__ import annotations

from classroom.models import Class, ClassMember

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


def _join_url(code: str) -> str:
    return f"/api/classroom/join/{code}"


def _rename_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/members/me"


def _join(client, access: str, join_code: str, display_name: str):
    return client.post(
        _join_url(join_code),
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )


# --- 가입 -----------------------------------------------------------------


def test_impersonation_name_is_rejected_on_join(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")

    response = _join(client, participant["access"], class_obj.join_code, "관리자")

    assert response.status_code == 422
    assert not ClassMember.objects.filter(
        classroom_id=class_id, user__username__contains="participant-1"
    ).exists()


def test_impersonation_name_is_rejected_regardless_of_case(client, db):
    """영문 사칭 낱말은 대소문자를 가리지 않고 걸린다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")

    response = _join(client, participant["access"], class_obj.join_code, "Class ADMIN")

    assert response.status_code == 422


def test_profanity_name_is_rejected_on_join(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")

    response = _join(client, participant["access"], class_obj.join_code, "씨발놈")

    assert response.status_code == 422


def test_normal_name_passes_on_join(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")

    response = _join(client, participant["access"], class_obj.join_code, "김개발")

    assert response.status_code == 200
    assert response.json()["display_name"] == "김개발"


def test_circumvented_spelling_is_not_rejected(client, db):
    """우회 표기는 일부러 잡지 않는다 — spec #474 의 결정 그대로다. 「관」과
    「리」와 「자」 사이에 구분 기호를 넣으면 사칭 효과 자체가 없으므로
    막을 필요가 없고, 막으려 들면 정상 문장의 오탐이 늘어난다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")

    response = _join(client, participant["access"], class_obj.join_code, "관.리.자")

    assert response.status_code == 200


# --- 거절 응답의 모양 --------------------------------------------------------


def test_rejection_detail_is_a_string_and_does_not_echo_the_banned_word(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")

    response = _join(client, participant["access"], class_obj.join_code, "운영자")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "운영자" not in detail


def test_rejection_message_says_which_kind_was_triggered(client, db):
    """「사용할 수 없습니다」만으로 끝나지 않는다 — 사칭과 욕설은 다른
    문구를 받는다, 무엇을 고쳐야 할지 알 수 있어야 하기 때문이다(spec #474
    User Story 2)."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)

    impersonator = _login(client, uid="participant-1")
    impersonation_detail = _join(
        client, impersonator["access"], class_obj.join_code, "관리자"
    ).json()["detail"]

    curser = _login(client, uid="participant-2")
    profanity_detail = _join(client, curser["access"], class_obj.join_code, "씨발").json()[
        "detail"
    ]

    assert impersonation_detail != profanity_detail
    assert "운영진" in impersonation_detail
    assert "욕설" in profanity_detail


# --- 바꾸기 -----------------------------------------------------------------


def test_impersonation_name_is_rejected_when_renaming(client, db):
    """가입할 때만 막으면 그 뒤에 바꾸면 그만이다 — 바꿀 때도 막힌다는
    것이 spec #474 User Story 3 이다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], class_obj.join_code, "정상이름")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "운영자"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 422
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    assert member.display_name == "정상이름"


def test_profanity_name_is_rejected_when_renaming(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], class_obj.join_code, "정상이름")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "병신"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 422
    member = ClassMember.objects.get(
        classroom_id=class_id, user__username__contains="participant-1"
    )
    assert member.display_name == "정상이름"


def test_normal_name_change_still_works(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], class_obj.join_code, "옛이름")

    response = client.patch(
        _rename_url(class_id),
        data={"display_name": "새이름"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "새이름"


# --- 강사 이름도 참여자다 ------------------------------------------------------


def test_instructor_who_joins_their_own_class_is_also_checked(client, db):
    """강사도 참가자이지 운영진이 아니다(spec #474 User Story 4) — 강사가
    자기 클래스에 참여자로 들어올 때(CONTEXT.md 「Class」) 쓰는 이름도
    ClassMember.display_name 이라 같은 검사를 받는다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    class_obj = Class.objects.get(id=class_id)

    response = _join(client, instructor["access"], class_obj.join_code, "관리자")

    assert response.status_code == 422
