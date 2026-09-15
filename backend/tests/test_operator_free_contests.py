"""운영자 앱 무료 공모전 목록 — 상태·수상 여부·수상자 (#420, ADR-0048).

`tests/test_free_contest_award.py`와 같은 형식(HTTP 시임만, 각 파일이 자기
헬퍼를 갖는다, CLAUDE.md)을 따른다. 수상자 옆에서 「운영팀 알림 보내기」로
이어지는 화면의 밑감이다 — 그래서 수상자 이메일·닉네임까지 응답에 실려야
한다(#418의 받는 사람 검색과 같은 값 모양).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride

ORIGIN = "http://testserver"
CONTESTS_URL = "/api/contests"
PERMISSIONS_URL = "/api/operator/hosting-permissions"
FREE_CONTESTS_URL = "/api/operator/contests/free"
TICK_URL = "/api/internal/tick"
PW = "operator-pw-9942-xkcd-privacy"

pytestmark = pytest.mark.django_db


# --- 헬퍼 (test_free_contest_award.py 와 같은 모양) --------------------------


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _operator_client(username, *, superuser=True):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _hosted_user(client, uid: str) -> dict:
    pair = _login(client, uid)
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email=f"{uid}@example.com")
    return {"access": pair["access"], "user_id": user.id}


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _grant(operator_client, user_id: int, *, reason="테스트 개최 권한"):
    response = operator_client.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": True, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일-운영목록")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지-운영목록", minimum_prize=500_000)


def _free_published_contest(
    client, *, host_uid, deadline_at, category, landing_type
) -> tuple[dict, dict]:
    host = _hosted_user(client, host_uid)
    root = _operator_client(f"root-{host_uid}")
    _grant(root, host["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data={
            "title": f"{host_uid}의 무료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "description": "",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(host["access"]),
    ).json()

    published = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert published.status_code == 200, published.content
    return host, published.json()


def _source_asset(contest_id: int, user_id: int) -> dict:
    return {
        "kind": "source",
        "value": f"submission:{contest_id}:{user_id}:source/{uuid4().hex}",
    }


def _submit(client, dev: dict, contest_id: int) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [_source_asset(contest_id, dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client, contest: dict, *, deadline) -> None:
    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


def _award(client, host: dict, contest_id: int, submission_id: int):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/award",
        data={"submission_id": submission_id},
        content_type="application/json",
        **_auth_header(host["access"]),
    )


def _list_free_contests(client):
    response = client.get(FREE_CONTESTS_URL)
    assert response.status_code == 200, response.content
    return response.json()


def _row_for(items, contest_id):
    (row,) = [item for item in items if item["id"] == contest_id]
    return row


# --- 목록: 상태·수상 여부 -----------------------------------------------------


def test_free_contest_list_shows_status_and_no_winner_before_award(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-list-1", deadline_at=deadline, category=category, landing_type=landing_type
    )

    root = _operator_client("root-free-list-1-viewer")
    items = _list_free_contests(root)

    row = _row_for(items, contest["id"])
    assert row["status"] == "published"
    assert row["winner"] is None


def test_free_contest_list_shows_winner_after_award(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-list-2", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-list-2-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = _award(client, host, contest["id"], submission["id"])
    assert award_resp.status_code == 200, award_resp.content

    root = _operator_client("root-free-list-2-viewer")
    items = _list_free_contests(root)

    row = _row_for(items, contest["id"])
    assert row["status"] == "awarded"
    assert row["winner"]["user_id"] == dev["user_id"]
    assert row["winner"]["email"] == "free-list-2-dev@example.com"


def test_free_contest_list_shows_no_winner_when_judging_ends_unawarded(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-list-3", deadline_at=deadline, category=category, landing_type=landing_type
    )
    _submit(client, _hosted_user(client, "free-list-3-dev"), contest["id"])
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED

    root = _operator_client("root-free-list-3-viewer")
    items = _list_free_contests(root)

    row = _row_for(items, contest["id"])
    assert row["status"] == "judging_ended"
    assert row["winner"] is None


# --- 유료 공모전은 섞이지 않는다 ----------------------------------------------


def test_free_contest_list_excludes_paid_contests(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _, free_contest = _free_published_contest(
        client, host_uid="free-list-mix", deadline_at=deadline, category=category, landing_type=landing_type
    )

    sponsor = _hosted_user(client, "free-list-mix-paid-sponsor")
    verify_resp = client.post(
        "/api/verification/verify",
        data={
            "verification_token": "사람|1990-01-01|free-list-mix-paid-ci|free-list-mix-paid-ci-di"
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert verify_resp.status_code == 200, verify_resp.content
    paid_contest = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 공모전 — 운영자 목록 회귀",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": deadline.isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert paid_contest.status_code == 200, paid_contest.content
    paid_contest = paid_contest.json()

    root = _operator_client("root-free-list-mix-viewer")
    items = _list_free_contests(root)

    ids = {item["id"] for item in items}
    assert free_contest["id"] in ids
    assert paid_contest["id"] not in ids


# --- 운영자가 아닌 요청은 거절된다 --------------------------------------------


def test_non_operator_request_is_rejected():
    user_client = Client()
    _login(user_client, "free-list-not-operator")

    response = user_client.get(FREE_CONTESTS_URL)

    assert response.status_code in (401, 403), response.content
