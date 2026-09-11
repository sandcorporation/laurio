"""새 문제 화면의 「이미 있는 문제로 시작하기」, 「내 다른 클래스에서」 탭
(#326, CONTEXT.md 「강의실」).

핵심 대상: 강사가 지금 클래스를 뺀 자기 다른 클래스의 문제 목록을 훑어볼 수
있다 — 대상 클래스는 묻지 않는다(지금 있는 클래스가 대상이다). 목록에는
제목·설명·제출 형식·체크리스트가 실려 고르기 전에 미리 볼 수 있다. 실제로
가져오는 것은 기존 #292의 복사 엔드포인트를 방향만 반대로(받는 쪽에서) 부르는
것이라 `test_classroom_problem_copy.py`가 그 계약을 이미 고정하고 있다.
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


def _create_problem(
    client, access: str, class_id: int, title: str = "1주차", submission_format: str = "source"
) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_format": submission_format},
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


def _list_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/from-other-classes"


def test_lists_problems_from_other_own_classes(client, db):
    pair = _login(client)
    class_a = _create_class(client, pair["access"], "1기")
    class_b = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], class_b, "fetch로 목록 그리기")
    _add_item(client, pair["access"], class_b, problem_id, "테스트가 통과한다", True)
    _add_item(client, pair["access"], class_b, problem_id, "README가 있다", False)

    response = client.get(_list_url(class_a), **_auth_header(pair["access"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["id"] == problem_id
    assert row["classroom_id"] == class_b
    assert row["classroom_name"] == "2기"
    assert row["title"] == "fetch로 목록 그리기"
    assert row["description"] == "설명"
    assert row["submission_format"] == "source"
    labels_and_required = [(i["label"], i["required"]) for i in row["checklist_items"]]
    assert labels_and_required == [("테스트가 통과한다", True), ("README가 있다", False)]


def test_excludes_problems_from_the_current_class(client, db):
    pair = _login(client)
    class_a = _create_class(client, pair["access"], "1기")
    class_b = _create_class(client, pair["access"], "2기")
    _create_problem(client, pair["access"], class_a, "이 클래스의 문제")
    other_id = _create_problem(client, pair["access"], class_b, "다른 클래스의 문제")

    response = client.get(_list_url(class_a), **_auth_header(pair["access"]))
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [other_id]


def test_excludes_other_instructors_problems(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_a = _create_class(client, a["access"], "A의 클래스")
    class_b = _create_class(client, b["access"], "B의 클래스")
    _create_problem(client, b["access"], class_b, "B의 문제")

    response = client.get(_list_url(class_a), **_auth_header(a["access"]))
    assert response.status_code == 200
    assert response.json() == []


def test_lookup_is_404_for_someone_elses_class(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_b = _create_class(client, b["access"], "B의 클래스")

    response = client.get(_list_url(class_b), **_auth_header(a["access"]))
    assert response.status_code == 404


def test_includes_problems_from_an_archived_source_class(client, db):
    """원본이 보관돼도 읽기는 남는다(#294와 같은 원칙) — 보관은 그 클래스에
    새 내용이 느는 길만 막지, 거기 있던 문제를 다른 곳으로 가져가는 것과는
    무관하다."""

    pair = _login(client)
    class_a = _create_class(client, pair["access"], "1기")
    class_b = _create_class(client, pair["access"], "지난 기수")
    problem_id = _create_problem(client, pair["access"], class_b, "지난 기수 문제")

    archived = client.post(
        f"{CLASSES_URL}/{class_b}/archive",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert archived.status_code == 200

    response = client.get(_list_url(class_a), **_auth_header(pair["access"]))
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [problem_id]


def test_picked_problem_is_imported_via_the_existing_copy_endpoint(client, db):
    """가져오기 자체는 새 엔드포인트가 아니라 #292의 복사를 그대로 쓴다 —
    여기서는 그 배선이 실제로 이어지는지만 한 번 확인한다(세부 계약은
    test_classroom_problem_copy.py가 고정한다)."""

    pair = _login(client)
    class_a = _create_class(client, pair["access"], "1기")
    class_b = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], class_b, "가져올 문제")
    _add_item(client, pair["access"], class_b, problem_id, "필수 항목", True)

    listing = client.get(_list_url(class_a), **_auth_header(pair["access"]))
    row = listing.json()[0]

    imported = client.post(
        f"{CLASSES_URL}/{row['classroom_id']}/problems/{row['id']}/copy",
        data={"target_class_id": class_a},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert imported.status_code == 201
    body = imported.json()
    assert body["classroom_id"] == class_a
    assert body["title"] == "가져올 문제"
    assert body["status"] == "draft"
    assert [i["label"] for i in body["checklist_items"]] == ["필수 항목"]
