"""무료 공모전 개최 — 권한 있는 사람이 결제·본인확인 없이 열고 목록에 뜬다
(#415, ADR-0048).

HTTP 시임만 쓴다(CLAUDE.md) — `contests.hosting_permission_services`나
`claim_contest_transition`을 직접 부르지 않는다. 헬퍼는
`tests/test_operator_hosting_permission.py`(운영자 로그인·권한 부여)와
`tests/test_judging_period_and_award.py`(개발자 로그인)의 것을 그대로 따른다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType

ORIGIN = "http://testserver"
PERMISSIONS_URL = "/api/operator/hosting-permissions"
CONTESTS_URL = "/api/contests"
PW = "operator-pw-9942-xkcd-privacy"

pytestmark = pytest.mark.django_db


# --- 헬퍼 --------------------------------------------------------------------


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


def _login(client, uid="dev-1", email=None):
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


def _grant(operator_client, user_id: int, *, granted=True, reason="무료 공모전 테스터로 지정"):
    response = operator_client.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": granted, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일-무료")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지-무료", minimum_prize=500_000)


def _free_brief(category, deliverable_type, *, title="무료 공모전", deadline_at=None):
    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))
    return {
        "title": title,
        "category_id": category.id,
        "deliverable_type_ids": [deliverable_type.id],
        "description": "테스트용 무료 공모전입니다.",
        "deadline_at": deadline_at.isoformat(),
        "requirements": [],
    }


def _hosted_user(client, uid: str, *, email=None) -> dict:
    pair = _login(client, uid=uid, email=email)
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email=email or f"{uid}@example.com")
    return {"access": pair["access"], "user_id": user.id}


# --- 개최 권한 자가 확인 -------------------------------------------------------


def test_own_hosting_permission_defaults_to_false(client, category, landing_type):
    user = _hosted_user(client, "free-self-check")

    response = client.get(
        f"{CONTESTS_URL}/free/hosting-permission", **_auth_header(user["access"])
    )

    assert response.status_code == 200, response.content
    assert response.json()["is_granted"] is False


def test_own_hosting_permission_reflects_grant(client, category, landing_type):
    user = _hosted_user(client, "free-self-check-granted")
    root = _operator_client("root-free-self-check")
    _grant(root, user["user_id"])

    response = client.get(
        f"{CONTESTS_URL}/free/hosting-permission", **_auth_header(user["access"])
    )

    assert response.status_code == 200, response.content
    assert response.json()["is_granted"] is True


def test_own_hosting_permission_requires_login(client):
    response = client.get(f"{CONTESTS_URL}/free/hosting-permission")
    assert response.status_code == 401


# --- 개최: 권한 있는 사람이 본인확인·결제 없이 만들고 공개한다 -----------------


def test_permitted_user_creates_and_publishes_free_contest_without_verification_or_payment(
    client, category, landing_type
):
    user = _hosted_user(client, "free-host-1")
    root = _operator_client("root-free-host-1")
    _grant(root, user["user_id"])

    create_resp = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert create_resp.status_code == 200, create_resp.content
    draft = create_resp.json()
    assert draft["status"] == "draft"
    assert draft["is_free"] is True
    assert draft["prize"] == 0
    assert draft["required_minimum_prize"] == 0
    assert draft["is_underfunded"] is False

    publish_resp = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert publish_resp.status_code == 200, publish_resp.content
    published = publish_resp.json()
    assert published["status"] == "published"
    assert published["is_free"] is True

    # 목록·상세에 무료 표시가 실린다.
    detail = client.get(f"{CONTESTS_URL}/{draft['id']}")
    assert detail.status_code == 200
    assert detail.json()["is_free"] is True

    listed = client.get(CONTESTS_URL)
    assert listed.status_code == 200
    by_id = {c["id"]: c for c in listed.json()["items"]}
    assert draft["id"] in by_id
    assert by_id[draft["id"]]["is_free"] is True


def test_paid_contest_is_not_flagged_free(client, category, landing_type):
    """회귀 방지 — 기존 유료 개최 경로로 만든 Contest는 `is_free`가 False다."""

    user = _hosted_user(client, "paid-host-not-free")
    from verification.models import Verification

    verify_resp = client.post(
        "/api/verification/verify",
        data={"verification_token": "사람|1990-01-01|paid-ci-not-free|paid-ci-not-free-di"},
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert verify_resp.status_code == 200

    create_resp = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert create_resp.status_code == 200, create_resp.content
    assert create_resp.json()["is_free"] is False


def test_unpermitted_user_cannot_create_free_contest(client, category, landing_type):
    user = _hosted_user(client, "free-host-no-perm")

    response = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    )

    assert response.status_code == 403, response.content
    assert Contest.objects.count() == 0


def test_unpermitted_user_cannot_publish_even_with_an_existing_draft(
    client, category, landing_type
):
    """권한을 회수당한 뒤에는 이미 만든 draft도 새로 공개할 수 없다(#414 —
    이미 공개된 것만 영향받지 않는다, draft는 새 규칙을 그대로 적용받는다)."""

    user = _hosted_user(client, "free-host-revoked")
    root = _operator_client("root-free-host-revoked")
    _grant(root, user["user_id"])

    create_resp = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert create_resp.status_code == 200, create_resp.content
    draft = create_resp.json()

    _grant(root, user["user_id"], granted=False, reason="더 이상 필요 없음")

    publish_resp = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert publish_resp.status_code == 403, publish_resp.content
    assert Contest.objects.get(id=draft["id"]).status == Contest.Status.DRAFT


def test_revoking_permission_does_not_affect_an_already_published_free_contest(
    client, category, landing_type
):
    user = _hosted_user(client, "free-host-already-published")
    root = _operator_client("root-free-host-already-published")
    _grant(root, user["user_id"])

    create_resp = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    draft = create_resp.json()
    publish_resp = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert publish_resp.status_code == 200, publish_resp.content

    _grant(root, user["user_id"], granted=False, reason="회수")

    detail = client.get(f"{CONTESTS_URL}/{draft['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "published"


def test_publishing_someone_elses_draft_is_404(client, category, landing_type):
    owner = _hosted_user(client, "free-host-owner")
    stranger = _hosted_user(client, "free-host-stranger")
    root = _operator_client("root-free-host-owner-stranger")
    _grant(root, owner["user_id"])
    _grant(root, stranger["user_id"])

    create_resp = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(owner["access"]),
    )
    draft = create_resp.json()

    publish_resp = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(stranger["access"]),
    )
    assert publish_resp.status_code == 404, publish_resp.content


def test_publishing_twice_is_409(client, category, landing_type):
    user = _hosted_user(client, "free-host-double-publish")
    root = _operator_client("root-free-host-double-publish")
    _grant(root, user["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    ).json()

    first = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert first.status_code == 200

    second = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert second.status_code == 409, second.content


def test_cannot_publish_a_paid_draft_through_the_free_endpoint(client, category, landing_type):
    user = _hosted_user(client, "free-host-paid-draft")
    root = _operator_client("root-free-host-paid-draft")
    _grant(root, user["user_id"])

    verify_resp = client.post(
        "/api/verification/verify",
        data={
            "verification_token": "사람|1990-01-01|paid-draft-ci|paid-draft-ci-di"
        },
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert verify_resp.status_code == 200

    paid_draft = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 초안",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(user["access"]),
    ).json()

    publish_resp = client.post(
        f"{CONTESTS_URL}/{paid_draft['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert publish_resp.status_code == 409, publish_resp.content
    assert Contest.objects.get(id=paid_draft["id"]).status == Contest.Status.DRAFT


def test_updating_a_free_draft_can_change_title_but_not_prize(client, category, landing_type):
    """`PATCH /contests/{id}`는 유료·무료 draft가 공유하는 엔드포인트다 —
    무료 공모전은 상금 자체가 없으므로 `prize`를 보내면 거절한다(#415)."""

    user = _hosted_user(client, "free-host-brief-edit")
    root = _operator_client("root-free-host-brief-edit")
    _grant(root, user["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    ).json()

    ok_resp = client.patch(
        f"{CONTESTS_URL}/{draft['id']}",
        data={"title": "제목을 고쳤습니다"},
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert ok_resp.status_code == 200, ok_resp.content
    assert ok_resp.json()["title"] == "제목을 고쳤습니다"
    assert ok_resp.json()["is_free"] is True

    prize_resp = client.patch(
        f"{CONTESTS_URL}/{draft['id']}",
        data={"prize": 500_000},
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert prize_resp.status_code == 422, prize_resp.content
    assert Contest.objects.get(id=draft["id"]).prize == 0


def test_changing_deliverable_types_on_a_free_draft_does_not_manufacture_a_prize_requirement(
    client, category, landing_type
):
    """`required_minimum_prize`/`is_underfunded`는 유료 경로에서만 뜻이 있다 —
    무료 공모전은 요구형태를 바꿔도 항상 0/False로 남는다(#415). 그렇지 않으면
    상금(prize=0)이 그 사이 「최소 상금 미달」로 조용히 읽힌다."""

    other_type = DeliverableType.objects.create(
        name="다른 요구형태-무료", minimum_prize=300_000
    )
    user = _hosted_user(client, "free-host-brief-edit-types")
    root = _operator_client("root-free-host-brief-edit-types")
    _grant(root, user["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    ).json()
    assert draft["required_minimum_prize"] == 0
    assert draft["is_underfunded"] is False

    resp = client.patch(
        f"{CONTESTS_URL}/{draft['id']}",
        data={"deliverable_type_ids": [landing_type.id, other_type.id]},
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["required_minimum_prize"] == 0
    assert body["is_underfunded"] is False

    stored = Contest.objects.get(id=draft["id"])
    assert stored.required_minimum_prize == 0
    assert stored.is_underfunded is False


def test_creating_free_contest_requires_a_deliverable_type(client, category, landing_type):
    user = _hosted_user(client, "free-host-no-deliverable")
    root = _operator_client("root-free-host-no-deliverable")
    _grant(root, user["user_id"])

    payload = _free_brief(category, landing_type)
    payload["deliverable_type_ids"] = []

    response = client.post(
        f"{CONTESTS_URL}/free",
        data=payload,
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert response.status_code == 422, response.content


# --- 「내 공모전」의 다음 행동 — 무료 draft 는 결제가 아니라 공개를 가리킨다
# (#415 회귀, #417 을 걷다가 발견) ---------------------------------------------


def test_sponsor_next_action_for_a_free_draft_points_to_publishing_not_payment(
    client, category, landing_type
):
    """`Contest.Status.PAYABLE`은 "DRAFT 인가"만 묻는다 — 무료 draft 도 걸린다.
    구분하지 않으면 「내 공모전」이 존재하지 않는 결제 화면으로 링크를 건다."""

    user = _hosted_user(client, "free-host-sponsor-action")
    root = _operator_client("root-free-host-sponsor-action")
    _grant(root, user["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    ).json()

    response = client.get("/api/contests/mine", **_auth_header(user["access"]))
    assert response.status_code == 200, response.content
    (row,) = [item for item in response.json()["items"] if item["contest_id"] == draft["id"]]
    assert row["next_action"] == "publish_free_draft"


# --- 스위치: 유료가 꺼져도 무료 개최·공개는 그대로 열린다 (#413/#415) ---------


@override_settings(PAID_CONTEST_PRODUCT_ENABLED=False)
def test_free_hosting_stays_open_when_only_the_paid_switch_is_off(
    client, category, landing_type
):
    user = _hosted_user(client, "free-host-paid-switch-off")
    root = _operator_client("root-free-host-paid-switch-off")
    _grant(root, user["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert draft.status_code == 200, draft.content

    published = client.post(
        f"{CONTESTS_URL}/{draft.json()['id']}/publish",
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert published.status_code == 200, published.content

    # 유료 경로(견적)는 계속 닫혀 있다 — 회귀 방지.
    quote_resp = client.post(
        f"{CONTESTS_URL}/quote",
        data={"deliverable_type_ids": [landing_type.id]},
        content_type="application/json",
    )
    assert quote_resp.status_code == 404


@override_settings(CONTEST_PRODUCT_ENABLED=False)
def test_free_hosting_closes_when_the_contest_switch_itself_is_off(
    client, category, landing_type
):
    user = _hosted_user(client, "free-host-contest-switch-off")

    response = client.post(
        f"{CONTESTS_URL}/free",
        data=_free_brief(category, landing_type),
        content_type="application/json",
        **_auth_header(user["access"]),
    )
    assert response.status_code == 404, response.content
