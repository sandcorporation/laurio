"""유료 공모전 스위치 (#413, ADR-0048) — 공모전은 켜진 채 유료 경로만 닫는다.

`tests/test_contest_product_switch.py`가 공모전 스위치 전체가 꺼진 상태를 보는
반면, 이 파일은 그 스위치를 나눈 뒤의 **중간 상태**(공모전 켜짐·유료 꺼짐 — 이제
prod의 기본값이다, ADR-0048)를 본다. 좋은 테스트는 구현이 아니라 결과를
본다는 같은 원칙(`CLAUDE.md` "HTTP가 유일한 시임이다")을 따른다.

1. **유료만 닫힌 표면**: 견적·결제·본인확인이 필요한 유료 개최/재개최·유료
   심사기간 연장이 404다.
2. **공모전 표면은 그대로 열림**: 목록·상세·홈 큐레이션·조회수·내 공모전 목록이
   200이다 — 유료를 더 닫아도 공모전 자체가 덩달아 닫히면 안 된다.
3. **스캔 등록**: 유료 전용 스캔만 등록부에서 사라지고, 공모전 전이 스캔
   (`contest-close`·`contest-judging-end`)과 채점은 남는다.

**켠 상태(기본값)의 회귀는 이 파일이 다시 확인하지 않는다** — 기존 스위트가 둘 다
켠 채로 돌므로 그 자체가 증거다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"

pytestmark = pytest.mark.django_db

PAID_OFF = override_settings(PAID_CONTEST_PRODUCT_ENABLED=False)


def _login(client, uid="user-1", email=None):
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


def _verify(client, access: str, ci: str = "sponsor-ci-1") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|sponsor-di-1"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


@pytest.fixture
def category(db):
    return Category.objects.create(name="엔터테인먼트")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


@pytest.fixture
def published_contest(db, category, landing_type):
    from accounts.models import SponsorProfile
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create(username="paid-off-sponsor")
    sponsor = SponsorProfile.objects.create(user=user)
    contest = Contest.objects.create(
        sponsor=sponsor,
        title="이미 열려 있는 공모전",
        category=category,
        prize=1_000_000,
        deadline_at=timezone.now() + timezone.timedelta(days=30),
        status=Contest.Status.PUBLISHED,
        required_minimum_prize=landing_type.minimum_prize,
    )
    contest.deliverable_types.set([landing_type])
    return contest


# --- 1. 유료만 닫힌 표면 -------------------------------------------------


@PAID_OFF
def test_paid_off_closes_quote_and_hosting(client, category, landing_type):
    pair = _login(client, uid="sponsor-paid-off-1")
    _verify(client, pair["access"], ci="sponsor-ci-paid-off-1")
    headers = _auth_header(pair["access"])

    assert (
        client.post(
            f"{CONTESTS_URL}/quote",
            data={"deliverable_type_ids": [landing_type.id]},
            content_type="application/json",
        ).status_code
        == 404
    )

    create_response = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 꺼진 동안의 개최 시도",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 404


@PAID_OFF
def test_paid_off_closes_reopen_and_judging_extension(client, published_contest):
    pair = _login(client, uid="paid-off-sponsor")
    headers = _auth_header(pair["access"])

    reopen_response = client.post(
        f"{CONTESTS_URL}/{published_contest.id}/reopen",
        data={"prize": 1_000_000, "deadline_at": "2030-01-01T00:00:00Z"},
        content_type="application/json",
        **headers,
    )
    assert reopen_response.status_code == 404

    assert (
        client.post(
            f"{CONTESTS_URL}/{published_contest.id}/extend-judging-period",
            data={},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )

    import uuid

    assert (
        client.post(
            f"{CONTESTS_URL}/{published_contest.id}/extend-judging-period/{uuid.uuid4()}/confirm",
            data={},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )


@PAID_OFF
def test_paid_off_closes_payment_initiate_and_confirm(client, published_contest):
    from payments.models import Payment

    pair = _login(client, uid="paid-off-sponsor")
    headers = _auth_header(pair["access"])

    assert (
        client.post(
            PAYMENTS_URL,
            data={"contest_id": published_contest.id},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )

    payment = Payment.objects.create(
        contest=published_contest,
        prize_amount=published_contest.prize,
        listing_fee_amount=0,
        status=Payment.Status.REQUESTED,
    )
    confirm_response = client.post(
        f"{PAYMENTS_URL}/{payment.order_id}/confirm",
        data={},
        content_type="application/json",
        **headers,
    )
    assert confirm_response.status_code == 404


# --- 2. 공모전 표면은 그대로 열림 ------------------------------------------


@PAID_OFF
def test_paid_off_keeps_contest_browsing_surfaces_open(client, published_contest):
    assert client.get(CONTESTS_URL).status_code == 200
    assert client.get(f"{CONTESTS_URL}/home").status_code == 200
    assert client.get(f"{CONTESTS_URL}/{published_contest.id}").status_code == 200
    assert client.post(f"{CONTESTS_URL}/{published_contest.id}/views").status_code == 200


@PAID_OFF
def test_paid_off_keeps_my_contests_open(client, published_contest):
    pair = _login(client, uid="paid-off-sponsor")
    headers = _auth_header(pair["access"])
    response = client.get(f"{CONTESTS_URL}/mine", **headers)
    assert response.status_code == 200


# --- 3. 스캔 등록 ----------------------------------------------------------


PAID_ONLY_SCAN_NAMES = (
    "payment-refund-request",
    "payment-refund-reconcile",
    "distribution-create",
    "distribution-share-payout",
    "payout-awaits-you",
    "seller-registration-recovery",
    "handover-release",
)

CONTEST_SHARED_SCAN_NAMES = (
    "submission-scoring",
    "repository-visibility",
    "contest-close",
    "contest-judging-end",
)


@PAID_OFF
def test_paid_off_removes_only_paid_scans_from_tick():
    response = _client_post_tick()
    scans = response.json()["scans"]
    for name in PAID_ONLY_SCAN_NAMES:
        assert name not in scans, f"{name} 가 유료 스위치 꺼진 tick 에 여전히 나온다"
    for name in CONTEST_SHARED_SCAN_NAMES:
        assert name in scans, f"{name} 가 유료 스위치만 꺼졌는데 tick 에서 사라졌다"


@PAID_OFF
@pytest.mark.parametrize("name", PAID_ONLY_SCAN_NAMES)
def test_paid_off_rejects_direct_scan_call_as_unregistered(client, name):
    response = client.post(f"/api/internal/scans/{name}", **_internal_headers())
    assert response.status_code == 404


def test_on_by_default_keeps_paid_only_scans_registered():
    response = _client_post_tick()
    scans = response.json()["scans"]
    for name in PAID_ONLY_SCAN_NAMES:
        assert name in scans, f"{name} 가 기본값(켜짐)에서 등록부에 없다"


def _client_post_tick():
    from django.test import Client

    client = Client()
    response = client.post("/api/internal/tick", **_internal_headers())
    assert response.status_code == 200, response.content
    return response
