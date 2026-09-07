"""Assignment 5 — 첫 제출이 문을 닫고, 강사가 InviteCode 를 재발급한다 (#209, ADR-0028).

`PATCH /api/assignments/{id}`(수정 게이트에 제출 0건 술어를 더한다)·
`POST /api/assignments/{id}/invite-code/reissue`(재발급)를 마운트된 django-ninja API로
친다(CLAUDE.md — HTTP가 유일한 시임).

Prior art: `tests/test_assignments.py`(자격 부여·과제 생성·열기 헬퍼),
`tests/test_assignment_submissions.py`(InviteCode 로 제출하는 헬퍼).
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import Contest, DeliverableType, InviteCode
from submissions.models import Submission

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
GRANT_URL = "/api/operator/assignment-permissions/grant"
OPERATOR_PW = "operator-pw-asgnlock-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _operator_client(username="root-asgnlock"):
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


# --- 첫 제출이 문을 닫는다 -------------------------------------------------------


@pytest.mark.django_db
def test_requirements_can_be_edited_while_zero_submissions(client, landing_type):
    root = _operator_client("root-lock-1")
    pair = _sponsor_with_permission(client, root, "lock-sponsor-1")
    assignment_id, _invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "제출 전이라 고칠 수 있다"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "제출 전이라 고칠 수 있다"
    # `is_editable`은 백엔드가 계산해 실어 보낸다 — 화면이 status 문자열만으로 이
    # 규칙을 다시 적지 않게 하는 값이다(코드리뷰 지적).
    assert body["is_editable"] is True


@pytest.mark.django_db
def test_edit_is_rejected_with_reason_once_a_submission_exists(client, landing_type):
    root = _operator_client("root-lock-2")
    pair = _sponsor_with_permission(client, root, "lock-sponsor-2")
    assignment_id, invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    student_pair = _login(client, "lock-student-2")
    student_user_id = _user_id(client, student_pair["access"])
    submitted = _submit(client, student_pair["access"], assignment_id, invite_code, student_user_id)
    assert submitted.status_code == 201, submitted.content

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "제출 후에도 고쳐본다"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 409
    body = response.json()
    # 응답이 이유를 말한다 — 일반적인 "지금은 고칠 수 없는 상태"와 다른, 제출이
    # 있어서 막혔다는 문구여야 화면이 그대로 보여줄 수 있다.
    assert "제출" in body["detail"]

    unchanged = Contest.objects.get(id=assignment_id)
    assert unchanged.title != "제출 후에도 고쳐본다"

    # 화면이 PATCH 실패를 기다리지 않고도 잠금을 미리 보여줄 수 있도록,
    # 조회 응답에도 제출 건수와 계산된 편집 가능 여부가 실려 있다.
    detail = client.get(f"{ASSIGNMENTS_URL}/{assignment_id}", **_auth_header(pair["access"]))
    detail_body = detail.json()
    assert detail_body["submission_count"] == 1
    assert detail_body["is_editable"] is False

    # `GET /assignments/mine`(annotate 로 세는 목록 경로)도 같은 답을 낸다 — 단일
    # 조회와 목록 조회가 서로 다른 셈법으로 갈리지 않는다(#209 코드리뷰 지적).
    mine = client.get(f"{ASSIGNMENTS_URL}/mine", **_auth_header(pair["access"]))
    mine_row = next(row for row in mine.json() if row["id"] == assignment_id)
    assert mine_row["submission_count"] == 1
    assert mine_row["is_editable"] is False


@pytest.mark.django_db
def test_edit_still_allowed_when_other_assignment_has_submissions(client, landing_type):
    """제출 건수는 Contest 단위다 — 남의 과제에 제출이 있다고 내 과제 편집이
    막혀서는 안 된다."""

    root = _operator_client("root-lock-3")
    pair = _sponsor_with_permission(client, root, "lock-sponsor-3")
    other_pair = _sponsor_with_permission(client, root, "lock-sponsor-3b")

    assignment_id, _invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id], title="내 과제"
    )
    other_id, other_invite = _create_and_open_assignment(
        client, other_pair["access"], deliverable_type_ids=[landing_type.id], title="남의 과제"
    )

    student_pair = _login(client, "lock-student-3")
    student_user_id = _user_id(client, student_pair["access"])
    submitted = _submit(client, student_pair["access"], other_id, other_invite, student_user_id)
    assert submitted.status_code == 201, submitted.content

    response = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "여전히 고칠 수 있다"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content


# --- InviteCode 재발급 ----------------------------------------------------------


@pytest.mark.django_db
def test_sponsor_can_reissue_invite_code(client, landing_type):
    root = _operator_client("root-reissue-1")
    pair = _sponsor_with_permission(client, root, "reissue-sponsor-1")
    assignment_id, old_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/invite-code/reissue",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content
    new_code = response.json()["invite_code"]
    assert new_code
    assert new_code != old_code
    assert InviteCode.objects.filter(contest_id=assignment_id, is_active=True).count() == 1


@pytest.mark.django_db
def test_old_invite_code_dies_but_existing_submission_survives_reissue(client, landing_type):
    root = _operator_client("root-reissue-2")
    pair = _sponsor_with_permission(client, root, "reissue-sponsor-2")
    assignment_id, old_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    student_pair = _login(client, "reissue-student-2")
    student_user_id = _user_id(client, student_pair["access"])
    submitted = _submit(client, student_pair["access"], assignment_id, old_code, student_user_id)
    assert submitted.status_code == 201, submitted.content

    reissued = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/invite-code/reissue",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert reissued.status_code == 200, reissued.content
    new_code = reissued.json()["invite_code"]

    # 옛 코드로는 더 이상 과제를 조회할 수 없다 — 존재를 드러내지 않는다.
    old_lookup = client.get(f"{ASSIGNMENTS_URL}/invite/{old_code}")
    assert old_lookup.status_code == 404

    # 새 코드로는 조회된다.
    new_lookup = client.get(f"{ASSIGNMENTS_URL}/invite/{new_code}")
    assert new_lookup.status_code == 200

    # 옛 코드로 새 학생이 들어오려 하면 거부된다.
    new_student_pair = _login(client, "reissue-newcomer-2")
    new_student_id = _user_id(client, new_student_pair["access"])
    blocked = _submit(
        client, new_student_pair["access"], assignment_id, old_code, new_student_id
    )
    assert blocked.status_code == 403

    # 그러나 재발급 전에 이미 제출한 학생의 Submission 은 그대로 남는다.
    assert Submission.objects.filter(
        contest_id=assignment_id, developer__user__username=_username(client, student_pair["access"])
    ).exists()

    # 그 학생은 새 코드로 자기 제출을 계속 조회·수정할 수 있다.
    my_submission = client.get(
        f"{CONTESTS_URL}/{assignment_id}/submissions/me", **_auth_header(student_pair["access"])
    )
    assert my_submission.status_code == 200, my_submission.content


@pytest.mark.django_db
def test_stranger_cannot_reissue_someone_elses_invite_code(client, landing_type):
    root = _operator_client("root-reissue-3")
    owner_pair = _sponsor_with_permission(client, root, "reissue-owner-3")
    stranger_pair = _login(client, "reissue-stranger-3")

    assignment_id, _old_code = _create_and_open_assignment(
        client, owner_pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/invite-code/reissue",
        content_type="application/json",
        **_auth_header(stranger_pair["access"]),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_reissue_rejected_before_assignment_is_opened(client, landing_type):
    root = _operator_client("root-reissue-4")
    pair = _sponsor_with_permission(client, root, "reissue-sponsor-4")

    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": "아직 안 연 과제",
            "deliverable_type_ids": [landing_type.id],
            "description": "설명",
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assignment_id = created.json()["id"]

    response = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/invite-code/reissue",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 409
