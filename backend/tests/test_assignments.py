"""Assignment 3 — 강사가 결제 없이 과제를 열고 초대코드를 얻는다 (#207, ADR-0028/0029).

`POST /api/assignments`(생성)·`PATCH /api/assignments/{id}`(수정)·
`POST /api/assignments/{id}/open`(열기)·`GET /api/assignments/invite/{code}`
(InviteCode 조회)를 마운트된 django-ninja API로 친다(CLAUDE.md — HTTP가 유일한 시임).

Prior art: `tests/test_contest_update.py`(DRAFT 편집 게이트 모양),
`tests/test_operator_assignment_permissions.py`(자격 부여 HTTP 헬퍼).
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import Client

from contests.assignment_category import get_assignment_category
from contests.models import Contest, DeliverableType, InviteCode
from ledger.models import JournalEntry

ASSIGNMENTS_URL = "/api/assignments"
GRANT_URL = "/api/operator/assignment-permissions/grant"
CONTESTS_URL = "/api/contests"
OPERATOR_PW = "operator-pw-asgn-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _operator_client(username="root-asgn", *, superuser=True):
    call_command("create_operator", username, password=OPERATOR_PW, superuser=superuser)
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


def _grant_permission(operator_client, *, username, reason="수업 개설 승인"):
    response = operator_client.post(
        GRANT_URL,
        data={"username": username, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


def _revoke_permission(operator_client, sponsor_profile_id, *, reason="남용 신고"):
    response = operator_client.post(
        f"/api/operator/assignment-permissions/{sponsor_profile_id}/revoke",
        data={"reason": reason},
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


def _create_assignment(client, access, *, deliverable_type_ids, title="파이썬 기초 과제"):
    return client.post(
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


# --- 자격 게이트 --------------------------------------------------------------


@pytest.mark.django_db
def test_sponsor_without_permission_cannot_create_assignment(client, landing_type):
    pair = _login(client, "no-perm-sponsor-1")

    response = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])

    assert response.status_code == 403


@pytest.mark.django_db
def test_open_is_rejected_when_permission_revoked_after_creation(client, landing_type):
    root = _operator_client("root-asgn-revoke")
    pair = _sponsor_with_permission(client, root, "revoke-target-sponsor")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]

    username = _username(client, pair["access"])
    from accounts.models import SponsorProfile

    sponsor_profile = SponsorProfile.objects.get(user__username=username)
    _revoke_permission(root, sponsor_profile.id)

    response = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 403


# --- 본인확인 없이 열고 낼 수 있다 — 상금 공모전에서는 여전히 막힌다 ------------------------


@pytest.mark.django_db
def test_unverified_account_can_create_and_open_assignment(client, landing_type):
    root = _operator_client("root-asgn-unverified")
    pair = _sponsor_with_permission(client, root, "unverified-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assert created.status_code == 201, created.content
    assert created.json()["status"] == Contest.Status.DRAFT

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{created.json()['id']}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert opened.status_code == 200, opened.content
    body = opened.json()
    assert body["status"] == Contest.Status.ASSIGNMENT_OPEN
    assert body["invite_code"]


@pytest.mark.django_db
def test_same_unverified_account_is_still_blocked_from_paid_contest(client, landing_type):
    """ADR-0029 의 전부라고 부른 그 쌍 — 과제는 통과하지만 상금 공모전 게이트는
    그대로다."""

    root = _operator_client("root-asgn-pair")
    pair = _sponsor_with_permission(client, root, "pair-sponsor-1")

    from contests.models import Category

    category = Category.objects.create(name="교육-pair")

    response = client.post(
        CONTESTS_URL,
        data={
            "title": "상금 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "description": "설명",
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 403


# --- 공개 노출 없음 -------------------------------------------------------------


@pytest.mark.django_db
def test_opened_assignment_is_invisible_on_public_surfaces(client, landing_type):
    root = _operator_client("root-asgn-hidden")
    pair = _sponsor_with_permission(client, root, "hidden-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]
    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert opened.status_code == 200, opened.content

    listed = client.get(CONTESTS_URL)
    assert assignment_id not in [c["id"] for c in listed.json()["items"]]

    detail = client.get(f"{CONTESTS_URL}/{assignment_id}")
    assert detail.status_code == 404

    home = client.get(f"{CONTESTS_URL}/home")
    home_ids = [c["id"] for group in home.json() for c in group["contests"]]
    assert assignment_id not in home_ids


# --- InviteCode 가 유일한 경계 ---------------------------------------------------


@pytest.mark.django_db
def test_wrong_invite_code_is_rejected_and_correct_one_works(client, landing_type):
    root = _operator_client("root-asgn-invite")
    pair = _sponsor_with_permission(client, root, "invite-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]
    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    code = opened.json()["invite_code"]
    assert code

    wrong = client.get(f"{ASSIGNMENTS_URL}/invite/not-the-real-code")
    assert wrong.status_code == 404

    right = client.get(f"{ASSIGNMENTS_URL}/invite/{code}")
    assert right.status_code == 200
    body = right.json()
    assert body["id"] == assignment_id
    assert body["status"] == Contest.Status.ASSIGNMENT_OPEN
    assert len(body["requirements"]) == 1


# --- 원장 분개 0건 --------------------------------------------------------------


@pytest.mark.django_db
def test_assignment_leaves_no_ledger_entries(client, landing_type):
    root = _operator_client("root-asgn-ledger")
    pair = _sponsor_with_permission(client, root, "ledger-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]
    client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    contest = Contest.objects.get(id=assignment_id)
    assert JournalEntry.objects.filter(contest_id=contest.ledger_id).count() == 0
    assert contest.prize == 0
    assert contest.required_minimum_prize == 0
    assert contest.is_underfunded is False
    assert contest.category_id == get_assignment_category().id


# --- 편집: DRAFT·ASSIGNMENT_OPEN 둘 다 되고, 남의 것·마감된 것은 안 된다 -----------------


@pytest.mark.django_db
def test_draft_and_opened_assignment_can_both_be_edited(client, landing_type):
    root = _operator_client("root-asgn-edit")
    pair = _sponsor_with_permission(client, root, "edit-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]

    draft_edit = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "고친 제목(초안)"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert draft_edit.status_code == 200, draft_edit.content
    assert draft_edit.json()["title"] == "고친 제목(초안)"

    client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    open_edit = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "고친 제목(열린 뒤)"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert open_edit.status_code == 200, open_edit.content
    assert open_edit.json()["title"] == "고친 제목(열린 뒤)"


@pytest.mark.django_db
def test_stranger_cannot_edit_or_open_someone_elses_assignment(client, landing_type):
    root = _operator_client("root-asgn-stranger")
    owner_pair = _sponsor_with_permission(client, root, "owner-asgn-1")
    stranger_pair = _login(client, "stranger-asgn-1")

    created = _create_assignment(
        client, owner_pair["access"], deliverable_type_ids=[landing_type.id]
    )
    assignment_id = created.json()["id"]

    edit = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}",
        data={"title": "몰래 고쳐본다"},
        content_type="application/json",
        **_auth_header(stranger_pair["access"]),
    )
    assert edit.status_code == 404

    open_response = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(stranger_pair["access"]),
    )
    assert open_response.status_code == 404


@pytest.mark.django_db
def test_double_open_is_rejected_and_only_one_active_invite_code_exists(client, landing_type):
    root = _operator_client("root-asgn-double")
    pair = _sponsor_with_permission(client, root, "double-open-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]

    first = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert first.status_code == 200

    second = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert second.status_code == 409

    assert InviteCode.objects.filter(contest_id=assignment_id, is_active=True).count() == 1


@pytest.mark.django_db
def test_mine_lists_only_own_assignments_with_invite_code_after_open(client, landing_type):
    root = _operator_client("root-asgn-mine")
    pair = _sponsor_with_permission(client, root, "mine-sponsor-1")
    other_pair = _sponsor_with_permission(client, root, "mine-sponsor-2")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]
    _create_assignment(client, other_pair["access"], deliverable_type_ids=[landing_type.id])

    mine_before_open = client.get(ASSIGNMENTS_URL + "/mine", **_auth_header(pair["access"]))
    assert mine_before_open.status_code == 200
    items = mine_before_open.json()
    assert len(items) == 1
    assert items[0]["id"] == assignment_id
    assert items[0]["invite_code"] is None

    client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    mine_after_open = client.get(ASSIGNMENTS_URL + "/mine", **_auth_header(pair["access"]))
    assert mine_after_open.json()[0]["invite_code"]


@pytest.mark.django_db
def test_create_rejects_empty_deliverable_types(client):
    root = _operator_client("root-asgn-empty")
    pair = _sponsor_with_permission(client, root, "empty-dt-sponsor-1")

    response = _create_assignment(client, pair["access"], deliverable_type_ids=[])

    assert response.status_code == 422


@pytest.mark.django_db
def test_assignment_never_appears_in_my_sponsored_contests_list(client, landing_type):
    """`GET /api/contests/mine`(공모전 전용 「다음 행동」 목록)에는 절대 섞이지
    않는다 — 자기 과제는 `GET /api/assignments/mine`이 따로 보여준다(코드리뷰 지적:
    처음 구현은 `sponsor=profile`만 걸러 Assignment 가 새고 있었다)."""

    root = _operator_client("root-asgn-mineleak")
    pair = _sponsor_with_permission(client, root, "mineleak-sponsor-1")

    created = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_id = created.json()["id"]
    client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    my_contests = client.get(f"{CONTESTS_URL}/mine", **_auth_header(pair["access"]))
    assert my_contests.status_code == 200, my_contests.content
    ids = [row["contest_id"] for row in my_contests.json()["items"]]
    assert assignment_id not in ids
