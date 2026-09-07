"""Assignment 4 — 학생이 초대코드로 들어와 인증 없이 제출한다 (#208, ADR-0028/0029).

기존 `POST /api/contests/{contest_id}/submissions`·`PUT .../submissions/me` 를 그대로
재사용한다(CLAUDE.md — 새 API 를 만들지 않는다). 달라지는 것은 Assignment 경로가
본인확인·자전거래 검사를 부르지 않는다는 것과, `invite_code` 로 InviteCode 를 다시
확인한다는 것뿐이다 — 마감 검사는 그대로 선다.

Prior art: `tests/test_submissions.py`(object_key 헬퍼·payload 모양),
`tests/test_assignments.py`(자격 부여·과제 생성·열기 헬퍼).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from submissions.models import Submission

PAYMENTS_URL = "/api/payments"


def _sign(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
GRANT_URL = "/api/operator/assignment-permissions/grant"
OPERATOR_PW = "operator-pw-asgnsub-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _operator_client(username="root-asgnsub"):
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


def _verify(client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"사람|1995-01-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _grant_permission(operator_client, *, username, reason="수업 개설 승인"):
    response = operator_client.post(
        GRANT_URL,
        data={"username": username, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _create_and_open_assignment(client, *, deliverable_type_ids, sponsor_uid, deadline_at=None):
    root = _operator_client(f"root-{sponsor_uid}")
    pair = _login(client, sponsor_uid)
    username = _username(client, pair["access"])
    _grant_permission(root, username=username)

    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))
    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": f"{sponsor_uid}의 과제",
            "deliverable_type_ids": deliverable_type_ids,
            "description": "과제 설명",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert opened.status_code == 200, opened.content
    body = opened.json()
    return {"id": assignment_id, "invite_code": body["invite_code"]}


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, access: str, contest_id: int, payload: dict):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


def _update(client, access: str, contest_id: int, payload: dict):
    return client.put(
        f"{CONTESTS_URL}/{contest_id}/submissions/me",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


@pytest.mark.django_db
def test_unverified_student_can_submit_to_assignment_with_invite_code(client, landing_type):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asub-sponsor-1"
    )

    student_pair = _login(client, "asub-student-1")
    student_user_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]

    response = _submit(
        client,
        student_pair["access"],
        assignment["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(assignment["id"], student_user_id),
                }
            ],
            "invite_code": assignment["invite_code"],
        },
    )

    assert response.status_code == 201, response.content
    assert Submission.objects.filter(contest_id=assignment["id"]).count() == 1


@pytest.mark.django_db
def test_same_unverified_student_is_still_blocked_from_paid_contest_submission(
    client, landing_type
):
    category = Category.objects.create(name="교육-asub-pair")
    sponsor_pair = _login(client, "asub-pair-sponsor")
    _verify(client, sponsor_pair["access"], ci="asub-pair-sponsor-ci")
    contest = client.post(
        CONTESTS_URL,
        data={
            "title": "상금 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor_pair["access"]),
    ).json()

    # 결제까지 확정해 published 로 옮긴다 — draft 는 애초에 SUBMITTABLE 이 아니라서
    # (본인확인 게이트에 닿기 전에) 404 로 끝나 이 테스트가 보려는 것을 못 본다.
    payment = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(sponsor_pair["access"]),
    ).json()
    webhook_id = f"wh-{contest['id']}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign(webhook_id=webhook_id, order_id=payment["order_id"], status="paid")
    webhook_resp = client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")
    assert webhook_resp.status_code == 200, webhook_resp.content

    student_pair = _login(client, "asub-pair-student")

    response = _submit(
        client,
        student_pair["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": "submission:x:1:source/abc"}]},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_missing_or_wrong_invite_code_cannot_submit(client, landing_type):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asub-sponsor-2"
    )
    student_pair = _login(client, "asub-student-2")
    student_user_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]

    missing = _submit(
        client,
        student_pair["access"],
        assignment["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(assignment["id"], student_user_id),
                }
            ]
        },
    )
    assert missing.status_code == 403

    wrong = _submit(
        client,
        student_pair["access"],
        assignment["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(assignment["id"], student_user_id),
                }
            ],
            "invite_code": "not-the-real-code",
        },
    )
    assert wrong.status_code == 403
    assert Submission.objects.filter(contest_id=assignment["id"]).count() == 0


@pytest.mark.django_db
def test_cannot_submit_after_assignment_deadline_passed(client, landing_type):
    assignment = _create_and_open_assignment(
        client,
        deliverable_type_ids=[landing_type.id],
        sponsor_uid="asub-sponsor-3",
        deadline_at=timezone.now() - timedelta(hours=1),
    )
    student_pair = _login(client, "asub-student-3")
    student_user_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]

    response = _submit(
        client,
        student_pair["access"],
        assignment["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(assignment["id"], student_user_id),
                }
            ],
            "invite_code": assignment["invite_code"],
        },
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_student_can_edit_own_submission_before_deadline(client, landing_type):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asub-sponsor-4"
    )
    student_pair = _login(client, "asub-student-4")
    student_user_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]

    first_key = _source_object_key(assignment["id"], student_user_id)
    created = _submit(
        client,
        student_pair["access"],
        assignment["id"],
        {"assets": [{"kind": "source", "value": first_key}], "invite_code": assignment["invite_code"]},
    )
    assert created.status_code == 201, created.content

    second_key = _source_object_key(assignment["id"], student_user_id)
    updated = _update(
        client,
        student_pair["access"],
        assignment["id"],
        {"assets": [{"kind": "source", "value": second_key}], "invite_code": assignment["invite_code"]},
    )
    assert updated.status_code == 200, updated.content

    my_submission = client.get(
        f"{CONTESTS_URL}/{assignment['id']}/submissions/me", **_auth_header(student_pair["access"])
    )
    assert my_submission.status_code == 200, my_submission.content


@pytest.mark.django_db
def test_logged_in_stranger_without_invite_code_cannot_guess_assignment_id(
    client, landing_type
):
    """`contest_id` 는 순차 정수라 짐작할 수 있다 — 로그인은 했지만 InviteCode 를 받은
    적 없는 계정은 그 짐작만으로 제출할 수 없어야 한다(위 `test_missing_or_wrong_
    invite_code_cannot_submit` 과 같은 결론을, 코드를 아예 모르는 **제3의 계정**
    으로 다시 확인한다 — 같은 학생이 실수로 빈 코드를 보낸 경우와 애초에 초대받지
    않은 사람이 시도하는 경우는 서로 다른 시나리오다)."""

    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asub-sponsor-5"
    )
    stranger_pair = _login(client, "asub-stranger-5")
    stranger_user_id = client.get(
        "/api/accounts/me", **_auth_header(stranger_pair["access"])
    ).json()["id"]

    response = _submit(
        client,
        stranger_pair["access"],
        assignment["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(assignment["id"], stranger_user_id),
                }
            ]
        },
    )

    assert response.status_code == 403
