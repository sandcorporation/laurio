"""제출을 받는 동안(published)에도 개최자가 공모전을 고칠 수 있다 (#473, ADR-0051).

지금까지는 공개(publish)하는 순간 브리프·요구사항이 통째로 잠겼다 —
`_get_owned_draft_contest`가 DRAFT가 아니면 409로 거절했다. 이 티켓은 그
문을 「제출을 받는 동안」까지 넓힌다: `PATCH /api/contests/{id}`와 요구사항
CRUD가 PUBLISHED에서도 통과하고, 실제로 바뀐 필드가 있으면 `ContestChange`가
남고 이미 제출한 참가자에게 알림이 간다. 마감 뒤(CLOSED 이후)는 여전히
막는다 — Score가 이미 그 체크리스트를 근거로 만들어졌기 때문이다(ADR-0006).

DRAFT·CLOSED 게이트 자체의 회귀는 `test_contest_update.py`·
`test_requirement_chat.py`가 다룬다 — 여기서는 PUBLISHED에서 새로 열린
동작(이력·알림·상금/마감 제약)만 다룬다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, ContestChange, DeliverableType, Requirement
from notifications.models import Notification, NotificationType

CONTESTS_URL = "/api/contests"
PERMISSIONS_URL = "/api/operator/hosting-permissions"
ORIGIN = "http://testserver"
PW = "operator-pw-9942-content-edit"

pytestmark = pytest.mark.django_db


# --- 헬퍼 --------------------------------------------------------------------


def _login(client, uid: str) -> dict:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"사람|1990-01-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _operator_client(username: str):
    call_command("create_operator", username, password=PW, superuser=True)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _grant_hosting_permission(operator_client, user_id: int) -> None:
    response = operator_client.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": True, "reason": "테스트 개최 권한"},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def category(db):
    return Category.objects.create(name="교육-내용변경")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지-내용변경", minimum_prize=500_000)


def _create_paid_draft(client, access: str, *, category, deliverable_type, prize=2_000_000) -> dict:
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "고칠 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "description": "원래 설명",
            "prize": prize,
            "deadline_at": (timezone.now() + timedelta(days=30)).isoformat(),
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _force_published(contest_id: int) -> None:
    Contest.objects.filter(id=contest_id).update(status=Contest.Status.PUBLISHED)


def _free_published_contest_with_submitter(
    client, *, host_uid, dev_uid, category, deliverable_type
) -> tuple[dict, dict, dict]:
    """무료 공모전을 실제로 공개하고 참가자 하나를 제출까지 시킨다 — 알림 팬아웃
    대상(`_participating_developer_users`)을 진짜 HTTP 경로로 만든다."""

    host_pair = _login(client, host_uid)
    profile_resp = client.post(
        "/api/accounts/sponsor-profile",
        data={"display_name": f"{host_uid} 개최자"},
        content_type="application/json",
        **_auth_header(host_pair["access"]),
    )
    assert profile_resp.status_code == 200, profile_resp.content

    from django.contrib.auth import get_user_model

    host_user = get_user_model().objects.get(email=f"{host_uid}@example.com")
    root = _operator_client(f"root-{host_uid}")
    _grant_hosting_permission(root, host_user.id)

    draft_resp = client.post(
        f"{CONTESTS_URL}/free",
        data={
            "title": f"{host_uid}의 무료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "description": "원래 설명",
            "deadline_at": (timezone.now() + timedelta(days=30)).isoformat(),
            "requirements": [{"text": "로그인 기능이 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(host_pair["access"]),
    )
    assert draft_resp.status_code == 200, draft_resp.content
    draft = draft_resp.json()

    published_resp = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(host_pair["access"]),
    )
    assert published_resp.status_code == 200, published_resp.content
    contest = published_resp.json()

    dev_pair = _login(client, dev_uid)
    dev_user = get_user_model().objects.get(email=f"{dev_uid}@example.com")
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [
                {
                    "kind": "source",
                    "value": f"submission:{contest['id']}:{dev_user.id}:source/{uuid4().hex}",
                }
            ],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev_pair["access"]),
    )
    assert submit_resp.status_code == 201, submit_resp.content

    host = {"access": host_pair["access"], "user_id": host_user.id}
    dev = {"access": dev_pair["access"], "user_id": dev_user.id}
    return host, contest, dev


# --- 브리프 편집: published에서 열린다 ------------------------------------------


def test_brief_update_while_published_succeeds_and_returns_correct_submission_count(
    client, category, landing_type
):
    pair = _login(client, "sponsor-content-1")
    _verify(client, pair["access"], ci="sponsor-content-ci-1")
    created = _create_paid_draft(client, pair["access"], category=category, deliverable_type=landing_type)
    _force_published(created["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"title": "제출 중에 고친 제목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "제출 중에 고친 제목"
    assert body["status"] == "published"
    # DRAFT의 0 하드코딩과 달리, PUBLISHED는 실제 참가작 수를 세야 한다.
    assert body["submission_count"] == 0


def test_prize_cannot_be_changed_while_published(client, category, landing_type):
    pair = _login(client, "sponsor-content-2")
    _verify(client, pair["access"], ci="sponsor-content-ci-2")
    created = _create_paid_draft(client, pair["access"], category=category, deliverable_type=landing_type)
    _force_published(created["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"prize": 9_999_999},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422, response.content
    assert Contest.objects.get(id=created["id"]).prize == created["prize"]


def test_deadline_cannot_move_to_the_past(client, category, landing_type):
    pair = _login(client, "sponsor-content-3")
    _verify(client, pair["access"], ci="sponsor-content-ci-3")
    created = _create_paid_draft(client, pair["access"], category=category, deliverable_type=landing_type)
    _force_published(created["id"])

    past = (timezone.now() - timedelta(hours=1)).isoformat()
    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"deadline_at": past},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422, response.content


def test_deadline_can_move_to_a_later_time(client, category, landing_type):
    pair = _login(client, "sponsor-content-4")
    _verify(client, pair["access"], ci="sponsor-content-ci-4")
    created = _create_paid_draft(client, pair["access"], category=category, deliverable_type=landing_type)
    _force_published(created["id"])

    later = (timezone.now() + timedelta(days=60)).isoformat()
    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"deadline_at": later},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200, response.content
    assert response.json()["deadline_at"].startswith(later[:10])


def test_deliverable_type_change_while_published_does_not_touch_frozen_minimum_snapshot(
    client, category, landing_type
):
    """개최(결제) 시점에 굳은 `required_minimum_prize`·`is_underfunded`는 published
    편집으로 요구형태가 바뀌어도 다시 계산되지 않는다 — 그 스냅샷은 결제 확정
    금액을 근거로 삼는다(update_contest 독스트링)."""

    other_type = DeliverableType.objects.create(name="관리자 페이지-내용변경", minimum_prize=1_500_000)
    pair = _login(client, "sponsor-content-5")
    _verify(client, pair["access"], ci="sponsor-content-ci-5")
    created = _create_paid_draft(
        client, pair["access"], category=category, deliverable_type=landing_type, prize=1_000_000
    )
    assert created["required_minimum_prize"] == 500_000
    _force_published(created["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"deliverable_type_ids": [other_type.id]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert [dt["id"] for dt in body["deliverable_types"]] == [other_type.id]
    # 상금미달 배지 스냅샷은 개최 시점 값(랜딩 50만) 그대로다 — 새 요구형태
    # (관리자 페이지 150만)로 다시 계산됐다면 여기서 100만 미달로 바뀌었을 것이다.
    assert body["required_minimum_prize"] == 500_000
    assert body["is_underfunded"] is False


def test_no_op_patch_does_not_create_a_change_record(client, category, landing_type):
    pair = _login(client, "sponsor-content-6")
    _verify(client, pair["access"], ci="sponsor-content-ci-6")
    created = _create_paid_draft(client, pair["access"], category=category, deliverable_type=landing_type)
    _force_published(created["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"title": created["title"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200, response.content
    assert not ContestChange.objects.filter(contest_id=created["id"]).exists()


def test_draft_edit_does_not_create_a_change_record_or_notify(client, category, landing_type):
    """DRAFT 편집은 이력·알림 대상이 아니다 — 아직 아무도 그 조건을 보고
    참가하지 않았다(`_record_contest_change` 독스트링)."""

    pair = _login(client, "sponsor-content-7")
    _verify(client, pair["access"], ci="sponsor-content-ci-7")
    created = _create_paid_draft(client, pair["access"], category=category, deliverable_type=landing_type)

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"title": "초안에서 고친 제목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200, response.content
    assert not ContestChange.objects.filter(contest_id=created["id"]).exists()
    assert not Notification.objects.filter(notification_type=NotificationType.CONTEST_UPDATED).exists()


# --- 변경 이력과 알림: 실제 참가자가 있는 published 공모전 -----------------------


def test_brief_update_while_published_records_change_and_notifies_participant(
    client, category, landing_type
):
    host, contest, dev = _free_published_contest_with_submitter(
        client,
        host_uid="sponsor-content-8-host",
        dev_uid="sponsor-content-8-dev",
        category=category,
        deliverable_type=landing_type,
    )

    response = client.patch(
        f"{CONTESTS_URL}/{contest['id']}",
        data={"title": "참가자가 있는 채로 고친 제목", "description": "바뀐 설명"},
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert response.status_code == 200, response.content

    change = ContestChange.objects.get(contest_id=contest["id"])
    assert change.action == ContestChange.Action.UPDATED
    assert change.before["title"] == contest["title"]
    assert change.after["title"] == "참가자가 있는 채로 고친 제목"
    assert change.after["description"] == "바뀐 설명"

    assert Notification.objects.filter(
        recipient_id=dev["user_id"], notification_type=NotificationType.CONTEST_UPDATED
    ).exists()
    # 개최자 자신에게는 알림이 가지 않는다 — 자기가 방금 한 행동이다.
    assert not Notification.objects.filter(
        recipient_id=host["user_id"], notification_type=NotificationType.CONTEST_UPDATED
    ).exists()


def test_requirement_added_while_published_records_change_and_notifies_participant(
    client, category, landing_type
):
    host, contest, dev = _free_published_contest_with_submitter(
        client,
        host_uid="sponsor-content-9-host",
        dev_uid="sponsor-content-9-dev",
        category=category,
        deliverable_type=landing_type,
    )

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/requirements",
        data={"text": "다크모드를 지원한다", "grade": "optional"},
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert response.status_code == 200, response.content
    requirement_id = response.json()["id"]

    change = ContestChange.objects.get(
        contest_id=contest["id"], action=ContestChange.Action.REQUIREMENT_ADDED
    )
    assert change.before == {}
    assert change.after["id"] == requirement_id
    assert change.after["text"] == "다크모드를 지원한다"

    assert Notification.objects.filter(
        recipient_id=dev["user_id"], notification_type=NotificationType.CONTEST_UPDATED
    ).exists()


def test_requirement_updated_while_published_records_change(client, category, landing_type):
    host, contest, _dev = _free_published_contest_with_submitter(
        client,
        host_uid="sponsor-content-10-host",
        dev_uid="sponsor-content-10-dev",
        category=category,
        deliverable_type=landing_type,
    )
    requirement = Requirement.objects.get(contest_id=contest["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{contest['id']}/requirements/{requirement.id}",
        data={"text": "로그인과 회원가입 기능이 있다"},
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert response.status_code == 200, response.content

    change = ContestChange.objects.get(
        contest_id=contest["id"], action=ContestChange.Action.REQUIREMENT_UPDATED
    )
    assert change.before["text"] == requirement.text
    assert change.after["text"] == "로그인과 회원가입 기능이 있다"


def test_requirement_update_with_no_actual_change_does_not_record(client, category, landing_type):
    host, contest, _dev = _free_published_contest_with_submitter(
        client,
        host_uid="sponsor-content-11-host",
        dev_uid="sponsor-content-11-dev",
        category=category,
        deliverable_type=landing_type,
    )
    requirement = Requirement.objects.get(contest_id=contest["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{contest['id']}/requirements/{requirement.id}",
        data={"text": requirement.text, "grade": requirement.grade},
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert response.status_code == 200, response.content
    assert not ContestChange.objects.filter(
        contest_id=contest["id"], action=ContestChange.Action.REQUIREMENT_UPDATED
    ).exists()


def test_requirement_removed_while_published_records_change(client, category, landing_type):
    host, contest, _dev = _free_published_contest_with_submitter(
        client,
        host_uid="sponsor-content-12-host",
        dev_uid="sponsor-content-12-dev",
        category=category,
        deliverable_type=landing_type,
    )
    requirement = Requirement.objects.get(contest_id=contest["id"])
    requirement_id = requirement.id
    requirement_text = requirement.text

    response = client.delete(
        f"{CONTESTS_URL}/{contest['id']}/requirements/{requirement_id}",
        **_auth_header(host["access"]),
    )
    assert response.status_code == 200, response.content

    change = ContestChange.objects.get(
        contest_id=contest["id"], action=ContestChange.Action.REQUIREMENT_REMOVED
    )
    assert change.after == {}
    assert change.before["id"] == requirement_id
    assert change.before["text"] == requirement_text


def test_stranger_cannot_edit_published_contest(client, category, landing_type):
    host, contest, _dev = _free_published_contest_with_submitter(
        client,
        host_uid="sponsor-content-13-host",
        dev_uid="sponsor-content-13-dev",
        category=category,
        deliverable_type=landing_type,
    )
    stranger = _login(client, "sponsor-content-13-stranger")

    response = client.patch(
        f"{CONTESTS_URL}/{contest['id']}",
        data={"title": "남의 공모전을 고쳐본다"},
        content_type="application/json",
        **_auth_header(stranger["access"]),
    )
    # 있는지가 아니라 없는지로 단언한다 — 403이 아니라 404다.
    assert response.status_code == 404
