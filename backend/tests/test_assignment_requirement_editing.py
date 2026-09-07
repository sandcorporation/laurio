"""#217 — 첫 제출 전이면 요구사항 체크리스트를 고친다 (부모 #197, ADR-0028).

`PATCH /api/assignments/{id}`가 `requirements`를 받아 통째 교체한다. 잠금 규칙은
새로 만들지 않는다 — `_get_owned_editable_assignment`(#209)가 이미 지키는 「첫
제출이 문을 닫는다」를 title·description·deadline_at과 똑같이 그대로 탄다.

`PATCH /api/assignments/{id}`를 마운트된 django-ninja API로 친다(CLAUDE.md — HTTP가
유일한 시임).

Prior art: `tests/test_assignments.py`(자격 부여·과제 생성·열기 헬퍼),
`tests/test_assignment_lock_and_reissue.py`(제출 후 잠김 검증 헬퍼).
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import Contest, DeliverableType, Requirement

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
GRANT_URL = "/api/operator/assignment-permissions/grant"
OPERATOR_PW = "operator-pw-asgnreq-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _operator_client(username="root-asgnreq"):
    call_command("create_operator", username, password=OPERATOR_PW, superuser=True)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": OPERATOR_PW},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid, email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _username(client, access: str) -> str:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["username"]


def _user_id(client, access: str) -> int:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["id"]


def _grant_permission(operator_client, *, username, reason="수업 개설 승인"):
    response = operator_client.post(
        GRANT_URL,
        data={"username": username, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


def _sponsor_with_permission(client, root, uid):
    pair = _login(client, uid)
    username = _username(client, pair["access"])
    _grant_permission(root, username=username)
    return pair


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _create_and_open_assignment(client, access, *, deliverable_type_ids, title="파이썬 기초 과제"):
    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": title,
            "deliverable_type_ids": deliverable_type_ids,
            "description": "1주차 과제",
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200, opened.content
    return assignment_id, opened.json()["invite_code"]


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, access: str, contest_id: int, invite_code: str, student_user_id: int):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [
                {"kind": "source", "value": _source_object_key(contest_id, student_user_id)}
            ],
            "invite_code": invite_code,
        },
        content_type="application/json",
        **_auth_header(access),
    )


# --- 제출 0건이면 통째 교체된다 --------------------------------------------------


@pytest.mark.django_db
def test_requirements_are_replaced_wholesale_when_no_submissions(client, landing_type):
    root = _operator_client("root-req-1")
    pair = _sponsor_with_permission(client, root, "req-sponsor-1")
    assignment_id, _invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )
    original_requirement_id = Contest.objects.get(id=assignment_id).requirements.get().id

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={
            "requirements": [
                {"text": "README에 실행 방법을 적는다", "grade": "required"},
                {"text": "테스트를 하나 이상 작성한다", "grade": "optional"},
            ]
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert [r["text"] for r in body["requirements"]] == [
        "README에 실행 방법을 적는다",
        "테스트를 하나 이상 작성한다",
    ]
    assert [r["grade"] for r in body["requirements"]] == ["required", "optional"]
    assert [r["order"] for r in body["requirements"]] == [0, 1]

    # 옛 항목은 새 id로 통째로 갈렸다 — 부분 patch(수정/추가)가 아니라 교체다.
    assert not Requirement.objects.filter(id=original_requirement_id).exists()

    # 단일 조회로 다시 봐도 같은 결과다.
    detail = client.get(f"{ASSIGNMENTS_URL}/{assignment_id}", **_auth_header(pair["access"]))
    assert [r["text"] for r in detail.json()["requirements"]] == [
        "README에 실행 방법을 적는다",
        "테스트를 하나 이상 작성한다",
    ]


@pytest.mark.django_db
def test_requirements_can_be_cleared_to_empty(client, landing_type):
    root = _operator_client("root-req-2")
    pair = _sponsor_with_permission(client, root, "req-sponsor-2")
    assignment_id, _invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"requirements": []},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content
    assert response.json()["requirements"] == []
    assert Contest.objects.get(id=assignment_id).requirements.count() == 0


@pytest.mark.django_db
def test_omitting_requirements_leaves_them_untouched(client, landing_type):
    """`requirements`를 아예 보내지 않으면(다른 필드만 고칠 때) 손대지 않는다 —
    `ContestUpdateIn`/`AssignmentUpdateIn`의 부분 갱신 규율과 같다."""

    root = _operator_client("root-req-3")
    pair = _sponsor_with_permission(client, root, "req-sponsor-3")
    assignment_id, _invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "제목만 고친다"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content
    assert len(response.json()["requirements"]) == 1
    assert response.json()["requirements"][0]["text"] == "함수를 정의한다"


@pytest.mark.django_db
def test_invalid_requirement_grade_is_rejected(client, landing_type):
    root = _operator_client("root-req-4")
    pair = _sponsor_with_permission(client, root, "req-sponsor-4")
    assignment_id, _invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"requirements": [{"text": "이상한 등급", "grade": "impossible"}]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    # 실패했으니 원래 요구사항이 그대로 남아 있어야 한다(원자적 실패).
    assert Contest.objects.get(id=assignment_id).requirements.count() == 1


# --- 제출이 있으면 title/description과 같은 이유로 거부된다 -----------------------


@pytest.mark.django_db
def test_requirement_edit_is_rejected_once_a_submission_exists(client, landing_type):
    root = _operator_client("root-req-5")
    pair = _sponsor_with_permission(client, root, "req-sponsor-5")
    assignment_id, invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    student_pair = _login(client, "req-student-5")
    student_user_id = _user_id(client, student_pair["access"])
    submitted = _submit(client, student_pair["access"], assignment_id, invite_code, student_user_id)
    assert submitted.status_code == 201, submitted.content

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"requirements": [{"text": "제출 후에 바꿔본다", "grade": "required"}]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 409
    body = response.json()
    # title/description을 잠그는 것과 같은 이유·같은 문구여야 한다(#217 인수조건 —
    # 새 잠금 규칙을 만들지 않는다).
    assert "제출" in body["detail"]

    # 거부됐으니 요구사항은 그대로다.
    unchanged = Contest.objects.get(id=assignment_id)
    assert unchanged.requirements.count() == 1
    assert unchanged.requirements.get().text == "함수를 정의한다"
