"""문제를 다른 클래스로 복사한다 (#292, CONTEXT.md 「강의실」).

핵심 대상: 강사가 자기 문제를 자기 다른 클래스로 복사한다. 체크리스트와
채점 설정(문제 자신의 `model`)이 함께 오고, 제출물·시도·Score는 애초에
이 티켓 범위에 없다(#286/#287이 아직 열려 있다). 복사본은 원본 상태와
무관하게 항상 초안으로 들어오고, 원본과 독립이다. 남의 클래스로는 복사할
수 없다 — 자기 클래스가 아닌 문제도 마찬가지다.
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
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(
    client, access: str, class_id: int, title: str = "1주차", submission_format: str = "source"
) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_formats": [submission_format]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _add_item(client, access: str, class_id: int, problem_id: int, label: str, required: bool = True):
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": label, "required": required},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _copy_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/copy"


def test_instructor_copies_a_problem_to_another_own_class(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], source_class, "1주차 — Todo API")
    _add_item(client, pair["access"], source_class, problem_id, "테스트가 통과한다", True)
    _add_item(client, pair["access"], source_class, problem_id, "README가 있다", False)

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["classroom_id"] == target_class
    assert body["title"] == "1주차 — Todo API"
    assert body["description"] == "설명"
    assert body["submission_formats"] == ["source"]
    labels_and_required = [(i["label"], i["required"]) for i in body["checklist_items"]]
    assert labels_and_required == [("테스트가 통과한다", True), ("README가 있다", False)]


def test_copy_preserves_a_problem_open_to_both_formats(client, db):
    """#374 AC — 문제 복사가 형식 목록을 보존한다(둘 다 열린 문제도 뭉개지지
    않는다)."""

    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    created = client.post(
        f"{CLASSES_URL}/{source_class}/problems",
        data={"title": "형식 둘", "submission_formats": ["repository", "source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    assert response.json()["submission_formats"] == ["source", "repository"]


def test_copy_always_lands_as_a_draft_even_if_the_original_is_open(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], source_class)
    _add_item(client, pair["access"], source_class, problem_id, "테스트가 통과한다", True)
    opened = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}/open", **_auth_header(pair["access"])
    )
    assert opened.status_code == 200
    assert opened.json()["status"] == Problem.Status.OPEN

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    assert response.json()["status"] == Problem.Status.DRAFT


def test_copy_carries_its_own_scoring_model_override(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], source_class)
    client.patch(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}",
        data={"model": "gpt-4.1-mini"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    assert response.json()["model"] == "gpt-4.1-mini"


def test_copy_is_independent_from_the_original(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], source_class)
    item_id = _add_item(client, pair["access"], source_class, problem_id, "테스트가 통과한다", True)

    copied = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    copy_id = copied.json()["id"]
    copy_item_id = copied.json()["checklist_items"][0]["id"]
    assert copy_id != problem_id
    assert copy_item_id != item_id

    client.patch(
        f"{CLASSES_URL}/{target_class}/problems/{copy_id}/checklist-items/{copy_item_id}",
        data={"label": "고친 항목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    original = client.get(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}", **_auth_header(pair["access"])
    )
    assert original.json()["checklist_items"][0]["label"] == "테스트가 통과한다"


def test_cannot_copy_into_someone_elses_class(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    source_class = _create_class(client, a["access"])
    other_class = _create_class(client, b["access"])
    problem_id = _create_problem(client, a["access"], source_class)

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": other_class},
        content_type="application/json",
        **_auth_header(a["access"]),
    )
    assert response.status_code == 404


def test_cannot_copy_someone_elses_problem(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    source_class = _create_class(client, a["access"])
    own_class = _create_class(client, b["access"])
    problem_id = _create_problem(client, a["access"], source_class)

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": own_class},
        content_type="application/json",
        **_auth_header(b["access"]),
    )
    assert response.status_code == 404


def test_copying_to_a_nonexistent_class_is_404(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], source_class)

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": 999999},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 404


def test_cannot_copy_into_an_archived_class(client, db):
    """#326 AC "보관된 클래스에서는 가져올 수 없다" — 대상 클래스가
    보관됐으면 복사(어느 방향에서 부르든 같은 엔드포인트다)는 403이다."""

    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], source_class)

    archived = client.post(
        f"{CLASSES_URL}/{target_class}/archive",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert archived.status_code == 200

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 403
    assert response.json()["detail"]


def test_copy_appends_after_existing_problems_in_the_target_class(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    existing_id = _create_problem(client, pair["access"], target_class, "이미 있는 문제")
    problem_id = _create_problem(client, pair["access"], source_class, "복사될 문제")

    response = client.post(
        _copy_url(source_class, problem_id),
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    assert response.json()["order"] == 1

    listing = client.get(f"{CLASSES_URL}/{target_class}/problems", **_auth_header(pair["access"]))
    assert [p["id"] for p in listing.json()] == [existing_id, response.json()["id"]]
