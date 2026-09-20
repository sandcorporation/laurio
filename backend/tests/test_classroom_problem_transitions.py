"""Problem 상태 전이 표 — 열린 문제는 필수 항목을 잃지 않는다 (#440, spec
#432, `contests.transitions`(#255)와 같은 모양). 표가 전이를 직접 실행한다
(#468, spec #461).

핵심 대상: 전이 표(초안→열림, 열림→숨김, 숨김→열림)가 허용하지 않는 전이를
거절하고, 열린·숨긴 문제의 마지막 필수 항목 삭제·필수 해제를 422로 막으며,
문제 응답이 지금 가능한 전이와 막힌 이유를 준다. 아래쪽 절(「화면의 이유와
거절의 이유가 같다」)은 그 「막힌 이유」가 실제 거절과 갈리지 않는다는 것을
고정한다 — `classroom.problem_transitions.execute_transition`과
`available_transitions`가 같은 `PROBLEM_TRANSITIONS`를 읽기 때문이다.
"""

from __future__ import annotations

from tests.classroom_scenarios import (
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    login,
)

CLASSES_URL = "/api/classroom/classes"


def _problem_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}"


def _hide(client, access: str, class_id: int, problem_id: int):
    return client.post(
        f"{_problem_url(class_id, problem_id)}/hide",
        content_type="application/json",
        **auth_header(access),
    )


def _reopen(client, access: str, class_id: int, problem_id: int):
    return client.post(
        f"{_problem_url(class_id, problem_id)}/reopen",
        content_type="application/json",
        **auth_header(access),
    )


def _open(client, access: str, class_id: int, problem_id: int):
    return client.post(
        f"{_problem_url(class_id, problem_id)}/open",
        content_type="application/json",
        **auth_header(access),
    )


def _get_problem(client, access: str, class_id: int, problem_id: int):
    return client.get(_problem_url(class_id, problem_id), **auth_header(access))


def _patch_item(client, access: str, class_id: int, problem_id: int, item_id: int, payload: dict):
    return client.patch(
        f"{_problem_url(class_id, problem_id)}/checklist-items/{item_id}",
        data=payload,
        content_type="application/json",
        **auth_header(access),
    )


def _delete_item(client, access: str, class_id: int, problem_id: int, item_id: int):
    return client.delete(
        f"{_problem_url(class_id, problem_id)}/checklist-items/{item_id}",
        **auth_header(access),
    )


# --- 허용되지 않는 전이는 표에 따라 거절된다 --------------------------------


def test_opening_an_already_open_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    response = _open(client, instructor["access"], class_id, problem.id)
    assert response.status_code == 400
    assert response.json()["detail"]


def test_hiding_a_draft_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, open=False)

    response = _hide(client, instructor["access"], class_id, problem.id)
    assert response.status_code == 400


def test_reopening_an_open_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    response = _reopen(client, instructor["access"], class_id, problem.id)
    assert response.status_code == 400


# --- 열린·숨긴 문제는 필수 항목을 잃지 않는다 --------------------------------


def test_unrequiring_the_last_required_item_of_an_open_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    response = _patch_item(
        client, instructor["access"], class_id, problem.id, problem.item_id, {"required": False}
    )
    assert response.status_code == 422
    assert "필수 항목이 하나 이상 있어야" in response.json()["detail"]


def test_deleting_the_last_required_item_of_an_open_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    response = _delete_item(client, instructor["access"], class_id, problem.id, problem.item_id)
    assert response.status_code == 422
    assert "필수 항목이 하나 이상 있어야" in response.json()["detail"]


def test_unrequiring_the_last_required_item_of_a_hidden_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    hidden = _hide(client, instructor["access"], class_id, problem.id)
    assert hidden.status_code == 200

    response = _patch_item(
        client, instructor["access"], class_id, problem.id, problem.item_id, {"required": False}
    )
    assert response.status_code == 422


def test_deleting_the_last_required_item_of_a_hidden_problem_is_rejected(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem.id)

    response = _delete_item(client, instructor["access"], class_id, problem.id, problem.item_id)
    assert response.status_code == 422


def test_unrequiring_the_last_required_item_of_a_draft_problem_is_allowed(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, open=False)

    response = _patch_item(
        client, instructor["access"], class_id, problem.id, problem.item_id, {"required": False}
    )
    assert response.status_code == 200


def test_deleting_the_last_required_item_of_a_draft_problem_is_allowed(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, open=False)

    response = _delete_item(client, instructor["access"], class_id, problem.id, problem.item_id)
    assert response.status_code == 204


def test_unrequiring_a_non_required_item_is_still_allowed_on_an_open_problem(client, db):
    """필수가 아닌 항목을 필수 해제해도(이미 선택이었으니 변화 없음) 통과에
    영향이 없으므로 막지 않는다."""

    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client,
        instructor["access"],
        class_id,
        required_labels=["필수 항목"],
        optional_labels=["선택 항목"],
    )
    optional_item_id = problem.item_ids[1]

    response = _patch_item(
        client, instructor["access"], class_id, problem.id, optional_item_id, {"required": False}
    )
    assert response.status_code == 200


def test_removing_one_of_two_required_items_of_an_open_problem_is_allowed(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client, instructor["access"], class_id, required_labels=["항목1", "항목2"]
    )

    response = _delete_item(client, instructor["access"], class_id, problem.id, problem.item_ids[0])
    assert response.status_code == 204


# --- 문제 응답이 가능한 전이 목록과 막힌 이유를 준다 -------------------------


def test_draft_problem_reports_open_transition(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, open=False)

    body = _get_problem(client, instructor["access"], class_id, problem.id).json()
    transitions = body["available_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["name"] == "open"
    assert transitions[0]["to_state"] == "open"
    assert transitions[0]["blocked_reason"] is None


def test_draft_problem_without_required_item_reports_blocked_open_transition(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "체크리스트 없음", "submission_formats": ["repository"]},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    body = _get_problem(client, instructor["access"], class_id, problem_id).json()
    transitions = body["available_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["name"] == "open"
    assert transitions[0]["blocked_reason"] == "no_required_item"


def test_open_problem_reports_hide_transition(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    body = _get_problem(client, instructor["access"], class_id, problem.id).json()
    transitions = body["available_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["name"] == "hide"
    assert transitions[0]["to_state"] == "hidden"
    assert transitions[0]["blocked_reason"] is None


def test_hidden_problem_reports_reopen_transition(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem.id)

    body = _get_problem(client, instructor["access"], class_id, problem.id).json()
    transitions = body["available_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["name"] == "reopen"
    assert transitions[0]["to_state"] == "open"
    assert transitions[0]["blocked_reason"] is None


def test_archived_class_reports_blocked_transition_regardless_of_status(client, db):
    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    body = _get_problem(client, instructor["access"], class_id, problem.id).json()
    transitions = body["available_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["name"] == "hide"
    assert transitions[0]["blocked_reason"] == "archived"


# --- 화면의 이유와 거절의 이유가 같다 (#468 AC) -------------------------------
#
# `available_transitions`(GET, 화면이 미리 읽는 자리)가 말하는 blocked_reason과
# 실제 전이 호출(POST)의 결과가 갈리지 않는다는 것을 고정한다 — 둘 다
# `classroom.problem_transitions.PROBLEM_TRANSITIONS` 하나를 읽으므로 갈릴 수
# 없어야 한다.


def test_transition_reported_as_open_actually_succeeds(client, db):
    """`blocked_reason`이 `None`이면(「열 수 있다」) 실제로 그 전이가
    성공하고, 문제의 새 상태가 GET이 말한 `to_state`와 같다."""

    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, open=False)

    reported = _get_problem(client, instructor["access"], class_id, problem.id).json()
    transition = reported["available_transitions"][0]
    assert transition["blocked_reason"] is None

    response = _open(client, instructor["access"], class_id, problem.id)
    assert response.status_code == 200
    assert response.json()["status"] == transition["to_state"]


def test_transition_reported_as_blocked_by_no_required_item_is_rejected_for_the_same_reason(
    client, db
):
    """`blocked_reason`이 "no_required_item"이면 실제 호출도 그 이유(필수
    항목 없음)로 거절된다 — `NO_REQUIRED_ITEM_MESSAGE` 문구는
    `create_problem`의 「바로 연다」와 같은 자리(`problem_transitions.
    NO_REQUIRED_ITEM_MESSAGE`)에서 온다."""

    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "체크리스트 없음", "submission_formats": ["repository"]},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    reported = _get_problem(client, instructor["access"], class_id, problem_id).json()
    transition = reported["available_transitions"][0]
    assert transition["blocked_reason"] == "no_required_item"

    response = _open(client, instructor["access"], class_id, problem_id)
    assert response.status_code == 400
    assert response.json()["detail"] == "필수 항목이 하나도 없는 문제는 열 수 없습니다."


def test_transition_reported_as_blocked_by_archived_is_rejected_for_the_same_reason(client, db):
    """`blocked_reason`이 "archived"면 실제 호출도 보관 때문에 거절된다 —
    다만 그 거절은 `execute_transition`이 아니라 라우트 첫 줄의 강사 범위
    (`instructor_scope.problem_scope(..., write=True)`)에서 먼저 난다(403).
    `execute_transition` 자신은 보관을 모른다(모듈 docstring)."""

    instructor = login(client)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    reported = _get_problem(client, instructor["access"], class_id, problem.id).json()
    transition = reported["available_transitions"][0]
    assert transition["blocked_reason"] == "archived"

    response = _hide(client, instructor["access"], class_id, problem.id)
    assert response.status_code == 403
