"""참여자가 문제 화면에서 채점 지침을 본다 (#388, 부모 #385).

핵심 대상: 참여자용 문제 응답(`GET .../problems/{id}/mine`)에 채점 지침
단계가 실리고, 직접 입력이면 문장도 함께 실린다 — 화면이 그 값으로 체크리스트
가까이 지침을 그린다(화면 쪽은 `classroom/lib/problems/grading-guideline.ts`의
순수 함수와 브라우저 걷기로 확인한다).
"""

from __future__ import annotations

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


def _create_open_problem(client, access: str, class_id: int, **overrides) -> int:
    payload = {
        "title": "1주차",
        "submission_formats": ["repository"],
        "checklist_items": [{"label": "테스트가 있다", "required": True}],
        "open": True,
    }
    payload.update(overrides)
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201, created.content
    return created.json()["id"]


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


def test_the_participant_view_carries_the_default_normal_strictness(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    body = _mine(client, participant["access"], class_id, problem_id)

    assert body["problem"]["grading_strictness"] == "normal"
    assert body["problem"]["grading_guideline_text"] == ""


def test_the_participant_view_carries_a_chosen_strictness(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, grading_strictness="strict")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    body = _mine(client, participant["access"], class_id, problem_id)

    assert body["problem"]["grading_strictness"] == "strict"


def test_the_participant_view_carries_the_instructors_custom_sentence(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    sentence = "함수 이름은 solve 여야 하지만 출력 형식은 자유롭게 판정한다."
    problem_id = _create_open_problem(
        client,
        instructor["access"],
        class_id,
        grading_strictness="custom",
        grading_guideline_text=sentence,
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    body = _mine(client, participant["access"], class_id, problem_id)

    assert body["problem"]["grading_strictness"] == "custom"
    assert body["problem"]["grading_guideline_text"] == sentence
