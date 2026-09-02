"""Payout 실행 — 토스 어댑터 · 멱등키 · 웹훅 · 신원 대기 (#15, ADR-0004, ADR-0007/0008).

핵심 대상:

- Escrow가 해제된(Handover.status==released) Contest에 대해서만 Developer가
  지급을 요청할 수 있다. 요청에는 멱등키가 붙고 재시도해도 새 Payout이 생기지
  않는다.
- 지급 확정 시 플랫폼 수수료·원천징수 공제가 분개로 남고, 원천징수는 예수금
  계정에 계상된다.
- 지급 API 타임아웃 후 실제로는 성공한 경우 조회로 확정하고 중복 지급하지 않는다
  (분개가 한 번만 남는다).
- `payout.changed` 웹훅으로 결과가 반영되고, 같은 웹훅을 두 번 받아도 한 번만
  반영된다.
- 주민등록번호는 지급이 확정된 뒤에만 받고, 별도 암호화 테이블에 평문이 아닌
  형태로 저장된다.
- 신원정보가 없으면 "지급 확정·신원 대기" 상태가 되고, 금액은 원장에 개발자
  미지급금으로 남아 사라지지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from handovers.models import Handover
from ledger.services import contest_entries
from payouts.adapters import FakePayoutAdapter, FakeSellerAdapter, SellerRegistrationResult
from payouts.models import Payout, Seller, TaxIdentity

TICK_URL = "/api/internal/tick"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SUBMISSIONS_URL = "/api/submissions"
PAYOUTS_URL = "/api/payouts"


# --- 헬퍼 (test_handover.py와 같은 형식) ----------------------------------------


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _unfreeze():
    """ClockOverride는 단일 행(pk=1)이라 한 Contest를 닫으며 건 고정이 그대로
    남아 있으면, 뒤이어 같은 테스트 안에서 실제 지금 시각 기준 마감을 가진 두
    번째 Contest에 제출이 "마감 지남"으로 막힌다. 독립된 두 번째
    `_ready_for_payout` 사이클을 시작하기 전에 실제 시각으로 되돌린다."""

    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": None})


def _login(client, uid="dev-1", email=None):
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


def _verify(client, access: str, *, ci: str, name: str = "사람", birth: str = "1995-01-01") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"{name}|{birth}|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def _verified_user(client, uid: str, ci: str) -> dict:
    pair = _login(client, uid=uid)
    _verify(client, pair["access"], ci=ci)
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200
    return {"access": pair["access"], "user_id": me.json()["id"]}


def _sign_payment(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _sign_payout(*, webhook_id: str, idempotency_key: str, status: str) -> str:
    key = settings.PAYOUT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{idempotency_key}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _publish_contest(
    client, *, category, deliverable_type, sponsor_uid="sponsor-1", deadline_at=None, prize=1_000_000
) -> tuple[dict, dict]:
    sponsor = _verified_user(client, sponsor_uid, f"{sponsor_uid}-ci")
    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))

    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{sponsor_uid}의 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "prize": prize,
            "deadline_at": deadline_at.isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 200, response.content
    contest = response.json()

    payment_resp = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert payment_resp.status_code == 201
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}-{uuid.uuid4().hex}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign_payment(
        webhook_id=webhook_id, order_id=payment["order_id"], status="paid"
    )
    webhook_resp = client.post(
        f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json"
    )
    assert webhook_resp.status_code == 200

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    contest = detail.json()
    assert contest["status"] == "published"
    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, dev: dict, contest_id: int) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": _source_object_key(contest_id, dev["user_id"]),
            "requirement_responses": [],
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


def _award(client, sponsor: dict, contest_id: int, submission_id: int) -> dict:
    resp = client.post(
        f"{CONTESTS_URL}/{contest_id}/award",
        data={"submission_id": submission_id},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 200, resp.content
    return resp.json()


def _accept_handover(client, sponsor: dict, contest_id: int) -> dict:
    resp = client.post(
        f"{CONTESTS_URL}/{contest_id}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert resp.status_code == 200, resp.content
    return resp.json()


def _ready_for_payout(
    client, category, landing_type, *, sponsor_uid="sponsor-1", dev_uid="dev-1", prize=1_000_000
):
    """Escrow까지 해제된 Contest 하나를 만들어 (sponsor, dev, contest, submission)를
    돌려준다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid=sponsor_uid, deadline_at=deadline, prize=prize,
    )
    dev = _verified_user(client, dev_uid, f"{dev_uid}-ci")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    _award(client, sponsor, contest["id"], submission["id"])
    _accept_handover(client, sponsor, contest["id"])
    return sponsor, dev, contest, submission


def _request_payout(client, dev: dict, contest_id: int) -> dict:
    resp = client.post(f"{CONTESTS_URL}/{contest_id}/payout", **_auth_header(dev["access"]))
    assert resp.status_code == 201, resp.content
    return resp.json()


def _confirm_payout(client, dev: dict, idempotency_key: str, *, simulate=None, seller_simulate=None):
    body = {}
    if simulate is not None:
        body["simulate"] = simulate
    if seller_simulate is not None:
        body["seller_simulate"] = seller_simulate
    return client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/confirm",
        data=body,
        content_type="application/json",
        **_auth_header(dev["access"]),
    )


def _retry_seller_registration(client, dev: dict, idempotency_key: str, *, simulate=None):
    return client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/seller-registration",
        data={"simulate": simulate} if simulate is not None else {},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )


def _operator_client(username="payouts-op-1", *, superuser=False):
    """로그인된 Operator 용 클라이언트 (test_appeals._operator_client와 같은 관용구)."""

    from django.core.management import call_command
    from django.test import Client

    password = "Zx82!Laurio-Payouts-Secret"
    call_command("create_operator", username, password=password, superuser=superuser)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": password},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert response.status_code == 200, response.content
    return operator


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 요청 게이팅 · 멱등성 -------------------------------------------------------


@pytest.mark.django_db
def test_cannot_request_payout_before_escrow_released(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-1-ci")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    _award(client, sponsor, contest["id"], submission["id"])
    # Handover accept를 하지 않는다 — Escrow가 아직 해제되지 않았다.

    resp = client.post(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_only_awarded_developer_can_request_payout(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    stranger = _verified_user(client, "stranger-1", "stranger-ci-1")

    resp = client.post(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(stranger["access"]))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_payout_request_computes_fee_and_withholding_breakdown(client, category, landing_type):
    """기본 정책(수수료 10%, 원천징수 4.4%)에서 1,000,000원 상금의 공제액을
    손으로 계산한 값과 비교한다(#75) — 코드의 계산식을 재현하지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)

    payout = _request_payout(client, dev, contest["id"])

    assert payout["prize_amount"] == 1_000_000
    assert payout["platform_fee_amount"] == 100_000
    assert payout["withholding_tax_amount"] == 44_000
    assert payout["net_amount"] == 856_000
    assert payout["status"] == "requested"


@pytest.mark.django_db
def test_withholding_tax_is_4_4_percent_of_paid_amount_not_3_3_percent(
    client, category, landing_type
):
    """국세청 기준 공모전 상금(기타소득, 필요경비 80%)의 원천징수는 지급액의
    4.4%다 — 사업소득 세율인 3.3%가 아니다(#73/#75). 5,000,000원 상금에서
    3.3%(165,000원)와 4.4%(220,000원)는 55,000원 차이가 나므로, 이 값 하나가
    이전 세율 사용 여부를 갈라낸다."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, prize=5_000_000
    )

    payout = _request_payout(client, dev, contest["id"])

    assert payout["withholding_tax_amount"] == 220_000
    assert payout["withholding_tax_amount"] != 165_000  # 3.3% — 옛 세율은 아니다.
    assert payout["net_amount"] == 5_000_000 - payout["platform_fee_amount"] - 220_000


# --- 과세최저한 경계값(250,000원) -------------------------------------------------


@pytest.mark.django_db
def test_withholding_is_zero_at_or_below_250000_won_and_nonzero_above_it(
    client, category, landing_type
):
    """과세최저한(기타소득금액 5만원 이하 = 지급액 250,000원 이하)에서는
    원천징수가 없다. 250,000원 자체를 포함해 경계 셋(그 아래·그 값·그 위)을
    모두 친다(#75) — 코드와 테스트가 경계의 같은 쪽에 서야 한다."""

    _, dev_below, contest_below, _ = _ready_for_payout(
        client, category, landing_type, dev_uid="dev-below", prize=249_999
    )
    payout_below = _request_payout(client, dev_below, contest_below["id"])
    assert payout_below["withholding_tax_amount"] == 0
    assert payout_below["net_amount"] == 249_999 - payout_below["platform_fee_amount"]

    _unfreeze()
    _, dev_at, contest_at, _ = _ready_for_payout(
        client, category, landing_type, dev_uid="dev-at", prize=250_000
    )
    payout_at = _request_payout(client, dev_at, contest_at["id"])
    assert payout_at["withholding_tax_amount"] == 0

    _unfreeze()
    _, dev_above, contest_above, _ = _ready_for_payout(
        client, category, landing_type, dev_uid="dev-above", prize=250_001
    )
    payout_above = _request_payout(client, dev_above, contest_above["id"])
    assert payout_above["withholding_tax_amount"] == 11_000
    assert payout_above["withholding_tax_amount"] > 0


# --- Payout이 적용된 요율을 스냅샷에 기록한다 -------------------------------------


@pytest.mark.django_db
def test_payout_records_the_platform_fee_and_withholding_rate_it_applied(
    client, category, landing_type
):
    """Payout은 금액만이 아니라 적용된 요율 자체(bp 단위)를 자기 안에 기록한다
    (#75, ADR-0023) — 상금이 다르면 금액에서 요율을 역산할 수 없다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.platform_fee_bps == 1000
    assert payout.withholding_tax_bps == 440


@pytest.mark.django_db
def test_changing_the_policy_changes_new_payouts_but_not_past_ones(
    client, category, landing_type
):
    """정책의 요율을 바꾼 뒤: 새 Payout의 공제는 달라지고, 이미 만들어진
    Payout의 금액과 기록된 요율은 그대로다(#75) — 스냅샷이 실제로 스냅샷인지를
    묻는다. "요율 필드가 있다"에서 멈추지 않고 요율을 실제로 바꿔 확인한다.

    #76부터는 운영자 API로 바꾼다 — 직접 ORM을 건드리지 않는다(CLAUDE.md의
    HTTP 시임 하나 규율)."""

    # 정책을 건드리기 전에 만든 Payout — 기본값(수수료 10%, 원천징수 4.4%).
    sponsor_a, dev_a, contest_a, _ = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-a", dev_uid="dev-a"
    )
    before = _request_payout(client, dev_a, contest_a["id"])
    payout_before = Payout.objects.get(idempotency_key=before["idempotency_key"])
    assert payout_before.platform_fee_amount == 100_000
    assert payout_before.withholding_tax_amount == 44_000
    assert payout_before.platform_fee_bps == 1000
    assert payout_before.withholding_tax_bps == 440

    # 상위 등급 Operator가 운영자 API로 요율을 바꾼다.
    root = _operator_client("policy-root-1", superuser=True)
    current = root.get("/api/operator/policy", HTTP_ORIGIN="http://testserver")
    assert current.status_code == 200, current.content
    changed = root.post(
        "/api/operator/policy",
        data={
            "platform_fee_bps": 1500,
            "withholding_tax_bps": 500,
            "reason": "요율 조정 테스트(#76)",
            "expected_version": current.json()["version"],
        },
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert changed.status_code == 200, changed.content

    # 정책 변경 이후에 만든 새 Payout — 새 요율이 적용된다.
    _unfreeze()
    sponsor_b, dev_b, contest_b, _ = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-b", dev_uid="dev-b"
    )
    after = _request_payout(client, dev_b, contest_b["id"])
    payout_after = Payout.objects.get(idempotency_key=after["idempotency_key"])
    assert payout_after.platform_fee_amount == 150_000  # 1,000,000 * 15%
    assert payout_after.withholding_tax_amount == 50_000  # 1,000,000 * 5%
    assert payout_after.platform_fee_bps == 1500
    assert payout_after.withholding_tax_bps == 500

    # 정책 변경이 과거 Payout을 흔들지 않는다 — 금액도, 기록된 요율도 그대로다.
    payout_before.refresh_from_db()
    assert payout_before.platform_fee_amount == 100_000
    assert payout_before.withholding_tax_amount == 44_000
    assert payout_before.platform_fee_bps == 1000
    assert payout_before.withholding_tax_bps == 440


@pytest.mark.django_db
def test_platform_policy_row_is_created_with_defaults_on_first_use(
    client, category, landing_type
):
    """PlatformPolicy 행이 없는 신선한 DB에서도 부팅과 첫 요청이 그냥
    동작한다(#75) — 행이 없으면 기본값으로 만들어진다."""

    from policies.models import PlatformPolicy

    assert PlatformPolicy.objects.count() == 0

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    payout = _request_payout(client, dev, contest["id"])

    assert payout["platform_fee_amount"] == 100_000
    assert payout["withholding_tax_amount"] == 44_000

    policy = PlatformPolicy.objects.get(pk=1)
    assert policy.platform_fee_bps == 1000
    assert policy.withholding_tax_bps == 440


# --- 코드리뷰 지적 반영 (#75 후속) -------------------------------------------------


@pytest.mark.django_db
def test_platform_policy_rejects_a_fee_bps_above_the_sane_upper_bound(db):
    """요율에 상한이 없으면 `platform_fee_bps=12000`(120%) 같은 오입력이
    저장되고, 한참 뒤 지급 요청 도중 `net_amount`가 음수라 500으로 죽는다 —
    원인이 여기(정책 저장 시점)인데 증상은 지급 경로에서 나타난다. 값을 바꾸는
    경로가 지금은 shell뿐이라(#76 전) 모델 자신이 막아야 한다.

    상한 CheckConstraint를 없애면 이 테스트가 빨간불이 된다 — 저장이 그냥
    성공해버리기 때문이다."""

    from django.db import IntegrityError, transaction

    from policies.models import PlatformPolicy

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformPolicy.objects.create(platform_fee_bps=12_000, withholding_tax_bps=440)


@pytest.mark.django_db
def test_platform_policy_rejects_fee_plus_withholding_bps_above_10000(db):
    """개별 상한 안에 있어도 둘의 합이 10000bp(100%)를 넘으면 net_amount가
    음수가 될 수 있다 — 합 제약이 따로 필요하다."""

    from django.db import IntegrityError, transaction

    from policies.models import PlatformPolicy

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            # 개별 상한(9000) 안이지만 합이 10000을 넘는다.
            PlatformPolicy.objects.create(platform_fee_bps=6_000, withholding_tax_bps=5_000)


@pytest.mark.django_db
def test_invalid_policy_never_reaches_the_payout_request_path(
    client, category, landing_type
):
    """CheckConstraint가 막아 상한 초과 값이 애초에 저장되지 않으므로, 지급
    요청 경로가 (수정 전처럼) 중단된 트랜잭션 안에서 재조회하다
    TransactionManagementError로 원인이 덮이는 500을 만날 일이 없다 — 정상
    상태(1000/440)에서 지급 요청이 여전히 200대로 끝난다는 것으로 그 경로가
    깨지지 않았음을 확인한다."""

    from policies.models import PlatformPolicy

    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformPolicy.objects.create(pk=1, platform_fee_bps=12_000, withholding_tax_bps=440)

    # 위 시도가 거부되어 정책 행은 여전히 없다(또는 기본값이다) — 지급 요청은
    # 정상적으로 200대로 끝난다.
    assert not PlatformPolicy.objects.filter(pk=1).exists()

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    payout = _request_payout(client, dev, contest["id"])
    assert payout["status"] == "requested"


@pytest.mark.django_db
def test_exempt_payout_records_zero_bps_and_an_explicit_exempt_flag_not_the_nominal_rate(
    client, category, landing_type
):
    """과세최저한으로 원천징수가 0원인데 정책의 명목 요율(440)을 그대로
    기록하면 "4.4%를 적용했다"는 기록과 "0원 뗐다"는 금액이 모순된다 — 나중에
    이 스냅샷으로 원천징수 명세를 만들면 뗀 적 없는 세금을 보고하게 된다.
    1/N 배분 몫은 250,000원 이하가 흔하므로 엣지 케이스가 아니다.

    적용된 bps를 0으로 되돌리면(면제인데도 정책의 명목 요율을 그대로 기록하면)
    이 테스트가 빨간불이 된다."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, prize=250_000
    )
    requested = _request_payout(client, dev, contest["id"])
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])

    assert payout.withholding_tax_amount == 0
    assert payout.withholding_exempt is True
    assert payout.withholding_tax_bps == 0  # 정책의 명목 요율(440)이 아니다.
    # 수수료는 면제 대상이 아니므로 그대로 기록된다 — 면제는 원천징수에만 적용.
    assert payout.platform_fee_bps == 1000


@pytest.mark.django_db
def test_non_exempt_payout_still_records_the_nominal_withholding_rate(
    client, category, landing_type
):
    """면제가 아닌 정상 케이스에서는 정책의 명목 요율이 그대로 기록되고
    withholding_exempt는 False다 — 위 면제 테스트와 대조."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, prize=1_000_000
    )
    requested = _request_payout(client, dev, contest["id"])
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])

    assert payout.withholding_tax_amount == 44_000
    assert payout.withholding_exempt is False
    assert payout.withholding_tax_bps == 440


@pytest.mark.django_db
def test_exempt_threshold_does_not_move_when_only_the_withholding_rate_changes(
    client, category, landing_type
):
    """원천징수 면제 임계값(250,000원)은 원천징수율(`withholding_tax_bps`)이
    아니라 필요경비율(`withholding_necessary_expense_bps`)에서만 유도된다 —
    누가 원천징수율만 330(사업소득 세율)으로 바꿔도, 그 값이 면제 임계값에
    관여하지 않으므로 250,000원 이하 건은 여전히 면제된다. 임계값이
    withholding_tax_bps에서 유도되도록(수정 전 상태로) 되돌리면 이 테스트가
    빨간불이 된다 — 330bp에서는 250,000 * 330 // 10000 = 8,250원이 걷혀
    withholding_tax_amount가 0이 아니게 된다."""

    from policies.models import PlatformPolicy

    # 원천징수율만 바꾼다 — 필요경비율(80%)은 그대로 둔다.
    PlatformPolicy.objects.update_or_create(pk=1, defaults={"withholding_tax_bps": 330})

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, prize=250_000
    )
    requested = _request_payout(client, dev, contest["id"])
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])

    assert payout.withholding_tax_amount == 0
    assert payout.withholding_exempt is True

    # 임계값 바로 위(250,001원)에서는 여전히 새 요율(330bp)로 걷힌다 —
    # 임계값 자체는 그대로이면서 요율만 바뀌었다는 것을 함께 증명한다.
    _unfreeze()
    _, dev2, contest2, _ = _ready_for_payout(
        client, category, landing_type, dev_uid="dev-330", prize=250_001
    )
    requested2 = _request_payout(client, dev2, contest2["id"])
    payout2 = Payout.objects.get(idempotency_key=requested2["idempotency_key"])
    assert payout2.withholding_tax_amount == 250_001 * 330 // 10_000
    assert payout2.withholding_exempt is False
    assert payout2.withholding_tax_bps == 330


@pytest.mark.django_db
def test_repeated_payout_requests_reuse_the_same_idempotency_key_and_no_duplicate_payout(
    client, category, landing_type
):
    """지급 요청에 멱등키가 붙고 재시도해도 중복 지급되지 않는다 (AC #4)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)

    first = _request_payout(client, dev, contest["id"])
    second = _request_payout(client, dev, contest["id"])
    third = _request_payout(client, dev, contest["id"])

    assert first["idempotency_key"] == second["idempotency_key"] == third["idempotency_key"]
    assert Payout.objects.filter(handover__award__contest_id=contest["id"]).count() == 1

    # 확정까지 여러 번 재시도해도 원장 분개는 한 번만 남는다.
    _confirm_payout(client, dev, first["idempotency_key"])
    _confirm_payout(client, dev, first["idempotency_key"])
    _confirm_payout(client, dev, first["idempotency_key"])

    payout = Payout.objects.get(idempotency_key=first["idempotency_key"])
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == payout.journal_entry_id
    ]
    assert len(entries) == 1


# --- 확정 · 원장 분개 -----------------------------------------------------------


@pytest.mark.django_db
def test_confirm_posts_fee_and_withholding_ledger_entry_with_withholding_to_payable_account(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.status_code == 200
    body = confirm_resp.json()
    assert body["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.journal_entry_id is not None

    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == payout.journal_entry_id
    ]
    assert len(entries) == 1
    entry = entries[0]
    lines = list(entry.lines.all())

    withholding_lines = [
        l for l in lines if l.account == "withholding_tax_payable" and l.side == "credit"
    ]
    assert len(withholding_lines) == 1
    assert withholding_lines[0].amount == payout.withholding_tax_amount

    fee_lines = [l for l in lines if l.account == "platform_fee_revenue" and l.side == "credit"]
    assert len(fee_lines) == 1
    assert fee_lines[0].amount == payout.platform_fee_amount

    debit_total = sum(l.amount for l in lines if l.side == "debit")
    credit_total = sum(l.amount for l in lines if l.side == "credit")
    assert debit_total == credit_total
    assert debit_total == payout.platform_fee_amount + payout.withholding_tax_amount


@pytest.mark.django_db
def test_confirm_timeout_resolves_via_query_status_and_posts_entry_once(
    client, category, landing_type
):
    """타임아웃 후 실제로는 성공한 경우 조회로 확정하고 중복 지급하지 않는다 (AC #5)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(
        client, dev, requested["idempotency_key"], simulate="timeout_then_success"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == payout.journal_entry_id
    ]
    assert len(entries) == 1


@pytest.mark.django_db
def test_confirm_failed_leaves_no_ledger_entry(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(client, dev, requested["idempotency_key"], simulate="failed")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.journal_entry_id is None


@pytest.mark.django_db
def test_payout_can_be_retried_after_failure_and_previous_attempt_stays_failed(
    client, category, landing_type
):
    """FAILED로 끝난 시도가 재시도를 영구히 막지 않는다 — 그렇지 않으면 토스가
    거절한 순간 상금이 Escrow에 영구히 갇힌다(리뷰 지적 1)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)

    first = _request_payout(client, dev, contest["id"])
    failed_resp = _confirm_payout(client, dev, first["idempotency_key"], simulate="failed")
    assert failed_resp.status_code == 200
    assert failed_resp.json()["status"] == "failed"

    # 재시도 — 실패한 시도와 다른(새) idempotency_key를 받는다.
    second = _request_payout(client, dev, contest["id"])
    assert second["idempotency_key"] != first["idempotency_key"]
    assert second["status"] == "requested"

    # 실패한 첫 시도는 실패인 채로 그대로 남는다 — 되돌아가는 상태 전이가 아니다.
    first_payout = Payout.objects.get(idempotency_key=first["idempotency_key"])
    assert first_payout.status == Payout.Status.FAILED

    # 재요청은 새 idempotency_key로 새 REQUESTED 행을 만든다 — 실패한 시도를
    # 덮어쓰지 않는다. Handover 당 두 행(실패 하나 + 새로 요청된 하나)이
    # 존재해야 한다.
    assert Payout.objects.filter(handover__award__contest_id=contest["id"]).count() == 2

    # 재시도한 지급은 정상적으로 확정되어 원장에 분개가 남는다.
    confirm_resp = _confirm_payout(client, dev, second["idempotency_key"])
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "confirmed_identity_pending"

    second_payout = Payout.objects.get(idempotency_key=second["idempotency_key"])
    assert second_payout.journal_entry_id is not None

    # GET은 가장 최근(재시도로 살아있는) 시도를 돌려준다 — 이미 실패한 첫 시도가
    # 아니라.
    get_resp = client.get(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert get_resp.status_code == 200
    assert get_resp.json()["idempotency_key"] == second["idempotency_key"]


@pytest.mark.django_db
def test_repeated_requests_while_active_do_not_create_a_third_payout(
    client, category, landing_type
):
    """활성(REQUESTED) 시도가 있는 동안 재요청은 새 행을 만들지 않는다 — 실패
    이후에만 새 시도가 허용된다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)

    first = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, first["idempotency_key"], simulate="failed")

    second = _request_payout(client, dev, contest["id"])
    third = _request_payout(client, dev, contest["id"])

    assert second["idempotency_key"] == third["idempotency_key"]
    assert Payout.objects.filter(handover__award__contest_id=contest["id"]).count() == 2


# --- payout.changed 웹훅 ---------------------------------------------------------


@pytest.mark.django_db
def test_webhook_confirms_payout_and_posts_ledger_entry(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    webhook_id = f"payout-wh-{uuid.uuid4().hex}"
    body = {
        "webhook_id": webhook_id,
        "idempotency_key": requested["idempotency_key"],
        "status": "paid",
    }
    body["signature"] = _sign_payout(
        webhook_id=webhook_id, idempotency_key=requested["idempotency_key"], status="paid"
    )
    resp = client.post(f"{PAYOUTS_URL}/webhook", data=body, content_type="application/json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.journal_entry_id is not None


@pytest.mark.django_db
def test_redelivered_webhook_applies_once(client, category, landing_type):
    """같은 웹훅을 두 번 받아도 한 번만 반영된다 (AC #6)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    webhook_id = f"payout-wh-{uuid.uuid4().hex}"
    body = {
        "webhook_id": webhook_id,
        "idempotency_key": requested["idempotency_key"],
        "status": "paid",
    }
    body["signature"] = _sign_payout(
        webhook_id=webhook_id, idempotency_key=requested["idempotency_key"], status="paid"
    )
    first = client.post(f"{PAYOUTS_URL}/webhook", data=body, content_type="application/json")
    second = client.post(f"{PAYOUTS_URL}/webhook", data=body, content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 200

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == payout.journal_entry_id
    ]
    assert len(entries) == 1


@pytest.mark.django_db
def test_webhook_rejects_missing_or_wrong_signature(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    body = {
        "webhook_id": "wh-no-sig",
        "idempotency_key": requested["idempotency_key"],
        "status": "paid",
        "signature": "not-the-real-signature",
    }
    resp = client.post(f"{PAYOUTS_URL}/webhook", data=body, content_type="application/json")
    assert resp.status_code == 401

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.REQUESTED
    assert payout.journal_entry_id is None


@pytest.mark.django_db
def test_webhook_arriving_before_sync_confirm_still_confirms_exactly_once(
    client, category, landing_type
):
    """웹훅이 동기 confirm보다 먼저 도착해도 결과는 같고, 분개는 한 번만 남는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    webhook_id = f"payout-wh-{uuid.uuid4().hex}"
    body = {
        "webhook_id": webhook_id,
        "idempotency_key": requested["idempotency_key"],
        "status": "paid",
    }
    body["signature"] = _sign_payout(
        webhook_id=webhook_id, idempotency_key=requested["idempotency_key"], status="paid"
    )
    webhook_resp = client.post(f"{PAYOUTS_URL}/webhook", data=body, content_type="application/json")
    assert webhook_resp.status_code == 200

    confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == payout.journal_entry_id
    ]
    assert len(entries) == 1


# --- 신원 · 미지급금 잔존 --------------------------------------------------------


@pytest.mark.django_db
def test_confirmed_without_identity_is_identity_pending_and_amount_stays_as_developer_payable(
    client, category, landing_type
):
    """신원정보가 없으면 '지급 확정·신원 대기' 상태가 되고 금액이 미지급금으로
    남는다 (AC #8)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
    assert not TaxIdentity.objects.filter(payout=payout).exists()

    from ledger.services import contest_balance

    balance = contest_balance(Contest.objects.get(id=contest["id"]).ledger_id)
    assert balance["is_balanced"] is True

    lines = [line for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id) for line in e.lines.all()]
    developer_payable_credit = sum(
        l.amount for l in lines if l.account == "developer_payable" and l.side == "credit"
    )
    developer_payable_debit = sum(
        l.amount for l in lines if l.account == "developer_payable" and l.side == "debit"
    )
    outstanding = developer_payable_credit - developer_payable_debit
    assert outstanding == payout.net_amount


@pytest.mark.django_db
def test_identity_cannot_be_submitted_before_payout_confirmed(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_identity_submission_finalizes_payout_and_is_encrypted_in_separate_table(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    rrn = "9001011234567"
    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": rrn},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED

    identity = TaxIdentity.objects.get(payout=payout)
    assert identity.resident_registration_number_encrypted != rrn
    assert rrn not in identity.resident_registration_number_encrypted

    from verification.crypto import decrypt

    assert decrypt(identity.resident_registration_number_encrypted) == rrn


@pytest.mark.django_db
def test_repeated_identity_submission_is_idempotent(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    rrn = "9001011234567"
    first = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": rrn},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    second = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": rrn},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert first.status_code == 200
    assert second.status_code == 200

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert TaxIdentity.objects.filter(payout=payout).count() == 1


@pytest.mark.django_db
def test_identity_rejects_non_digit_or_wrong_length_values_with_422(client, category, landing_type):
    """길이만 보고 통과시키면 공백·기호가 섞인 13글자도 암호화되어 저장된다
    (리뷰 지적 4) — 숫자 13자리만 통과해야 한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    for bad_value in ["90010112345a", "9001-0112345", "900101123456", "90010112345678"]:
        resp = client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": bad_value},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )
        assert resp.status_code == 422, (bad_value, resp.content)

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert not TaxIdentity.objects.filter(payout=payout).exists()


@pytest.mark.django_db
def test_identity_can_be_corrected_after_a_typo(client, category, landing_type):
    """오타로 잘못 제출한 주민등록번호를 API로 정정할 수 있어야 한다(리뷰 지적
    4) — 이전 정책(이미 있으면 그대로 돌려주고 두 번째 값은 버림)은 오타를
    영영 못 고치게 만들었다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    typo = "9001011234567"
    corrected = "9001011234568"

    first = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": typo},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert first.status_code == 200

    second = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": corrected},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    identity = TaxIdentity.objects.get(payout=payout)
    assert TaxIdentity.objects.filter(payout=payout).count() == 1

    from verification.crypto import decrypt

    assert decrypt(identity.resident_registration_number_encrypted) == corrected


@pytest.mark.django_db
def test_other_developer_cannot_submit_identity_for_someone_elses_payout(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    stranger = _verified_user(client, "stranger-2", "stranger-ci-2")
    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **_auth_header(stranger["access"]),
    )
    assert resp.status_code == 403


# --- 조회 ------------------------------------------------------------------------


@pytest.mark.django_db
def test_developer_can_view_payout_breakdown(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    _request_payout(client, dev, contest["id"])

    resp = client.get(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert resp.status_code == 200
    body = resp.json()
    assert set(["prize_amount", "platform_fee_amount", "withholding_tax_amount", "net_amount"]) <= set(
        body.keys()
    )


@pytest.mark.django_db
def test_sponsor_cannot_view_developer_payout_breakdown(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    _request_payout(client, dev, contest["id"])

    resp = client.get(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(sponsor["access"]))
    assert resp.status_code == 403


# --- Seller 등록 — 지급 확정 후 등록과 두 대기의 구분 (#50, ADR-0020) -------------


@pytest.mark.django_db
def test_seller_registration_does_not_start_before_payout_is_confirmed(
    client, category, landing_type
):
    """제출·요청 시점에는 Seller가 아예 생기지 않는다 — 등록은 지급이 확정된
    뒤에만 시작된다(ADR-0020 핵심 규율)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert not Seller.objects.filter(developer_id=payout.handover.award.submission.developer_id).exists()

    _confirm_payout(client, dev, requested["idempotency_key"])

    assert Seller.objects.filter(
        developer_id=payout.handover.award.submission.developer_id
    ).exists()


@pytest.mark.django_db
def test_default_seller_registration_succeeds_and_reaches_identity_pending(
    client, category, landing_type
):
    """기본(시나리오 미지정) 등록은 즉시 부분 승인되어 기존 흐름(확정 즉시
    신원 대기)을 그대로 유지한다 — 회귀 방지용."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["seller_status"] == "partially_approved"


@pytest.mark.django_db
def test_seller_pending_is_a_distinct_state_from_identity_pending(client, category, landing_type):
    """「지급 확정 · Seller 대기」는 「지급 확정 · 신원 대기」와 다른 상태다
    (#50 AC) — 하나는 세무(주민등록번호), 하나는 지급대행사 수취인 등록을
    기다린다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(
        client, dev, requested["idempotency_key"], seller_simulate="review_required"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_seller_pending"
    assert body["status"] != "confirmed_identity_pending"
    assert body["seller_status"] == "under_review"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_SELLER_PENDING


@pytest.mark.django_db
def test_limit_exceeded_seller_registration_is_under_review_not_failed(
    client, category, landing_type
):
    """주간 한도를 넘으면 심사 대기이지 실패가 아니다(#50 AC) — 성공한
    Developer를 성공했다는 이유로 막지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(
        client, dev, requested["idempotency_key"], seller_simulate="limit_exceeded"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_seller_pending"
    assert body["status"] != "failed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status != Payout.Status.FAILED

    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status == Seller.Status.UNDER_REVIEW


@pytest.mark.django_db
def test_seller_rejection_leaves_confirmed_amount_in_the_ledger(client, category, landing_type):
    """등록이 거절되어도 확정된 금액은 원장에 개발자 미지급금으로 그대로
    남는다(#50 AC, ADR-0004) — 어느 경로로도 돈이 사라지지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="rejected")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_seller_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.journal_entry_id is not None

    from ledger.services import contest_balance, contest_entries

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    balance = contest_balance(ledger_id)
    assert balance["is_balanced"] is True

    lines = [line for e in contest_entries(ledger_id) for line in e.lines.all()]
    developer_payable_credit = sum(
        l.amount for l in lines if l.account == "developer_payable" and l.side == "credit"
    )
    developer_payable_debit = sum(
        l.amount for l in lines if l.account == "developer_payable" and l.side == "debit"
    )
    outstanding = developer_payable_credit - developer_payable_debit
    assert outstanding == payout.net_amount

    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status == Seller.Status.REJECTED


@pytest.mark.django_db
def test_identity_can_be_submitted_while_seller_registration_is_still_pending(
    client, category, landing_type
):
    """두 대기는 독립적이다 — Seller 등록이 안 끝났어도 신원은 먼저 제출할 수
    있고, 그래도 최종 확정(CONFIRMED)에는 이르지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_seller_pending"
    assert body["has_identity"] is True

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert TaxIdentity.objects.filter(payout=payout).exists()
    assert payout.status == Payout.Status.CONFIRMED_SELLER_PENDING


@pytest.mark.django_db
def test_retry_seller_registration_resolves_to_confirmed_when_identity_already_submitted(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED


@pytest.mark.django_db
def test_retry_seller_registration_resolves_to_identity_pending_when_identity_missing(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed_identity_pending"


@pytest.mark.django_db
def test_retry_seller_registration_can_still_come_back_under_review(client, category, landing_type):
    """재시도해도 여전히 승인되지 않을 수 있다 — 그래도 실패로 종결되지
    않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="limit_exceeded")

    resp = _retry_seller_registration(
        client, dev, requested["idempotency_key"], simulate="limit_exceeded"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed_seller_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status != Payout.Status.FAILED


@pytest.mark.django_db
def test_seller_registration_cannot_be_retried_outside_seller_pending(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])  # 기본 성공 -> identity_pending

    resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
    assert resp.status_code == 409


@pytest.mark.django_db
def test_second_payout_reuses_seller_id_and_does_not_reregister(
    client, category, landing_type
):
    """sellerId가 Developer에 남아 두 번째 Payout이 재등록하지 않는다(#50 AC)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest_a = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-a", deadline_at=deadline,
    )
    dev = _verified_user(client, "dev-repeat", "dev-repeat-ci")
    submission_a = _submit(client, dev, contest_a["id"])
    _close_contest(client, contest_a, deadline=deadline)
    _award(client, sponsor, contest_a["id"], submission_a["id"])
    _accept_handover(client, sponsor, contest_a["id"])

    requested_a = _request_payout(client, dev, contest_a["id"])
    _confirm_payout(client, dev, requested_a["idempotency_key"])

    payout_a = Payout.objects.get(idempotency_key=requested_a["idempotency_key"])
    developer_id = payout_a.handover.award.submission.developer_id
    seller_after_first = Seller.objects.get(developer_id=developer_id)
    assert seller_after_first.status == Seller.Status.PARTIALLY_APPROVED
    first_seller_id = seller_after_first.seller_id

    # 같은 Developer가 두 번째 Contest도 이긴다. 첫 Contest를 마감시키며 시계를
    # 앞으로 감아 두었으므로(ClockOverride) 초기화하지 않으면 이 두 번째 마감이
    # 이미 지난 시각이 되어 제출 자체가 403으로 막힌다.
    ClockOverride.objects.filter(pk=1).delete()
    deadline2 = timezone.now() + timedelta(hours=1)
    sponsor2, contest_b = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-b", deadline_at=deadline2,
    )
    submission_b = _submit(client, dev, contest_b["id"])
    _close_contest(client, contest_b, deadline=deadline2)
    _award(client, sponsor2, contest_b["id"], submission_b["id"])
    _accept_handover(client, sponsor2, contest_b["id"])

    requested_b = _request_payout(client, dev, contest_b["id"])
    # 두 번째 확정에 "거절" 시나리오를 실어 보내도 — 이미 부분 승인된 Seller가
    # 있으므로 재등록 자체가 일어나지 않아 이 값은 무시되고 곧장 신원 대기로
    # 넘어간다.
    resp = _confirm_payout(
        client, dev, requested_b["idempotency_key"], seller_simulate="rejected"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed_identity_pending"

    assert Seller.objects.filter(developer_id=developer_id).count() == 1
    seller_after_second = Seller.objects.get(developer_id=developer_id)
    assert seller_after_second.seller_id == first_seller_id
    assert seller_after_second.status == Seller.Status.PARTIALLY_APPROVED


@pytest.mark.django_db
def test_developer_sees_next_action_guidance_on_payout(client, category, landing_type):
    """침묵은 상금이 사라진 것으로 읽힌다 — Developer가 다음에 뭘 해야 하는지
    알 수 있어야 한다(#50 AC)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    resp = _confirm_payout(
        client, dev, requested["idempotency_key"], seller_simulate="limit_exceeded"
    )
    body = resp.json()
    assert body["next_action_message"]
    assert "심사" in body["next_action_message"]

    get_resp = client.get(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert get_resp.status_code == 200
    assert get_resp.json()["next_action_message"]


# --- Operator 표면 — 두 대기 중 어느 쪽인지 조회 (#50 AC) -------------------------


@pytest.mark.django_db
def test_operator_sees_which_payouts_are_blocked_on_seller_vs_identity(
    client, category, landing_type
):
    sponsor, dev1, contest1, submission1 = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-op-1", dev_uid="dev-op-1"
    )
    requested1 = _request_payout(client, dev1, contest1["id"])
    _confirm_payout(client, dev1, requested1["idempotency_key"], seller_simulate="review_required")

    # 첫 Contest를 마감시키며 시계를 앞으로 감아 두었으므로(ClockOverride)
    # 초기화하지 않으면 두 번째 Contest의 마감이 이미 지난 시각이 된다.
    ClockOverride.objects.filter(pk=1).delete()
    _sponsor2, dev2, contest2, _submission2 = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-op-2", dev_uid="dev-op-2"
    )
    requested2 = _request_payout(client, dev2, contest2["id"])
    _confirm_payout(client, dev2, requested2["idempotency_key"])  # identity_pending

    operator = _operator_client()

    seller_blocked = operator.get("/api/operator/payouts?blocked_on=seller")
    assert seller_blocked.status_code == 200
    seller_keys = {row["idempotency_key"] for row in seller_blocked.json()}
    assert requested1["idempotency_key"] in seller_keys
    assert requested2["idempotency_key"] not in seller_keys
    seller_row = next(
        row for row in seller_blocked.json() if row["idempotency_key"] == requested1["idempotency_key"]
    )
    assert seller_row["blocked_on"] == "seller"
    assert seller_row["seller_status"] == "under_review"

    identity_blocked = operator.get("/api/operator/payouts?blocked_on=identity")
    assert identity_blocked.status_code == 200
    identity_keys = {row["idempotency_key"] for row in identity_blocked.json()}
    assert requested2["idempotency_key"] in identity_keys
    assert requested1["idempotency_key"] not in identity_keys


@pytest.mark.django_db
def test_operator_payouts_surface_is_closed_to_non_operators(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    resp = client.get("/api/operator/payouts", **_auth_header(dev["access"]))
    assert resp.status_code in (401, 403)


# --- 주민등록번호가 새는 자리 (#74) -------------------------------------------
#
# 이 값은 저장할 때 암호화된다(위 테스트가 확인한다). 하지만 **저장에 이르지
# 못한 요청**이 남는 자리가 두 곳 더 있다: 검증 실패 응답과 로그. pydantic 은
# 기본적으로 검증 오류에 `input` 을 담고, django-ninja 는 그것을 그대로
# `detail` 로 내보낸다 — 사용자가 자릿수를 틀리는 순간 주민등록번호 전체가
# 응답 본문에, 그리고 그 응답을 찍는 어떤 로그에든 들어간다.


@pytest.mark.django_db
def test_a_malformed_resident_number_never_comes_back_in_the_error_response(
    client, category, landing_type
):
    """자릿수를 틀린 주민등록번호가 4xx 응답 본문에 되돌아오면 안 된다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    # 13자리가 아니라 패턴 검증에서 떨어진다 — 사용자가 실제로 흔히 내는 요청이다.
    malformed = "900101123456"

    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": malformed},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert resp.status_code == 422
    body = resp.content.decode()
    assert malformed not in body, (
        "검증 실패 응답이 입력한 주민등록번호를 그대로 되돌려줬다 — "
        f"본문: {body[:400]}"
    )
    # 앞 6자리(생년월일)만 새도 준식별자다.
    assert malformed[:6] not in body


@pytest.mark.django_db
def test_a_malformed_resident_number_never_reaches_the_logs(
    client, category, landing_type, caplog
):
    """같은 요청이 로그에도 남으면 안 된다 — 응답만 막으면 절반이다."""

    import logging

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    malformed = "900101123456"

    with caplog.at_level(logging.DEBUG):
        client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": malformed},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )

    logged = chr(10).join(record.getMessage() for record in caplog.records)
    assert malformed not in logged
    assert malformed[:6] not in logged


@pytest.mark.django_db
def test_a_valid_resident_number_never_comes_back_in_the_success_response(
    client, category, landing_type
):
    """성공 응답에도 되돌려주지 않는다 — 되돌려줄 이유가 없다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    rrn = "9001011234567"
    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": rrn},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert resp.status_code == 200
    assert rrn not in resp.content.decode()
    assert rrn[:6] not in resp.content.decode()


# --- 어댑터 선택이 resolve_adapter를 쓴다 (#83) --------------------------------


class _DottedPathTestPayoutAdapter(FakePayoutAdapter):
    """`PAYOUT_ADAPTER_MODE`에 dotted path로 지목됐을 때 실제로 이 클래스가
    쓰인다는 것을 증명하기 위한 테스트 전용 더블(#83).

    `FakePayoutAdapter`의 기본 시나리오(`simulate=None`)는 즉시 "paid"를
    돌려주는데, 이 더블은 그와 반대로 항상 "failed"를 돌려준다 — 그래서
    `simulate`를 전혀 넘기지 않은 confirm 호출이 실패로 끝나면, `resolve_adapter`가
    "fake" 별칭이 아니라 이 dotted path를 실제로 import해 썼다는 것을 HTTP 응답
    본문만으로 확인할 수 있다.
    """

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        return "failed"


@pytest.mark.django_db
def test_payout_adapter_mode_resolves_a_dotted_path_to_a_real_class(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._DottedPathTestPayoutAdapter"
    ):
        resp = _confirm_payout(client, dev, requested["idempotency_key"])

    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


class _DottedPathTestSellerAdapter(FakeSellerAdapter):
    """`SELLER_ADAPTER_MODE`에 dotted path로 지목됐을 때 실제로 이 클래스가
    쓰인다는 것을 증명하기 위한 테스트 전용 더블(#83).

    `FakeSellerAdapter`의 나머지 동작(부분 승인/한도 초과/심사 필요/거절
    시나리오)은 그대로 물려받고, `seller_id`에만 이 클래스만 낼 수 있는 마커를
    남긴다 — `SELLER_ADAPTER_MODE="fake"`였다면 절대 나올 수 없는 값이므로,
    DB에 저장된 값만으로 `resolve_adapter`가 이 dotted path를 실제로 import해
    썼다는 것을 확인할 수 있다.
    """

    def register(
        self, *, developer_id: int, simulate: str | None = None, policy=None
    ) -> SellerRegistrationResult:
        result = super().register(developer_id=developer_id, simulate=simulate, policy=policy)
        return SellerRegistrationResult(
            seller_id=f"dotted-path-marker-{developer_id}",
            status=result.status,
            weekly_limit_amount=result.weekly_limit_amount,
        )


@pytest.mark.django_db
def test_seller_adapter_mode_resolves_a_dotted_path_to_a_real_class(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        SELLER_ADAPTER_MODE="tests.test_payouts._DottedPathTestSellerAdapter"
    ):
        resp = _confirm_payout(client, dev, requested["idempotency_key"])

    assert resp.status_code == 200

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.seller_id == f"dotted-path-marker-{developer_id}"


# --- #57: Seller.Status.APPROVAL_REQUIRED / APPROVED -----------------------------------


@pytest.mark.django_db
def test_approval_required_is_visible_and_distinct_from_pending(client, category, landing_type):
    """APPROVAL_REQUIRED("본인인증 대기")는 PENDING("응답 대기")과 화면에서
    다르게 읽혀야 한다(#57 추가 인수조건) — 하나는 Developer의 차례이고, 하나는
    아무도 할 일이 없는 상태다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(
        client, dev, requested["idempotency_key"], seller_simulate="approval_required"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_seller_pending"
    assert body["seller_status"] == "approval_required"
    assert "본인인증" in body["next_action_message"]

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status == Seller.Status.APPROVAL_REQUIRED


@pytest.mark.django_db
def test_approved_seller_is_ready_like_partially_approved(client, category, landing_type):
    """APPROVED(KYC 완료, 한도 없음)도 PARTIALLY_APPROVED처럼 곧바로 지급
    가능 상태로 취급된다 — 한도를 푼 Developer가 계속 부분 승인으로 남지
    않는다(#57 추가 인수조건)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approved")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["seller_status"] == "approved"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING


@pytest.mark.django_db
def test_second_payout_does_not_reregister_when_seller_is_approved(client, category, landing_type):
    """READY_STATUSES는 PARTIALLY_APPROVED뿐 아니라 APPROVED도 포함한다 — 이미
    APPROVED인 Seller는 두 번째 Payout에서도 재등록하지 않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest_a = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-approved", deadline_at=deadline, prize=1_000_000,
    )
    dev = _verified_user(client, "dev-approved", "dev-approved-ci")
    submission_a = _submit(client, dev, contest_a["id"])
    _close_contest(client, contest_a, deadline=deadline)
    _award(client, sponsor, contest_a["id"], submission_a["id"])
    _accept_handover(client, sponsor, contest_a["id"])
    requested_a = _request_payout(client, dev, contest_a["id"])
    _confirm_payout(client, dev, requested_a["idempotency_key"], seller_simulate="approved")

    payout_a = Payout.objects.get(idempotency_key=requested_a["idempotency_key"])
    developer_id = payout_a.handover.award.submission.developer_id
    seller_id_after_first = Seller.objects.get(developer_id=developer_id).seller_id

    ClockOverride.objects.filter(pk=1).delete()
    deadline2 = timezone.now() + timedelta(hours=1)
    sponsor_b, contest_b = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-approved-2", deadline_at=deadline2, prize=1_000_000,
    )
    submission_b = _submit(client, dev, contest_b["id"])
    _close_contest(client, contest_b, deadline=deadline2)
    _award(client, sponsor_b, contest_b["id"], submission_b["id"])
    _accept_handover(client, sponsor_b, contest_b["id"])
    requested_b = _request_payout(client, dev, contest_b["id"])

    # "rejected"를 넘겨도 이미 APPROVED인 Seller는 어댑터를 다시 부르지 않으므로
    # 여전히 즉시 확정된다 — ensure_seller_registered가 READY_STATUSES에서
    # 곧바로 반환한다는 것을 증명한다.
    resp = _confirm_payout(client, dev, requested_b["idempotency_key"], seller_simulate="rejected")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["seller_status"] == "approved"

    seller_id_after_second = Seller.objects.get(developer_id=developer_id).seller_id
    assert seller_id_after_second == seller_id_after_first


# --- #57: 전화번호 제출 -----------------------------------------------------------------


@pytest.mark.django_db
def test_seller_phone_submission_stores_encrypted_value(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/seller-phone",
        data={"phone_number": "01055556666"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 200

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.phone_number == "01055556666"
    # DB 컬럼 자체는 평문이 아니어야 한다(TaxIdentity와 같은 원칙).
    assert "01055556666" not in seller.phone_number_encrypted


@pytest.mark.django_db
def test_seller_phone_submission_retries_registration_when_seller_pending(
    client, category, landing_type
):
    """Seller 등록이 대기 중이었다면(#50 심사 대기 시나리오), 전화번호 제출
    직후 곧바로 재시도된다 — Developer가 전화번호를 낸 뒤 별도로 "다시 시도"
    버튼을 또 눌러야 한다면 그 자체가 침묵으로 읽힌다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_SELLER_PENDING

    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/seller-phone",
        data={"phone_number": "01055556666"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    # FakeSellerAdapter는 phone_number를 쓰지 않으므로 재시도의 시나리오는
    # 기본값(성공)이다 — 곧바로 다음 단계로 넘어간다.
    assert body["status"] == "confirmed_identity_pending"


@pytest.mark.django_db
def test_seller_phone_rejects_malformed_value(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/seller-phone",
        data={"phone_number": "abc"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_next_action_message_asks_for_phone_when_seller_row_has_none(
    client, category, landing_type
):
    """PENDING이면서 전화번호도 없으면 "우리가 응답을 기다린다"가 아니라
    "Developer가 낼 것이 있다"는 뜻이어야 한다(#57 추가 인수조건) — 실물
    어댑터가 이 상태에 실제로 머무는 경로는 `test_payouts_toss_adapter.py`가
    이미 검증했으므로, 여기서는 그 상태에서 화면 문구가 올바른지만 확인한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    # 실물 어댑터가 전화번호 없이 PENDING에 머무는 상황을 흉내낸다 — Fake는
    # 이 상태를 직접 만들 시나리오가 없으므로(#50 네 시나리오에는 없다) 여기서만
    # ORM으로 상태를 조정한다(동작을 구동하는 게 아니라 화면 문구를 확인하기
    # 위한 사전 조건 설정이다 — `_freeze`가 ClockOverride를 직접 다루는 것과
    # 같은 관용구).
    Seller.objects.filter(developer_id=developer_id).update(
        status=Seller.Status.PENDING, seller_id=""
    )

    resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["seller_status"] == "pending"
    assert "전화번호" in body["next_action_message"]


# --- #57: 실물 토스 웹훅 --------------------------------------------------------------


_TEST_TOSS_SECURE_KEY = "b" * 64  # 64자 hex 더미 — 실제 TOSS_API_SECURE_KEY와 같은 형식.


def _sign_toss_webhook(*, payload: bytes, transmission_time: str) -> str:
    """`payouts.adapters_toss.verify_toss_webhook_signature`가 검증하는 것과
    같은 스킴으로, 테스트가 실제 토스인 척 서명을 만든다.

    secure_key는 hex 디코드한 32바이트를 HMAC 키로 쓴다(코드리뷰 지적 11) —
    JWE 암호화와 같은 해석이다.
    """

    import base64

    secure_key = settings.TOSS_API_SECURE_KEY
    digest = hmac.new(
        bytes.fromhex(secure_key),
        f"{payload.decode()}:{transmission_time}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"v1:{base64.b64encode(digest).decode()}"


@pytest.mark.django_db
def test_toss_payout_webhook_rejects_missing_or_wrong_signature(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])

    payload = json.dumps(
        {"eventType": "payout.changed", "data": {"refPayoutId": requested["idempotency_key"], "status": "COMPLETED"}}
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME="2024-01-01T00:00:00+09:00",
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE="v1:d3Jvbmc=",
        )
    assert resp.status_code == 401

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING  # 건드리지 않았다


@pytest.mark.django_db
def test_toss_payout_webhook_confirms_and_is_idempotent_on_redelivery(
    client, category, landing_type
):
    """실제 토스 서명 스킴으로 온 `payout.changed` 웹훅이 Payout을 확정하고,
    같은 웹훅이 재전송돼도 원장 분개가 두 번 남지 않는다(#57 AC)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    # confirm()을 부르지 않고 곧바로 웹훅으로 확정한다(REQUESTED에서 시작).
    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "data": {"refPayoutId": requested["idempotency_key"], "status": "COMPLETED"},
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        headers = dict(
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID="whid-1",
        )
        first = client.post(f"{PAYOUTS_URL}/webhook/toss", data=payload, **headers)
        assert first.status_code == 200
        assert first.json()["status"] == "confirmed_identity_pending"

        second = client.post(f"{PAYOUTS_URL}/webhook/toss", data=payload, **headers)
        assert second.status_code == 200

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.journal_entry_id is not None

    from ledger.services import contest_entries

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    fee_entries = [
        e for e in contest_entries(ledger_id)
        if "Payout 확정" in e.memo
    ]
    assert len(fee_entries) == 1


@pytest.mark.django_db
def test_toss_seller_webhook_advances_seller_pending_payout(client, category, landing_type):
    """`seller.changed` 웹훅이 Seller.status를 갱신하고, 그 즉시
    CONFIRMED_SELLER_PENDING이던 Payout을 다음 단계로 밀어준다(#57)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approval_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_SELLER_PENDING
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    ref_seller_id = f"laurio-developer-{developer_id}"

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "seller.changed",
            "data": {
                "refSellerId": ref_seller_id,
                "sellerId": seller.seller_id,
                "status": "PARTIALLY_APPROVED",
                "weeklyLimit": {"amount": 10_000_000},
            },
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss-seller",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "partially_approved"

    seller.refresh_from_db()
    assert seller.status == Seller.Status.PARTIALLY_APPROVED
    assert seller.weekly_limit_amount == 10_000_000

    payout.refresh_from_db()
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING


@pytest.mark.django_db
def test_toss_seller_webhook_rejects_bad_signature(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approval_required")

    payload = json.dumps(
        {"eventType": "seller.changed", "data": {"refSellerId": "x", "status": "APPROVED"}}
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss-seller",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME="2024-01-01T00:00:00+09:00",
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE="v1:d3Jvbmc=",
        )
    assert resp.status_code == 401



# --- 코드리뷰 후속(#57 2차) -------------------------------------------------------


class _TransferFailsOnceSellerReadyPayoutAdapter(FakePayoutAdapter):
    """실물 TossPayoutAdapter.confirm()의 두 갈래 동작을 재현하는 테스트
    더블 -- Seller가 아직 READY가 아니면(내부 확정 단계) 항상 "paid"를
    돌려주지만, Seller가 READY가 된 뒤(실이체를 실제로 시도하는 단계)에는
    항상 "failed"를 돌려준다. #57 코드리뷰 지적 1(실이체가 실패했는데도
    status만 보고 CONFIRMED로 잘못 전이하던 버그)을 검증하는 데 쓴다."""

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        from payouts.models import Payout as PayoutModel
        from payouts.models import Seller as SellerModel

        payout = PayoutModel.objects.select_related(
            "handover__award__submission__developer",
            "distribution_share__submission__developer",
        ).get(idempotency_key=idempotency_key)
        developer = (
            payout.handover.award.submission.developer
            if payout.handover_id is not None
            else payout.distribution_share.submission.developer
        )
        seller = SellerModel.objects.filter(developer=developer).first()
        if seller is None or seller.status not in SellerModel.READY_STATUSES:
            return "paid"
        return "failed"


@pytest.mark.django_db
def test_real_transfer_failure_keeps_payout_at_seller_pending_not_confirmed(
    client, category, landing_type
):
    """#57 코드리뷰 지적 1: Seller가 READY가 됐어도 실이체 자체가 거절되면
    Payout은 CONFIRMED로 전이하면 안 된다 -- transfer_status가 그 사실을
    별도로 기록하고, status는 재시도가 가능한 CONFIRMED_SELLER_PENDING에
    남는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        confirm_resp = _confirm_payout(
            client, dev, requested["idempotency_key"], seller_simulate="review_required"
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == "confirmed_seller_pending"

        # Seller가 READY가 되도록 재시도한다(기본 시나리오 -- 즉시 부분 승인).
        retry_resp = _retry_seller_registration(client, dev, requested["idempotency_key"])

    assert retry_resp.status_code == 200
    body = retry_resp.json()
    assert body["status"] == "confirmed_seller_pending"
    assert body["transfer_status"] == "failed"
    assert "다시 시도" in body["next_action_message"] or "실이체" in body["next_action_message"]

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_SELLER_PENDING
    assert payout.transfer_status == Payout.TransferStatus.FAILED

    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status in Seller.READY_STATUSES  # Seller 자체는 준비됐다


@pytest.mark.django_db
def test_real_transfer_recovers_to_confirmed_after_retry_succeeds(client, category, landing_type):
    """실이체가 처음엔 실패해도, 이후 재시도가 성공하면 정상적으로
    CONFIRMED까지 도달한다 -- 실패가 영구적 종결이 아님을 증명한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
        _retry_seller_registration(client, dev, requested["idempotency_key"])

    # 이번엔 정상(Fake 기본) 어댑터로 다시 시도한다 -- 실제 이체가 성공한다.
    retry_resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
    assert retry_resp.status_code == 200
    body = retry_resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["transfer_status"] == "completed"


class _AlwaysFailingSellerAdapter(FakeSellerAdapter):
    """실물 어댑터의 5xx/네트워크 장애를 흉내내는 테스트 더블(#57 코드리뷰
    지적 3/6) -- register()가 항상 SellerError를 던진다."""

    def register(self, *, developer_id: int, simulate: str | None = None, policy=None):
        from payouts.adapters import SellerError

        raise SellerError("fake vendor 5xx")


@pytest.mark.django_db
def test_seller_adapter_error_does_not_roll_back_the_ledger_entry(client, category, landing_type):
    """#57 코드리뷰 지적 6: Seller 등록 어댑터가 예외(SellerError)를 던져도
    mark_confirmed의 원장 분개는 그대로 남아야 한다 -- ADR-0020의 "Seller
    등록 결과와 무관하게 분개는 항상 남는다"가 실물 어댑터의 일시 오류에도
    지켜져야 한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        SELLER_ADAPTER_MODE="tests.test_payouts._AlwaysFailingSellerAdapter"
    ):
        resp = _confirm_payout(client, dev, requested["idempotency_key"])

    assert resp.status_code == 200
    body = resp.json()
    # 크래시(500)하지 않는다 -- SellerError가 mark_confirmed의 atomic 블록
    # 밖으로 새면 500이 나고 원장 분개까지 롤백된다.
    assert body["status"] == "confirmed_seller_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.journal_entry_id is not None

    from ledger.services import contest_balance

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    balance = contest_balance(ledger_id)
    assert balance["is_balanced"] is True


class _TransferStaysPendingPayoutAdapter(FakePayoutAdapter):
    """실물 TossPayoutAdapter.confirm()의 두 갈래 동작을 재현하되(Seller가
    READY가 아니면 "paid"), Seller가 READY가 된 뒤(실이체를 실제로 시도하는
    단계)에는 실이체가 벤더 쪽에서 아직 확정되지 않은 채 계속 대기 중인
    상황을 흉내낸다 -- confirm()이 PayoutTimeoutError를 던지고
    query_status()도 "pending"을 돌려준다. transfer_status가 COMPLETED로도
    FAILED로도 확정되지 않은(REQUESTED) 상태에서 웹훅이 도착하는 시나리오를
    재현하는 데 쓴다(#57 코드리뷰 지적 4/5, 3차)."""

    def _seller_ready(self, idempotency_key: str) -> bool:
        from payouts.models import Payout as PayoutModel
        from payouts.models import Seller as SellerModel

        payout = PayoutModel.objects.select_related(
            "handover__award__submission__developer",
            "distribution_share__submission__developer",
        ).get(idempotency_key=idempotency_key)
        developer = (
            payout.handover.award.submission.developer
            if payout.handover_id is not None
            else payout.distribution_share.submission.developer
        )
        seller = SellerModel.objects.filter(developer=developer).first()
        return seller is not None and seller.status in SellerModel.READY_STATUSES

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        from payouts.adapters import PayoutTimeoutError

        if not self._seller_ready(idempotency_key):
            return "paid"
        raise PayoutTimeoutError("fake pending forever")

    def query_status(self, *, idempotency_key: str) -> str:
        if not self._seller_ready(idempotency_key):
            return "pending"
        return "pending"


@pytest.mark.django_db
def test_toss_payout_webhook_failed_after_confirmed_updates_transfer_status(
    client, category, landing_type
):
    """#57 코드리뷰 지적 4: Payout이 이미 REQUESTED를 지나 확정된 뒤에
    도착한 payout.changed FAILED 웹훅이 조용히 버려지지 않는다 -- 원장
    분개(Payout.status)는 그대로 두되(ADR-0004), transfer_status와
    next_action_message에 그 사실이 드러나야 한다.

    이체가 아직 COMPLETED로 확정되지 않은(REQUESTED) 상태에서 웹훅이
    와야 한다 -- 코드리뷰 지적 5(3차)로 "이미 COMPLETED면 FAILED 웹훅이
    되돌리지 않는다"가 추가됐으므로, 이 테스트는 그 가드에 걸리지 않는
    시나리오(실이체가 여전히 미확정인 채로 있다가 웹훅으로 처음
    FAILED가 확정되는 경우)를 정확히 재현해야 한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._TransferStaysPendingPayoutAdapter"
    ):
        confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.transfer_status == Payout.TransferStatus.REQUESTED

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "data": {"refPayoutId": requested["idempotency_key"], "status": "FAILED"},
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
        )
    assert resp.status_code == 200
    # Payout.status(원장 확정 사실)는 되돌리지 않는다.
    assert resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING  # 되돌리지 않았다
    assert payout.transfer_status == Payout.TransferStatus.FAILED  # 하지만 기록은 남는다
    assert payout.journal_entry_id is not None  # 원장 분개도 그대로다

    get_resp = client.get(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert get_resp.status_code == 200
    assert "실패" in get_resp.json()["next_action_message"]


@pytest.mark.django_db
def test_seller_changed_webhook_ignores_out_of_order_regression(client, category, landing_type):
    """#57 코드리뷰 지적 9: 역순으로 도착한(또는 재전송된) seller.changed
    이벤트가 이미 더 진행된 상태(APPROVED)를 뒤처진 값(APPROVAL_REQUIRED)으로
    되돌리지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approved")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status == Seller.Status.APPROVED
    ref_seller_id = f"laurio-developer-{developer_id}"

    transmission_time = "2024-01-01T00:00:00+09:00"
    stale_payload = json.dumps(
        {
            "eventType": "seller.changed",
            "data": {
                "refSellerId": ref_seller_id,
                "sellerId": seller.seller_id,
                "status": "APPROVAL_REQUIRED",
            },
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=stale_payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss-seller",
            data=stale_payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
        )
    assert resp.status_code == 200
    # 되돌려진 값이 아니라 현재 상태를 그대로 돌려준다.
    assert resp.json()["status"] == "approved"

    seller.refresh_from_db()
    assert seller.status == Seller.Status.APPROVED  # 되돌아가지 않았다


@pytest.mark.django_db
def test_seller_changed_webhook_rejected_always_applies_even_after_approval(
    client, category, landing_type
):
    """REJECTED는 순위와 무관하게 항상 반영된다 -- 벤더가 이미 승인된 셀러를
    나중에 거절하는 것도 정상적인 사실이다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approved")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    ref_seller_id = f"laurio-developer-{developer_id}"

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "seller.changed",
            "data": {"refSellerId": ref_seller_id, "sellerId": seller.seller_id, "status": "REJECTED"},
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss-seller",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    seller.refresh_from_db()
    assert seller.status == Seller.Status.REJECTED



# --- 코드리뷰 후속(#57 3차) -------------------------------------------------------


class _CountingPayoutAdapter(FakePayoutAdapter):
    """confirm() 호출 횟수를 센다 -- resolve_adapter가 dotted path마다 매번 새
    인스턴스를 만들기 때문에 클래스 속성(인스턴스가 아니라)에 누적한다(#57
    코드리뷰 지적 2, 3차 -- 이미 COMPLETED인 Payout에 다시 confirm()을
    부르면 안 된다는 것을 호출 횟수로 직접 증명한다)."""

    call_count = 0

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        type(self).call_count += 1
        return "paid"


@pytest.mark.django_db
def test_completed_transfer_is_not_reconfirmed_on_identity_submission(
    client, category, landing_type
):
    """#57 코드리뷰 지적 2(3차): 실이체가 이미 COMPLETED면 submit_identity가
    다시 confirm()을 부르지 않는다 -- 이중 지급 방지를 벤더의 Idempotency-Key
    보존 기간에만 맡기지 않는다."""

    _CountingPayoutAdapter.call_count = 0
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._CountingPayoutAdapter"
    ):
        confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["transfer_status"] == "completed"
        calls_after_confirm = _CountingPayoutAdapter.call_count
        assert calls_after_confirm >= 1

        identity_resp = client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": "9001011234567"},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )
    assert identity_resp.status_code == 200
    assert identity_resp.json()["status"] == "confirmed"
    # confirm()이 다시 불리지 않았다 -- 이미 COMPLETED였기 때문이다.
    assert _CountingPayoutAdapter.call_count == calls_after_confirm


@pytest.mark.django_db
def test_submit_identity_does_not_regress_status_when_transfer_still_failing(
    client, category, landing_type
):
    """#57 코드리뷰 지적 6(3차): Seller가 READY인데 실이체가 여전히 실패
    중이면, submit_identity가 CONFIRMED_IDENTITY_PENDING을
    CONFIRMED_SELLER_PENDING으로 역행시키지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        # 기본 시나리오(성공)로 confirm하면 Seller가 곧바로 READY가 되고,
        # 이 어댑터는 그 시점에 실이체를 항상 거절한다 -- 그래도 첫 확정은
        # CONFIRMED_IDENTITY_PENDING에 머문다(신원이 아직 없다).
        confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == "confirmed_identity_pending"
        assert confirm_resp.json()["transfer_status"] == "failed"

        identity_resp = client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": "9001011234567"},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )

    assert identity_resp.status_code == 200
    body = identity_resp.json()
    # CONFIRMED_SELLER_PENDING으로 역행하지 않는다 -- 신원은 이미 제출됐다.
    assert body["status"] == "confirmed_identity_pending"
    assert body["has_identity"] is True
    assert body["transfer_status"] == "failed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING


@pytest.mark.django_db
def test_retry_endpoint_accepts_identity_pending_with_failed_transfer(
    client, category, landing_type
):
    """위 상태(CONFIRMED_IDENTITY_PENDING + transfer_status=failed)에서도
    재시도 엔드포인트가 409를 돌려주지 않는다(#57 코드리뷰 지적 6/7/8, 3차) --
    프런트가 transfer_status만 보고 재시도 버튼을 띄우므로, 엔드포인트가 이
    상태를 받지 않으면 그 버튼은 항상 실패한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        _confirm_payout(client, dev, requested["idempotency_key"])
        client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": "9001011234567"},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )

    # 재시도는 정상(Fake 기본, 즉시 성공) 어댑터로 -- 이 테스트가 증명하려는
    # 것은 "이 상태 조합에서 엔드포인트가 409를 내지 않는다"이지, 실이체가
    # 영원히 실패한다는 것이 아니다.
    retry_resp = _retry_seller_registration(client, dev, requested["idempotency_key"])

    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "confirmed"


@pytest.mark.django_db
def test_seller_changed_webhook_stale_event_cannot_resurrect_rejected(
    client, category, landing_type
):
    """#57 코드리뷰 지적 3(3차): REJECTED가 *source*일 때는 어떤 incoming
    상태로도 이 웹훅 경로에서 되돌리지 않는다 -- rank가 0이라는 이유로 "무엇
    으로든 넘어갈 수 있다"고 허용하면, 거절 이전에 발송됐다가 뒤늦게 도착한
    오래된 이벤트가 거절을 지우고 곧바로 실이체를 재발사할 길을 연다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="rejected")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status == Seller.Status.REJECTED
    ref_seller_id = f"laurio-developer-{developer_id}"

    transmission_time = "2024-01-01T00:00:00+09:00"
    stale_payload = json.dumps(
        {
            "eventType": "seller.changed",
            "data": {
                "refSellerId": ref_seller_id,
                "sellerId": seller.seller_id,
                "status": "APPROVAL_REQUIRED",
            },
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=stale_payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss-seller",
            data=stale_payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    seller.refresh_from_db()
    assert seller.status == Seller.Status.REJECTED


@pytest.mark.django_db
def test_seller_changed_webhook_exact_duplicate_does_not_reprocess(
    client, category, landing_type
):
    """#57 코드리뷰 지적 4(3차): 완전히 같은 상태의 중복 배달은
    advance_seller_pending_payouts를 다시 부르지 않는다 -- 그렇지 않으면
    "동급 rank가 서로 덮어쓴다"는 조건이 중복 배달마다 실이체 재시도 표면을
    다시 두드린다."""

    _CountingPayoutAdapter.call_count = 0
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._CountingPayoutAdapter"
    ):
        _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

        payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
        developer_id = payout.handover.award.submission.developer_id
        seller = Seller.objects.get(developer_id=developer_id)
        ref_seller_id = f"laurio-developer-{developer_id}"

        transmission_time = "2024-01-01T00:00:00+09:00"
        payload = json.dumps(
            {
                "eventType": "seller.changed",
                "data": {
                    "refSellerId": ref_seller_id,
                    "sellerId": seller.seller_id or "seller-dup-test",
                    "status": "PARTIALLY_APPROVED",
                    "weeklyLimit": {"amount": 10_000_000},
                },
            }
        ).encode("utf-8")

        with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
            signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
            headers = dict(
                content_type="application/json",
                HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
                HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
            )
            first = client.post(f"{PAYOUTS_URL}/webhook/toss-seller", data=payload, **headers)
            assert first.status_code == 200
            calls_after_first = _CountingPayoutAdapter.call_count
            assert calls_after_first >= 1  # advance_seller_pending_payouts가 실제로 불렸다

            second = client.post(f"{PAYOUTS_URL}/webhook/toss-seller", data=payload, **headers)
            assert second.status_code == 200

    # 완전히 같은 상태의 재전송이므로 confirm()이 다시 불리지 않았다.
    assert _CountingPayoutAdapter.call_count == calls_after_first


@pytest.mark.django_db
def test_participation_next_action_reflects_failed_transfer_not_payout_complete(
    client, category, landing_type
):
    """#57 코드리뷰 지적 7(3차): 「내 참가 현황」이 transfer_status를 본다 --
    Seller가 READY인데 실이체만 실패했으면 PAYOUT_COMPLETE라고 말하지 않는다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        _confirm_payout(client, dev, requested["idempotency_key"])

    # 「내 참가 현황」의 next_action_for()는 hasattr(submission, "score")부터
    # 확인한다 -- _ready_for_payout는 채점을 돌리지 않고 곧바로 Award로
    # 가므로(#57 범위 밖인 채점 플로우), Score가 없으면 AWAITING_SCORING에서
    # 끝나 payout 단계까지 내려가지 않는다. Score 생성은 이 테스트가 보려는
    # 동작(transfer_status를 읽는가)이 아니라 사전 조건 설정이다 --
    # `_freeze`가 ClockOverride를 직접 다루는 것과 같은 관용구.
    from scoring.models import Score

    Score.objects.create(
        submission_id=submission["id"],
        percentage=100,
        model_version="test",
        prompt="",
        reasoning=[],
    )

    resp = client.get("/api/submissions/mine", **_auth_header(dev["access"]))
    assert resp.status_code == 200
    rows = resp.json()["items"]
    row = next(r for r in rows if r["contest_id"] == contest["id"])
    assert row["next_action"] == "retry_transfer"
    assert row["next_action"] != "payout_complete"


@pytest.mark.django_db
def test_operator_blocked_on_transfer_for_identity_pending_with_failed_transfer(
    client, category, landing_type
):
    """#57 코드리뷰 지적 9(3차): CONFIRMED_IDENTITY_PENDING + transfer_status
    FAILED는 blocked_on="identity"가 아니라 "transfer"다 -- "identity"로
    분류되면 이미 제출된 신원을 또 기다리는 것처럼 보이고, transfer 큐에서는
    아예 빠진다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.json()["status"] == "confirmed_identity_pending"
    assert confirm_resp.json()["transfer_status"] == "failed"

    operator = _operator_client()
    resp = operator.get(f"{PAYOUTS_URL.replace('/payouts', '/operator/payouts')}?blocked_on=transfer")
    assert resp.status_code == 200
    idempotency_keys = [row["idempotency_key"] for row in resp.json()]
    assert requested["idempotency_key"] in idempotency_keys

    identity_resp = operator.get(
        f"{PAYOUTS_URL.replace('/payouts', '/operator/payouts')}?blocked_on=identity"
    )
    assert requested["idempotency_key"] not in [row["idempotency_key"] for row in identity_resp.json()]
