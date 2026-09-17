"""강사가 학생 화면을 그 주소로 연다 (#429, 부모 #428; 2026-09-17 개정).

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
    # 초안 상태에서도 강사는 낼 수 있다(2026-09-17) — 잠금은 보관뿐이다.
    assert body["submit_blocked_reason"] is None
    assert body["viewing_as_instructor"] is True
    assert body["instructor_problem_status"] == "draft"
    assert body["submissions"] == []


def test_instructor_opening_an_open_problem_can_submit(client, db):
    """열린 문제에서는 잠금이 풀린다(2026-09-17) — 「강사가 보는 중」은 남는다."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["submit_blocked_reason"] is None
    assert body["viewing_as_instructor"] is True
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
    # 숨김 상태에서도 강사는 낼 수 있다(2026-09-17) — 잠금은 보관뿐이다.
    assert body["submit_blocked_reason"] is None
    assert body["viewing_as_instructor"] is True
    assert body["instructor_problem_status"] == "hidden"
    assert body["submissions"] == []


def test_instructors_own_attempts_appear_in_the_instructor_view(client, db):
    """강사 자신의 시도는 이 화면에 보인다(2026-09-17 개정) — 남의 시도는
    여전히 이 질의에 없다(`member=member`). 명단·달성률·토큰 예산이 강사를
    세지 않는 것은 그대로다(#290)."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    submitted = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert submitted.status_code == 201, submitted.content

    response = client.get(_mine_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["viewing_as_instructor"] is True
    assert body["submit_blocked_reason"] is None
    assert [s["attempt_number"] for s in body["submissions"]] == [1]


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


def test_instructor_can_submit_to_an_open_problem_without_joining(client, db):
    """강사가 가입 링크를 거치지 않고도 열린 문제에 낸다(2026-09-17) — 제출이
    참여자 행을 그 자리에서 만든다. 그 행은 명단에 「강사」로 표시되고 달성률
    집계에서는 빠진다(#290 — 이 파일 밖에서 이미 고정한 규칙)."""

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
    assert response.status_code == 201, response.content

    members = client.get(
        f"{CLASSES_URL}/{created['id']}/members", **_auth_header(instructor["access"])
    )
    assert [m["is_instructor"] for m in members.json()] == [True]


def test_instructor_can_submit_to_a_draft_problem(client, db):
    """초안에도 낸다(2026-09-17) — 문제를 만들며 한 번 내 보는 것이 정상
    절차다(#431이 이미 그 전제 위에 서 있다). 참여자에게는 여전히 404다."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 201, response.content

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    blocked = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert blocked.status_code == 404


def test_instructor_can_submit_to_a_hidden_problem(client, db):
    """강사가 거둔 문제에도 강사 자신은 낸다(2026-09-17) — 참여자는 낸 적이
    있어야 문제가 보이고, 그래도 새 제출은 403이다."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    first = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert first.status_code == 201, first.content
    _hide_problem(client, instructor["access"], created["id"], problem_id)

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 201, response.content


def test_a_stranger_still_gets_404_when_submitting(client, db):
    """남의 클래스에는 여전히 낼 수 없다 — 참여자도 강사도 아닌 사람에게는
    문제의 존재 자체를 숨긴다."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_draft_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    stranger = _login(client, uid="stranger-1")

    response = client.post(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(stranger["access"]),
    )
    assert response.status_code == 404
