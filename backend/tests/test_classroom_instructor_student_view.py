"""강사가 학생 화면을 그 주소로 연다 — 제출은 잠긴 채로 (#429, 부모 #428).

핵심 대상: `GET .../mine`이 그 클래스의 강사를 참여자와 달리 대한다 — 상태와
무관하게 문제를 주고, 시도 목록은 언제나 빈 배열이며, 「강사로 보고 있다」를
응답의 한 칸으로 말한다. 참여자에 대한 규칙은 한 글자도 바뀌지 않는다(초안·
낸 적 없는 숨긴 문제는 여전히 404). 강사가 그 화면에서 제출을 시도해도
거절된다 — 화면 잠금이 유일한 문이 아니다.
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


def _create_class(client, access: str, name: str = "웹 스터디") -> dict:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def _create_draft_problem(client, access: str, class_id: int) -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_required_item(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "통과 조건", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201


def _open_problem(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _hide_problem(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/hide",
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _mine_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine"


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> dict:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


# --- 강사가 학생 화면을 연다 — 세 상태 전부 -----------------------------------


def test_instructor_can_open_draft_problem_and_sees_empty_submissions(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["submit_blocked_reason"] == "viewing_as_instructor"
    assert body["instructor_problem_status"] == "draft"
    assert body["submissions"] == []


def test_instructor_can_open_open_problem_and_sees_empty_submissions(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["submit_blocked_reason"] == "viewing_as_instructor"
    assert body["instructor_problem_status"] == "open"
    assert body["submissions"] == []


def test_instructor_can_open_hidden_problem_and_sees_empty_submissions(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    _hide_problem(client, instructor["access"], created["id"], problem_id)

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["submit_blocked_reason"] == "viewing_as_instructor"
    assert body["instructor_problem_status"] == "hidden"
    assert body["submissions"] == []


def test_instructors_own_attempts_never_appear_in_the_instructor_view(client, db):
    """강사가 가입 링크로 자기 클래스 참여자가 되어 있어도 이 주소는 언제나
    강사 시점이다 — 명단·달성률·토큰 예산에 강사가 섞이지 않는다는 것을
    시도 목록이 비어 있음으로 확인한다(#429 Implementation Decisions)."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    _join(client, instructor["access"], created["join_code"], display_name="강사 본인")
    client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["submit_blocked_reason"] == "viewing_as_instructor"
    assert body["submissions"] == []


# --- 참여자 규칙은 그대로다 ----------------------------------------------------


def test_participant_still_gets_404_for_draft_problem(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(participant["access"]))
    assert response.status_code == 404


def test_participant_still_gets_404_for_hidden_problem_never_submitted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    _hide_problem(client, instructor["access"], created["id"], problem_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(participant["access"]))
    assert response.status_code == 404


def test_participant_view_still_reports_not_viewing_as_instructor(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(participant["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["submit_blocked_reason"] is None
    assert body["instructor_problem_status"] is None


# --- 남의 클래스 강사는 404다 --------------------------------------------------


def test_other_instructors_view_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    created = _create_class(client, a["access"], name="A의 클래스")
    problem_id = _create_draft_problem(client, a["access"], created["id"])

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(b["access"]))
    assert response.status_code == 404


# --- 강사의 제출은 백엔드가 거절한다 --------------------------------------------


def test_instructor_submission_attempt_is_rejected(client, db):
    """강사가 「학생 화면으로」를 열어 제출 버튼을 눌러도(화면 잠금을 우회해도)
    백엔드가 거절한다 — 강사는 `ClassMember`가 아니므로 지금과 같은 404다
    (#429 Implementation Decisions "화면만 잠그면 그것이 유일한 문이 된다")."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 404
