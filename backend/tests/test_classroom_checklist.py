"""체크리스트 — 필수·선택 항목과 순서 (#283, CONTEXT.md 「강의실」).

핵심 대상: 강사가 항목을 더하고 고치고 지우고 순서를 바꾼다. 각 항목이
필수인지 선택인지 정해진다. 필수 항목이 하나도 없는 문제는 열 수 없다 —
통과가 정의되지 않는다. 참여자도 무엇이 필수인지 볼 수 있어야 하므로
`ProblemOut`이 체크리스트를 함께 싣는다.
"""

from __future__ import annotations

from classroom.models import Problem

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
        data={"name": name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_format": "source"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _items_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items"


def test_instructor_adds_a_required_and_an_optional_item(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    required = client.post(
        _items_url(class_id, problem_id),
        data={"label": "테스트가 통과한다", "required": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert required.status_code == 201
    assert required.json()["required"] is True

    optional = client.post(
        _items_url(class_id, problem_id),
        data={"label": "README가 있다", "required": False},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert optional.status_code == 201
    assert optional.json()["required"] is False

    problem = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"]))
    labels_and_required = [(i["label"], i["required"]) for i in problem.json()["checklist_items"]]
    assert labels_and_required == [("테스트가 통과한다", True), ("README가 있다", False)]


def test_instructor_edits_and_deletes_an_item(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    created = client.post(
        _items_url(class_id, problem_id),
        data={"label": "테스트가 통과한다", "required": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    item_id = created.json()["id"]

    patched = client.patch(
        f"{_items_url(class_id, problem_id)}/{item_id}",
        data={"label": "전체 테스트가 통과한다", "required": False},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["label"] == "전체 테스트가 통과한다"
    assert patched.json()["required"] is False

    deleted = client.delete(f"{_items_url(class_id, problem_id)}/{item_id}", **_auth_header(pair["access"]))
    assert deleted.status_code == 204

    problem = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"]))
    assert problem.json()["checklist_items"] == []


def test_items_are_ordered_and_reorderable(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    ids = []
    for label in ["항목 1", "항목 2", "항목 3"]:
        created = client.post(
            _items_url(class_id, problem_id),
            data={"label": label, "required": True},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )
        ids.append(created.json()["id"])

    reordered = client.post(
        f"{_items_url(class_id, problem_id)}/reorder",
        data={"item_ids": [ids[2], ids[0], ids[1]]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert reordered.status_code == 200
    assert [i["id"] for i in reordered.json()] == [ids[2], ids[0], ids[1]]

    problem = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"]))
    assert [i["id"] for i in problem.json()["checklist_items"]] == [ids[2], ids[0], ids[1]]


def test_a_problem_with_no_required_items_cannot_be_opened(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    client.post(
        _items_url(class_id, problem_id),
        data={"label": "README가 있다", "required": False},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open", **_auth_header(pair["access"])
    )
    assert response.status_code == 400


def test_a_problem_with_no_checklist_items_at_all_cannot_be_opened(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open", **_auth_header(pair["access"])
    )
    assert response.status_code == 400


def test_a_problem_with_at_least_one_required_item_can_be_opened(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    client.post(
        _items_url(class_id, problem_id),
        data={"label": "테스트가 통과한다", "required": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open", **_auth_header(pair["access"])
    )
    assert response.status_code == 200
    assert response.json()["status"] == Problem.Status.OPEN


def test_instructor_can_still_edit_the_checklist_after_opening(client, db):
    """이미 열린 문제도 강사가 언제든 고친다 — 돈이 걸려 있지 않아 "나중에
    낸 사람이 유리해진다"가 성립하지 않는다(CONTEXT.md 「Problem」)."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    created = client.post(
        _items_url(class_id, problem_id),
        data={"label": "테스트가 통과한다", "required": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    item_id = created.json()["id"]
    client.post(f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open", **_auth_header(pair["access"]))

    patched = client.patch(
        f"{_items_url(class_id, problem_id)}/{item_id}",
        data={"label": "더 엄격한 테스트가 통과한다"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert patched.status_code == 200

    added = client.post(
        _items_url(class_id, problem_id),
        data={"label": "새 항목", "required": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert added.status_code == 201

    problem = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"]))
    assert problem.json()["status"] == Problem.Status.OPEN
    assert len(problem.json()["checklist_items"]) == 2
