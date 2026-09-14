"""문제 만들기 화면에 체크리스트를 합친다 (#315, 부모 #312, CONTEXT.md 「강의실」).

핵심 대상: 만들기 요청 하나가 문제와 체크리스트 항목을 함께 만든다 — 항목이
잘못되면 문제도 생기지 않는다. 항목이 준비됐으면(필수 항목이 하나 이상) 그
자리에서 바로 열 수 있다 — 「필수 항목이 하나도 없으면 열 수 없다」는 백엔드
규칙은 열기 엔드포인트(#283)와 똑같이 여기서도 지켜진다.
"""

from __future__ import annotations

from classroom.models import ChecklistItem, Problem

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


def test_creating_a_problem_with_checklist_items_creates_both_in_one_request(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차 — Todo API",
            "submission_formats": ["source"],
            "checklist_items": [
                {"label": "테스트가 통과한다", "required": True},
                {"label": "README가 있다", "required": False},
            ],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == Problem.Status.DRAFT
    labels_and_required = [(i["label"], i["required"]) for i in body["checklist_items"]]
    assert labels_and_required == [("테스트가 통과한다", True), ("README가 있다", False)]

    stored = Problem.objects.get(id=body["id"])
    assert list(stored.checklist_items.values_list("label", "required")) == [
        ("테스트가 통과한다", True),
        ("README가 있다", False),
    ]


def test_creating_a_problem_without_checklist_items_still_creates_an_empty_draft(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == Problem.Status.DRAFT
    assert body["checklist_items"] == []


def test_create_and_open_opens_immediately_when_a_required_item_is_included(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "테스트가 통과한다", "required": True}],
            "open": True,
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == Problem.Status.OPEN

    stored = Problem.objects.get(id=body["id"])
    assert stored.status == Problem.Status.OPEN


def test_create_and_open_is_rejected_without_a_required_item_and_creates_nothing(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "README가 있다", "required": False}],
            "open": True,
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 400
    assert not Problem.objects.filter(classroom_id=class_id, title="1주차").exists()
    assert not ChecklistItem.objects.filter(label="README가 있다").exists()


def test_create_and_open_is_rejected_with_no_checklist_items_at_all(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"], "open": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 400
    assert not Problem.objects.filter(classroom_id=class_id, title="1주차").exists()


def test_create_without_open_flag_defaults_to_draft_even_with_a_required_item(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "테스트가 통과한다", "required": True}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    assert response.json()["status"] == Problem.Status.DRAFT


def test_an_invalid_checklist_item_rejects_the_whole_request_and_creates_no_problem(client, db):
    """빈 라벨은 `ChecklistItemIn`의 `min_length=1`에 걸려 django-ninja가 핸들러에
    닿기 전에 422를 낸다 — 문제도 항목도 생기지 않는다."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "", "required": True}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422
    assert not Problem.objects.filter(classroom_id=class_id, title="1주차").exists()


def test_a_draft_created_with_a_required_item_can_still_be_opened_later(client, db):
    """항목 없이(또는 열지 않고) 만들면 지금처럼 초안으로 생기고, 상세에서
    이어 붙이거나 나중에 열 수 있다는 것이 그대로 동작한다는 회귀 방지."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "테스트가 통과한다", "required": True}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem_id = created.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open", **_auth_header(pair["access"])
    )
    assert opened.status_code == 200
    assert opened.json()["status"] == Problem.Status.OPEN
