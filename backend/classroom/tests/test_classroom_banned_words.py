"""강의실에서 사람 이름으로 불리는 자리에 금칙어(사칭·욕설)가 있으면
거절된다 (spec #474, #475, #477).

핵심 대상은 넷이다 — 클래스 참여자가 그 클래스에서 불릴 이름(가입할 때
`POST /join/{code}`와 나중에 스스로 바꿀 때 `PATCH .../members/me`, #475),
클래스가 들고 있는 강사 이름(만들 때 `POST /classes`와 설정에서 고칠 때
`PATCH /classes/{id}`, #477), 문제 템플릿·클래스 템플릿 공개자 이름(둘 다
`POST .../publish-template`, #477). 넷 다 만들 때만 막으면 그 뒤에 사칭
이름으로 바꾸면 그만이므로 바꾸는 자리도 같은 검사를 받는다. 이 필드들에는
사칭·욕설 두 목록이 모두 걸린다. 거절 응답의 `detail`은 걸린 낱말이 아니라
종류만 말하는 문자열이다.

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


def _create_class(client, access: str, name: str = "웹 스터디", instructor_display_name: str = "강사") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": instructor_display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_class_response(client, access: str, instructor_display_name: str, name: str = "웹 스터디"):
    return client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": instructor_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _publish_problem_template(client, access: str, class_id: int, problem_id: int, publisher_display_name: str):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


def _publish_class_template(client, access: str, class_id: int, publisher_display_name: str):
    return client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


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


# --- 클래스가 들고 있는 강사 이름(#477) ----------------------------------------


def test_impersonation_instructor_name_is_rejected_on_create(client, db):
    """이 이름은 로그인하지 않은 사람도 보는 가입 미리보기에 뜬다 — 노출이
    가장 큰 자리다(spec #474, #477)."""

    instructor = _login(client, uid="instructor-1")

    response = _create_class_response(client, instructor["access"], "관리자")

    assert response.status_code == 422
    assert not Class.objects.filter(instructor_id__isnull=False, instructor_display_name="관리자").exists()


def test_profanity_instructor_name_is_rejected_on_create(client, db):
    instructor = _login(client, uid="instructor-1")

    response = _create_class_response(client, instructor["access"], "씨발")

    assert response.status_code == 422


def test_normal_instructor_name_passes_on_create(client, db):
    instructor = _login(client, uid="instructor-1")

    response = _create_class_response(client, instructor["access"], "김강사")

    assert response.status_code == 201
    assert response.json()["instructor_display_name"] == "김강사"


def test_impersonation_instructor_name_is_rejected_when_changing_in_settings(client, db):
    """만들 때만 막으면 그 뒤에 사칭 이름으로 바꾸면 그만이다 — 참여자
    이름과 같은 이유(spec #474 User Story 3)."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"], instructor_display_name="정상강사")

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"instructor_display_name": "운영자"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 422
    class_obj = Class.objects.get(id=class_id)
    assert class_obj.instructor_display_name == "정상강사"


def test_profanity_instructor_name_is_rejected_when_changing_in_settings(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"], instructor_display_name="정상강사")

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"instructor_display_name": "병신"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 422
    class_obj = Class.objects.get(id=class_id)
    assert class_obj.instructor_display_name == "정상강사"


def test_normal_instructor_name_change_still_works_in_settings(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"], instructor_display_name="옛강사")

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"instructor_display_name": "새강사"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 200
    assert response.json()["instructor_display_name"] == "새강사"


def test_impersonating_instructor_name_never_reaches_the_unauthenticated_join_preview(client, db):
    """인증 없이 열리는 가입 미리보기에 사칭 강사 이름이 새로 생길 수
    없다(spec #474, #477 AC) — 만드는 시점에 거절되므로 저장되지 않고,
    그래서 미리보기도 절대 사칭 이름을 돌려주지 않는다."""

    instructor = _login(client, uid="instructor-1")
    rejected = _create_class_response(client, instructor["access"], "운영자")
    assert rejected.status_code == 422

    normal_class_id = _create_class(client, instructor["access"], instructor_display_name="정상강사")
    class_obj = Class.objects.get(id=normal_class_id)

    preview = client.get(f"/api/classroom/join/{class_obj.join_code}")

    assert preview.status_code == 200
    assert preview.json()["instructor_display_name"] == "정상강사"


# --- 템플릿 공개자 이름(#477) --------------------------------------------------


def test_impersonation_publisher_name_is_rejected_on_problem_template_publish(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], class_id)

    response = _publish_problem_template(client, instructor["access"], class_id, problem_id, "운영자")

    assert response.status_code == 422
    from classroom.models import ProblemTemplate

    assert not ProblemTemplate.objects.filter(source_problem_id=problem_id).exists()


def test_profanity_publisher_name_is_rejected_on_problem_template_publish(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], class_id)

    response = _publish_problem_template(client, instructor["access"], class_id, problem_id, "씨발")

    assert response.status_code == 422


def test_normal_publisher_name_passes_on_problem_template_publish(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], class_id)

    response = _publish_problem_template(client, instructor["access"], class_id, problem_id, "김강사")

    assert response.status_code == 201
    assert response.json()["publisher_display_name"] == "김강사"


def test_impersonation_publisher_name_is_rejected_on_class_template_publish(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])

    response = _publish_class_template(client, instructor["access"], class_id, "관리자")

    assert response.status_code == 422
    from classroom.models import ClassTemplate

    assert not ClassTemplate.objects.filter(source_class_id=class_id).exists()


def test_profanity_publisher_name_is_rejected_on_class_template_publish(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])

    response = _publish_class_template(client, instructor["access"], class_id, "병신")

    assert response.status_code == 422


def test_normal_publisher_name_passes_on_class_template_publish(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])

    response = _publish_class_template(client, instructor["access"], class_id, "김강사")

    assert response.status_code == 201
    assert response.json()["publisher_display_name"] == "김강사"
