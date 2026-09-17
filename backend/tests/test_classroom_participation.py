"""참여자는 낼 수 없는 이유를 하나로 본다 — 업로드도 같은 문을 지난다 (#439,
spec #432).

핵심 대상: 참여자 문제 상세의 `submit_blocked_reason`이 보관 → 내보냄 → 숨김
순서로 하나만 오고, 강의실 소스 업로드 presign도 같은 판정을 거쳐 낼 수 없는
사람에게는 발급되지 않는다.
"""

from __future__ import annotations

from tests.classroom_scenarios import (
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    login,
    user_id,
)

CLASSES_URL = "/api/classroom/classes"
UPLOAD_URL = "/api/storage/uploads"


def _mine_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine"


def _expel(client, instructor_access: str, class_id: int, participant_user_id: int) -> None:
    members = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(instructor_access))
    member_id = next(
        m["id"]
        for m in members.json()
        if not m["is_instructor"]
    )
    response = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **auth_header(instructor_access),
    )
    assert response.status_code == 200, response.content


def _source_target_ref(problem_id: int, uid: int) -> str:
    return f"classroom-submission:{problem_id}:{uid}:source"


def _request_upload(client, access: str, target_ref: str):
    return client.post(
        UPLOAD_URL,
        data={"target_ref": target_ref},
        content_type="application/json",
        **auth_header(access),
    )


# --- 우선순위: 보관 → 내보냄 → 숨김 -----------------------------------------


def test_no_blocking_reason_when_everything_is_normal(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])

    response = client.get(_mine_url(class_id, problem.id), **auth_header(participant["access"]))
    assert response.status_code == 200
    assert response.json()["submit_blocked_reason"] is None


def test_hidden_problem_blocks_with_hidden_reason(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **auth_header(participant["access"]),
    )
    hidden = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide",
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert hidden.status_code == 200

    response = client.get(_mine_url(class_id, problem.id), **auth_header(participant["access"]))
    assert response.status_code == 200
    assert response.json()["submit_blocked_reason"] == "hidden"


def test_expelled_wins_over_hidden(client, db):
    """우선순위가 보관 → 내보냄 → 숨김이므로, 내보냄과 숨김이 동시에 참이면
    「내보냄」이 온다(#439 AC)."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **auth_header(participant["access"]),
    )
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide",
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    _expel(client, instructor["access"], class_id, user_id("participant-1"))

    response = client.get(_mine_url(class_id, problem.id), **auth_header(participant["access"]))
    assert response.status_code == 200
    assert response.json()["submit_blocked_reason"] == "expelled"


def test_archived_wins_over_expelled_and_hidden(client, db):
    """셋이 모두 참이어도 「보관」이 가장 근본적인 이유로 온다(#439 AC)."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **auth_header(participant["access"]),
    )
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide",
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    _expel(client, instructor["access"], class_id, user_id("participant-1"))
    archive_class(client, instructor["access"], class_id)

    response = client.get(_mine_url(class_id, problem.id), **auth_header(participant["access"]))
    assert response.status_code == 200
    assert response.json()["submit_blocked_reason"] == "archived"


def test_instructor_viewing_as_student_reports_viewing_as_instructor(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    response = client.get(_mine_url(class_id, problem.id), **auth_header(instructor["access"]))
    assert response.status_code == 200
    assert response.json()["submit_blocked_reason"] == "viewing_as_instructor"


# --- 목록과 상세가 언제나 같다 ------------------------------------------------


def test_my_problem_list_matches_what_can_be_opened(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    open_problem = create_open_problem(client, instructor["access"], class_id, title="열린 문제")
    draft_problem = create_open_problem(
        client, instructor["access"], class_id, title="초안 문제", open=False
    )
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])

    listing = client.get(
        f"{CLASSES_URL}/{class_id}/problems/mine", **auth_header(participant["access"])
    )
    assert listing.status_code == 200
    listed_ids = {p["id"] for p in listing.json()["problems"]}
    assert listed_ids == {open_problem.id}

    opened = client.get(_mine_url(class_id, open_problem.id), **auth_header(participant["access"]))
    assert opened.status_code == 200

    not_opened = client.get(
        _mine_url(class_id, draft_problem.id), **auth_header(participant["access"])
    )
    assert not_opened.status_code == 404


# --- 업로드도 같은 문을 지난다 ------------------------------------------------


def test_a_participant_who_can_submit_gets_an_upload_url(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])

    response = _request_upload(
        client,
        participant["access"],
        _source_target_ref(problem.id, user_id("participant-1")),
    )
    assert response.status_code == 200, response.content


def test_an_expelled_participant_does_not_get_an_upload_url(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    _expel(client, instructor["access"], class_id, user_id("participant-1"))

    response = _request_upload(
        client,
        participant["access"],
        _source_target_ref(problem.id, user_id("participant-1")),
    )
    assert response.status_code == 403


def test_a_participant_cannot_upload_into_an_archived_class(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    archive_class(client, instructor["access"], class_id)

    response = _request_upload(
        client,
        participant["access"],
        _source_target_ref(problem.id, user_id("participant-1")),
    )
    assert response.status_code == 403


def test_a_participant_cannot_upload_to_a_hidden_problem(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/submissions",
        data={"value": "https://github.com/octocat/hello", "submission_format": "repository"},
        content_type="application/json",
        **auth_header(participant["access"]),
    )
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide",
        content_type="application/json",
        **auth_header(instructor["access"]),
    )

    response = _request_upload(
        client,
        participant["access"],
        _source_target_ref(problem.id, user_id("participant-1")),
    )
    assert response.status_code == 403


def test_a_non_member_does_not_get_an_upload_url(client, db):
    """진짜 참여자가 아니면(가입하지 않은 사람, 강사 본인 포함) 판정할 자격이
    없어 거절한다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    outsider = login(client, uid="outsider-1")

    response = _request_upload(
        client,
        outsider["access"],
        _source_target_ref(problem.id, user_id("outsider-1")),
    )
    assert response.status_code == 403
