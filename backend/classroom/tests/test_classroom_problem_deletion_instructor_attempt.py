"""삭제 — 강사 자신만 내본 문제도 지운다, 그 채점을 함께 걷어낸다
(#431, 부모 #428, ADR-0050).

문제를 만들 때 한 번 내보는 것은 정상적인 절차다 — 앞 티켓(#430)까지의
규칙으로는 그 한 번이 문제를 영원히 못 지우게 만든다. 이 티켓은 「강사 자신의
시도만 있는 문제」까지 지울 수 있게 넓히되, 걷어내는 범위를 「그 문제 × 강사
자신」으로 닫는다(ADR-0050) — 참여자의 시도(내보낸 사람 포함)가 있으면 여전히
거절한다.
"""

from __future__ import annotations

from classroom.models import ClassroomScore, Problem

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


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": ["repository"]},
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


def _expel(client, access: str, class_id: int, member_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _delete_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}"


def _score_a_submission(submission_id: int) -> ClassroomScore:
    """채점 스캔을 실제로 돌리지 않고 `ClassroomScore`를 직접 만든다 — 이
    파일이 보는 것은 채점 파이프라인이 아니라 삭제가 그 결과를 지우는가다
    (`seed_demo_classroom`이 데모를 채울 때 쓰는 것과 같은 우회, CLAUDE.md
    「테스트」)."""

    return ClassroomScore.objects.create(
        submission_id=submission_id,
        model_version="test-model",
        prompt="테스트 프롬프트",
        reasoning=[],
    )


# --- 강사 자신의 시도만 있으면 지울 수 있고, 채점도 함께 사라진다 -----------------


def test_problem_with_only_instructors_own_attempt_can_be_deleted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    _join(client, instructor["access"], created["join_code"], display_name="강사 본인")
    submission = _submit(client, instructor["access"], created["id"], problem_id)
    score = _score_a_submission(submission["id"])

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 204
    assert not Problem.objects.filter(id=problem_id).exists()
    assert not ClassroomScore.objects.filter(id=score.id).exists()


def test_deletable_flag_is_true_when_only_the_instructor_attempted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    _join(client, instructor["access"], created["join_code"], display_name="강사 본인")
    submission = _submit(client, instructor["access"], created["id"], problem_id)
    _score_a_submission(submission["id"])

    response = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    assert response.json()["deletable"] is True


# --- 참여자의 시도가 있으면 여전히 거절한다 — 채점도 지워지지 않는다 -------------


def test_problem_with_a_participant_attempt_is_still_rejected_even_with_instructors_own_attempt(
    client, db
):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    _join(client, instructor["access"], created["join_code"], display_name="강사 본인")
    instructor_submission = _submit(client, instructor["access"], created["id"], problem_id)
    instructor_score = _score_a_submission(instructor_submission["id"])

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    _submit(client, participant["access"], created["id"], problem_id)

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 403
    assert Problem.objects.filter(id=problem_id).exists()
    # 강사 자신의 채점도 거절된 삭제와 함께 그대로 남는다 — 걷어내는 시점은
    # 실제 삭제가 허용된 뒤뿐이다.
    assert ClassroomScore.objects.filter(id=instructor_score.id).exists()


def test_deletable_flag_is_false_when_a_participant_also_attempted(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"])
    _submit(client, participant["access"], created["id"], problem_id)

    response = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    assert response.json()["deletable"] is False


# --- 내보낸 참여자의 시도도 「남은 시도」다 — 거절이 그대로다 --------------------


def test_expelled_participants_attempt_still_blocks_deletion(client, db):
    """내보내면 지울 수 있다가 되면 내보내기가 기록을 지우는 우회로가 된다
    (#431 AC, ADR-0050의 경계) — 이 단언이 그것을 막는다."""

    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)

    participant = _login(client, uid="participant-1")
    join_result = _join(client, participant["access"], created["join_code"])
    _submit(client, participant["access"], created["id"], problem_id)

    members = client.get(
        f"{CLASSES_URL}/{created['id']}/members", **_auth_header(instructor["access"])
    ).json()
    member = next(m for m in members if not m["is_instructor"])
    _expel(client, instructor["access"], created["id"], member["id"])

    deletable = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    assert deletable.json()["deletable"] is False

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 403
    assert Problem.objects.filter(id=problem_id).exists()
    assert join_result["class_name"] == created["name"]


# --- 근거 신호는 여전히 실제 삭제 결과와 같은 답을 낸다 --------------------------


def test_deletable_flag_matches_actual_delete_result_for_instructor_only_attempt(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])
    problem_id = _create_problem(client, instructor["access"], created["id"])
    _add_required_item(client, instructor["access"], created["id"], problem_id)
    _open_problem(client, instructor["access"], created["id"], problem_id)
    _join(client, instructor["access"], created["join_code"], display_name="강사 본인")
    submission = _submit(client, instructor["access"], created["id"], problem_id)
    _score_a_submission(submission["id"])

    before = client.get(
        f"{CLASSES_URL}/{created['id']}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    assert before.json()["deletable"] is True

    response = client.delete(_delete_url(created["id"], problem_id), **_auth_header(instructor["access"]))
    assert response.status_code == 204
