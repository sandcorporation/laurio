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


def _queue_rows(response) -> list[dict]:
    """운영자 지급 큐 응답의 행들. 페이지네이션이 붙어(#149) 본문이
    `{"items": [...], "count": N}` 이다 — 건수는 `response.json()["count"]` 로 따로 본다."""

    body = response.json()
    assert "items" in body, body
    return body["items"]


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
def test_confirm_timeout_then_failed_requery_leaves_payout_requested_not_500(
    client, category, landing_type
):
    """타임아웃 뒤 재확인(query_status) 자체가 또 실패하면 500 이 아니라 미확정으로
    남긴다 (#125) — 결제 확인(payments.api)이 #87 지적 3 으로 얻은 규율을 지급 확인도
    같이 갖는다. 실패도 타임아웃도 "아직 모른다"이지 "실패했다"가 아니다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    resp = _confirm_payout(
        client, dev, requested["idempotency_key"], simulate="timeout_then_query_error"
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "requested"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.REQUESTED
    assert payout.journal_entry_id is None


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
    seller_keys = {row["idempotency_key"] for row in _queue_rows(seller_blocked)}
    assert requested1["idempotency_key"] in seller_keys
    assert requested2["idempotency_key"] not in seller_keys
    seller_row = next(
        row for row in _queue_rows(seller_blocked) if row["idempotency_key"] == requested1["idempotency_key"]
    )
    assert seller_row["blocked_on"] == "seller"
    assert seller_row["seller_status"] == "under_review"

    identity_blocked = operator.get("/api/operator/payouts?blocked_on=identity")
    assert identity_blocked.status_code == 200
    identity_keys = {row["idempotency_key"] for row in _queue_rows(identity_blocked)}
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

    def confirm(self, request, *, simulate: str | None = None):
        from payouts.adapters import VendorResult

        return VendorResult(status="failed")


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

    def register(self, registration, *, simulate: str | None = None) -> SellerRegistrationResult:
        result = super().register(registration, simulate=simulate)
        return SellerRegistrationResult(
            seller_id=f"dotted-path-marker-{registration.ref_seller_id.rsplit('-', 1)[-1]}",
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
        {
            "eventType": "payout.changed",
            "entityBody": {
                # 벤더가 실제로 돌려주는 refPayoutId는 우리가 보낸 것과 같은
                # `{idempotency_key}-{transfer_attempt}` 형식이다(코드리뷰
                # 지적 1, 5차) — 접미어 없는 순수 UUID를 손으로 넣으면 이
                # 테스트가 실제로는 잡아야 할 파싱 결함을 가릴 수 있다.
                "refPayoutId": f"{requested['idempotency_key']}-0",
                "status": "COMPLETED",
            },
        }
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
            # 접미어(-0)를 포함한 실제 벤더 참조 형식을 그대로 쓴다(코드리뷰
            # 지적 1, 5차 — 접미어 없는 순수 key로는 이 웹훅이 실제로는 늘
            # 422가 나던 결함을 이 테스트가 잡지 못했다). REQUESTED에서
            # confirm()을 거치지 않고 곧바로 웹훅으로 확정하므로
            # transfer_attempt는 아직 기본값 0이다.
            "entityBody": {"refPayoutId": f"{requested['idempotency_key']}-0", "status": "COMPLETED"},
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
            "entityBody": {
                "refSellerId": ref_seller_id,
                "id": seller.seller_id,
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
        {"eventType": "seller.changed", "entityBody": {"refSellerId": "x", "status": "APPROVED"}}
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

    def confirm(self, request, *, simulate: str | None = None):
        from payouts.adapters import VendorResult

        # 수취인(request.seller_id)이 없으면 내부 확정 "paid", 있으면 실이체 거절 "failed".
        return VendorResult(status="failed" if request.seller_id else "paid")


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

    def register(self, registration, *, simulate: str | None = None):
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
    """수취인이 있으면 실이체가 영원히 pending 인 더블 -- 확정된 뒤 뒤늦게 웹훅으로 결과가
    도착하는 경로를 재현한다."""

    def confirm(self, request, *, simulate: str | None = None):
        from payouts.adapters import PayoutTimeoutError, VendorResult

        if not request.seller_id:
            return VendorResult(status="paid")
        raise PayoutTimeoutError("fake pending forever")

    def query_status(self, request):
        from payouts.adapters import VendorResult

        return VendorResult(status="pending")


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
            # attempt 선점은 caller(payouts.progress)가 하므로(#135) 어댑터가 무엇이든
            # 실이체를 시도한 순간 transfer_attempt 는 1 이다 — 실제 형식 그대로 그 값을 쓴다
            # (코드리뷰 지적 1, 5차). 낡은 attempt 의 배달은 조용히 버려진다.
            "entityBody": {
                "refPayoutId": f"{requested['idempotency_key']}-{payout.transfer_attempt}",
                "status": "FAILED",
            },
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
            "entityBody": {
                "refSellerId": ref_seller_id,
                "id": seller.seller_id,
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
def test_seller_changed_webhook_unknown_status_422s_and_does_not_touch_seller(
    client, category, landing_type
):
    """벤더 문서(docs.tosspayments.com/reference/additional, 웹 확인 —
    #174)가 실제로 규정하는 Seller.status 는 APPROVAL_REQUIRED·
    PARTIALLY_APPROVED·KYC_REQUIRED·APPROVED 넷뿐이다 — REJECTED 는 이
    문서에 없다. 예전 맵은 "토스에 재확인한 실제 상태 흐름(ADR-0020)"이라며
    UNDER_REVIEW·REJECTED·DENIED 도 함께 실었지만 그 재확인 기록에도 근거가
    없었다(#174). 벤더 거절은 이 비동기 웹훅이 아니라 등록 응답의 4xx로
    온다(#172, `TossSellerAdapter._parse_seller_response`) — 그러니 이
    웹훅이 알지 못하는 status 를 받으면 422 로 크게 남기고 Seller 는
    건드리지 않는다(#174 AC: 모르는 값은 조용히 진행시키지 않는다)."""

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
            "entityBody": {"refSellerId": ref_seller_id, "id": seller.seller_id, "status": "REJECTED"},
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
    assert resp.status_code == 422

    seller.refresh_from_db()
    assert seller.status == Seller.Status.APPROVED  # 건드려지지 않았다



# --- 코드리뷰 후속(#57 3차) -------------------------------------------------------


class _CountingPayoutAdapter(FakePayoutAdapter):
    """confirm() 호출 횟수를 센다 -- resolve_adapter가 dotted path마다 매번 새
    인스턴스를 만들기 때문에 클래스 속성(인스턴스가 아니라)에 누적한다(#57
    코드리뷰 지적 2, 3차 -- 이미 COMPLETED인 Payout에 다시 confirm()을
    부르면 안 된다는 것을 호출 횟수로 직접 증명한다)."""

    call_count = 0

    def confirm(self, request, *, simulate: str | None = None):
        from payouts.adapters import VendorResult

        type(self).call_count += 1
        return VendorResult(status="paid")


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
            "entityBody": {
                "refSellerId": ref_seller_id,
                "id": seller.seller_id,
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
                "entityBody": {
                    "refSellerId": ref_seller_id,
                    "id": seller.seller_id or "seller-dup-test",
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

        # 신원은 이미 제출된 상태여야 한다 -- 신원이 없으면(코드리뷰
        # 지적 3, 4차) SUBMIT_TAX_IDENTITY가 우선하는 것이 올바른 동작이다 --
        # 이 테스트가 보려는 것은 그 다음 단계(신원은 낸 다음 실이체가 실패한
        # 경우)다.
        client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": "9001011234567"},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )

    resp = client.get("/api/submissions/mine", **_auth_header(dev["access"]))
    assert resp.status_code == 200
    rows = resp.json()["items"]
    row = next(r for r in rows if r["contest_id"] == contest["id"])
    assert row["next_action"] == "retry_transfer"
    assert row["next_action"] != "payout_complete"


@pytest.mark.django_db
def test_participation_next_action_prioritizes_missing_identity_over_retry_transfer(
    client, category, landing_type
):
    """#57 코드리뷰 지적 3(4차): 신원을 아직 한 번도 못 낸(has_identity=False)
    Payout은 transfer_status가 FAILED여도 retry_transfer가 아니라
    submit_tax_identity를 돌려준다 -- 둘을 동시에 기다리는 상태인데
    하나가 다른 하나를 가리면 안 된다."""

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
    assert confirm_resp.json()["has_identity"] is False

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
    assert row["next_action"] == "submit_tax_identity"


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

        # 신원을 먼저 낸다 -- 미제출 신원이 있으면(코드리뷰 지적 3, 4차)
        # identity가 우선해야 한다 -- 이 테스트가 보려는 것은 그 다음 단계다.
        # override_settings 블록 밖으로 나가면 PAYOUT_ADAPTER_MODE가
        # 기본값(fake)으로 되돌아가 submit_identity의 실이체 재확인이 항상
        # 즉시 성공해 버린다 -- 반드시 이 블록 안에서 제출해야 한다.
        client.post(
            f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": "9001011234567"},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )

    operator = _operator_client()
    resp = operator.get(f"{PAYOUTS_URL.replace('/payouts', '/operator/payouts')}?blocked_on=transfer")
    assert resp.status_code == 200
    idempotency_keys = [row["idempotency_key"] for row in _queue_rows(resp)]
    assert requested["idempotency_key"] in idempotency_keys

    identity_resp = operator.get(
        f"{PAYOUTS_URL.replace('/payouts', '/operator/payouts')}?blocked_on=identity"
    )
    assert requested["idempotency_key"] not in [row["idempotency_key"] for row in _queue_rows(identity_resp)]


@pytest.mark.django_db
def test_operator_blocked_on_identity_takes_priority_when_identity_missing(
    client, category, landing_type
):
    """#57 코드리뷰 지적 3(4차): 신원을 아직 내지 않았으면 transfer_status가
    FAILED여도 blocked_on은 "identity"다 -- "transfer"로 분류되면 운영자가
    identity 큐에서 이 행을 영영히 못 본다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE=(
            "tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
        )
    ):
        confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.json()["has_identity"] is False
    assert confirm_resp.json()["transfer_status"] == "failed"

    operator = _operator_client()
    identity_resp = operator.get(
        f"{PAYOUTS_URL.replace('/payouts', '/operator/payouts')}?blocked_on=identity"
    )
    assert requested["idempotency_key"] in [row["idempotency_key"] for row in _queue_rows(identity_resp)]

    transfer_resp = operator.get(
        f"{PAYOUTS_URL.replace('/payouts', '/operator/payouts')}?blocked_on=transfer"
    )
    assert requested["idempotency_key"] not in [row["idempotency_key"] for row in _queue_rows(transfer_resp)]



# --- 코드리뷰 후속(#57 4차) -------------------------------------------------------


_R4_SECURE_KEY_HEX = "c" * 64


@pytest.mark.django_db
def test_toss_payout_adapter_never_posts_twice_for_the_same_confirm_request(
    client, category, landing_type
):
    """#57 코드리뷰 지적 1(4차, 실행 재현 확인됨): Seller가 이미 READY인
    Payout은 confirm 요청 한 번에 payouts.api.confirm_payout의 직접 호출과
    payouts.services.mark_confirmed 안의 _request_real_transfer_if_ready 호출
    둘 다가 TossPayoutAdapter.confirm()에 도달한다 -- 벤더에는
    정확히 한 번만 POST가 나가야 한다(claim_transition 관용구로 이
    시도를 벤더 호출 전에 선점한다)."""

    from unittest.mock import Mock, patch

    from payouts.adapters_toss import jwe_encrypt

    def _encrypted_response(status_code, body):
        token = jwe_encrypt(body, secure_key_hex=_R4_SECURE_KEY_HEX)
        response = Mock()
        response.status_code = status_code
        response.text = token
        response.json.side_effect = ValueError("jwe body")
        return response

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    # 이 Developer는 이미 이전에 Seller가 등록되어 READY 상태다 --
    # payouts.api.confirm_payout의 첫 번째 adapter.confirm() 호출이 곳바로
    # 실이체를 시도하는 시나리오를 재현한다.
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    Seller.objects.create(
        developer_id=developer_id,
        seller_id="already-ready-seller",
        status=Seller.Status.PARTIALLY_APPROVED,
        weekly_limit_amount=10_000_000,
    )

    with override_settings(
        PAYOUT_ADAPTER_MODE="payouts.adapters_toss.TossPayoutAdapter",
        TOSS_API_SECRET_KEY="test-secret-key",
        TOSS_API_SECURE_KEY=_R4_SECURE_KEY_HEX,
    ):
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(
                200, {"id": "toss-vendor-payout-id", "status": "COMPLETED"}
            )
            resp = _confirm_payout(client, dev, requested["idempotency_key"])

    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed_identity_pending"
    assert resp.json()["transfer_status"] == "completed"
    # 핵심 단언 -- 두 경로가 같은 Payout에 대해 경쳐 불려도 실제 POST는
    # 단 한 번만 나가야 한다.
    assert mock_post.call_count == 1


@pytest.mark.django_db
def test_toss_payout_adapter_retry_uses_a_fresh_vendor_reference(client, category, landing_type):
    """#57 코드리뷰 지적 4(4차): 재시도마다 벤더에 보내는 refPayoutId/
    Idempotency-Key가 달라야 한다 -- 같은 값을 재사용하면 벤더가 예전
    FAILED 응답을 그대로 재생해 실운영에서 영구히 복구 불가능해진다.

    Seller는 미리 만들어두지 않는다 -- confirm() 시점에 이미 READY인
    Seller가 있으면 그 첫 벤더 응답이 "failed"일 때 mark_failed가 Payout
    자체를 종결시킨다(원래 #15/#50 설계 그대로: 아직 원장에 아무것도
    안 남았을 때의 실패는 그 Payout 행을 끝내고 재시도는 새 Payout으로
    한다). 이 테스트가 보려는 "같은 Payout을 재시도할 때 refPayoutId가
    바뀌는가"를 보려면, 첫 실이체 시도가 mark_confirmed 안에서(원장 분개가
    이미 남은 뒤) 실패해 CONFIRMED_IDENTITY_PENDING + transfer_status=
    failed로 남는 경로를 타야 한다 -- Seller가 confirm() 첫 호출 시점에는
    아직 없다가(내부 확정만 진행), 그 안에서 등록되며 READY가 되는 순간
    처음으로 실이체가 시도되는 정상 순서를 그대로 따른다.
    """

    from unittest.mock import Mock, patch

    from payouts.adapters_toss import jwe_decrypt, jwe_encrypt

    def _encrypted_response(status_code, body):
        token = jwe_encrypt(body, secure_key_hex=_R4_SECURE_KEY_HEX)
        response = Mock()
        response.status_code = status_code
        response.text = token
        response.json.side_effect = ValueError("jwe body")
        return response

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="payouts.adapters_toss.TossPayoutAdapter",
        TOSS_API_SECRET_KEY="test-secret-key",
        TOSS_API_SECURE_KEY=_R4_SECURE_KEY_HEX,
    ):
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(400, {"code": "INVALID_ACCOUNT"})
            # 기본(성공) Seller 등록 시나리오 -- ensure_seller_registered가
            # mark_confirmed 안에서 Seller를 즉시 READY로 만들고, 그 직후
            # _request_real_transfer_if_ready가 처음으로 실이체를 시도한다.
            first_resp = _confirm_payout(client, dev, requested["idempotency_key"])
        assert first_resp.json()["status"] == "confirmed_identity_pending"
        assert first_resp.json()["transfer_status"] == "failed"
        first_ref = jwe_decrypt(
            mock_post.call_args.kwargs["data"], secure_key_hex=_R4_SECURE_KEY_HEX
        )["refPayoutId"]

        with patch("payouts.adapters_toss.requests.post") as mock_post_retry:
            mock_post_retry.return_value = _encrypted_response(
                400, {"code": "INVALID_ACCOUNT"}
            )
            retry_resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
        assert retry_resp.status_code == 200
        assert retry_resp.json()["transfer_status"] == "failed"
        second_ref = jwe_decrypt(
            mock_post_retry.call_args.kwargs["data"], secure_key_hex=_R4_SECURE_KEY_HEX
        )["refPayoutId"]

    assert first_ref != second_ref
    assert first_ref == f"{payout.idempotency_key}-1"
    assert second_ref == f"{payout.idempotency_key}-2"


@pytest.mark.django_db
def test_retry_seller_registration_preserves_tax_identity_requirement(
    client, category, landing_type
):
    """#57 코드리뷰 지적 2(4차, 실행 재현 확인됨): CONFIRMED_IDENTITY_PENDING +
    transfer_status=FAILED에서 재시도가 성공해도, 신원을 제출한 적이 없으면
    CONFIRMED로 바로 올라가면 안 된다 -- 주민등록번호를 영구히 못 받게
    된다."""

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
    assert confirm_resp.json()["has_identity"] is False

    # 이제 실이체가 성공하는 정상(Fake 기본) 어댑터로 재시도한다 --
    # 신원을 한 번도 내지 않았으므로 CONFIRMED가 아니라
    # CONFIRMED_IDENTITY_PENDING에 그대로 남아야 한다.
    retry_resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
    assert retry_resp.status_code == 200
    body = retry_resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["has_identity"] is False
    assert body["transfer_status"] == "completed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING

    # 이제 신원을 내면 정상적으로 CONFIRMED로 올라간다.
    identity_resp = client.post(
        f"{PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert identity_resp.status_code == 200
    assert identity_resp.json()["status"] == "confirmed"


@pytest.mark.django_db
class _VendorNoLongerRecognizesSellerAdapter(FakeSellerAdapter):
    """벤더가 우리 seller_id를 더는 인식하지 못하는 상황(GET 404)을 흉내내는
    테스트 더블(#57 코드리뷰 지적 6, 4차) -- register()를 몇 번을 다시
    불러도 항상 "pending"과 빈 seller_id를 돌려준다."""

    def register(self, registration, *, simulate: str | None = None):
        return SellerRegistrationResult(seller_id="", status="pending", weekly_limit_amount=None)


@pytest.mark.django_db
def test_seller_register_stale_id_does_not_loop_forever_on_404(
    client, category, landing_type
):
    """#57 코드리뷰 지적 6(4차): 벤더가 우리 seller_id를 404로 거부하면
    그 값을 보존하지 않는다 -- 보존하면 다음 register() 호출이 같은 죽은
    seller_id로 또 조회를 시도해 영원히 404를 반복하고 새 POST로 넘어갈
    길이 없어진다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    # 먼저 정상 경로로 seller_id를 확보한다(기본 Fake 성공 시나리오가 아니라
    # 심사 대기로 남겨 등록은 접수됐지만 아직 READY는 아닌 상태를 만든다).
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller_before = Seller.objects.get(developer_id=developer_id)
    assert seller_before.seller_id  # 등록 접수 시 받은 식별자가 있다.

    # 이제 벤더가 그 seller_id를 더는 인식하지 못하는 상황(GET 404)을
    # 재현한다 -- 재시도가 "pending"과 빈 seller_id를 돌려준다.
    with override_settings(
        SELLER_ADAPTER_MODE="tests.test_payouts._VendorNoLongerRecognizesSellerAdapter"
    ):
        resp = _retry_seller_registration(client, dev, requested["idempotency_key"])
    assert resp.status_code == 200

    seller_after = Seller.objects.get(developer_id=developer_id)
    assert seller_after.status == Seller.Status.PENDING
    # 핵심 단언 -- 죽은 seller_id가 보존되지 않았다. 보존되었다면 다음
    # register() 호출이 다시 같은 죽은 ID로 조회를 시도해 영원히 풀리지
    # 않는다(실물 TossSellerAdapter.register()는 seller_id가 있으면 GET으로
    # 재조회하는 경로를 타므로, 이 값이 안 지워지면 실운영에서 영구
    # 404 루프가 된다).
    assert seller_after.seller_id == ""


# --- 코드리뷰 후속(#57 5차) — attempt를 벤더 거래의 유일한 키로 끝까지 끌고 간다 ------
#
# 5차 코드리뷰의 성공 기준: "어떤 진입 경로 조합으로도 한 attempt에 벤더 POST가
# 한 번만 나가고, 그 결과가 정확히 그 attempt에 기록되며, 실패·중단 어느 쪽이든
# 회복 가능한 상태로 끝나는 것." 아래 세 테스트가 각각 재시도(attempt 증가),
# 웹훅 재전송(낡은 attempt 배달), 중단된 클레임(벤더에 닿기도 전에 끊긴 요청)을
# 다룬다 — 4차의 "두 경로가 동시에 발사돼도 requests.post가 한 번" 테스트를
# 그대로 넓힌 것이다.


@pytest.mark.django_db
def test_toss_payout_attempt_retry_after_failure_resolves_exactly_once(
    client, category, landing_type
):
    """attempt 1이 실패한 뒤 재시도(attempt 2)가 성공하면, 각 attempt마다
    정확히 한 번씩만 벤더 POST가 나가고 최종 transfer_status는 그 성공한
    attempt의 결과로만 확정된다."""

    from unittest.mock import Mock, patch

    from payouts.adapters_toss import jwe_encrypt

    def _encrypted_response(status_code, body):
        token = jwe_encrypt(body, secure_key_hex=_R4_SECURE_KEY_HEX)
        response = Mock()
        response.status_code = status_code
        response.text = token
        response.json.side_effect = ValueError("jwe body")
        return response

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="payouts.adapters_toss.TossPayoutAdapter",
        TOSS_API_SECRET_KEY="test-secret-key",
        TOSS_API_SECURE_KEY=_R4_SECURE_KEY_HEX,
    ):
        with patch("payouts.adapters_toss.requests.post") as mock_post_1:
            mock_post_1.return_value = _encrypted_response(400, {"code": "INVALID_ACCOUNT"})
            first_resp = _confirm_payout(client, dev, requested["idempotency_key"])
        assert first_resp.json()["transfer_status"] == "failed"
        assert mock_post_1.call_count == 1

        payout.refresh_from_db()
        assert payout.transfer_attempt == 1
        assert payout.vendor_payout_id == ""

        with patch("payouts.adapters_toss.requests.post") as mock_post_2:
            mock_post_2.return_value = _encrypted_response(
                200, {"id": "toss-vendor-id-attempt-2", "status": "COMPLETED"}
            )
            retry_resp = _retry_seller_registration(client, dev, requested["idempotency_key"])

    assert retry_resp.status_code == 200
    assert retry_resp.json()["transfer_status"] == "completed"
    # attempt 2에서도 벤더 POST는 정확히 한 번만 나갔다 -- attempt 1의 실패
    # 뒤에도 이중 POST가 없다.
    assert mock_post_2.call_count == 1

    payout.refresh_from_db()
    assert payout.transfer_attempt == 2
    # 새 attempt를 선점하며 vendor_payout_id가 그 attempt의 실제 응답으로
    # 갱신됐다 -- attempt 1의 빈 값이 남아 있지 않다(코드리뷰 지적 2, 5차).
    assert payout.vendor_payout_id == "toss-vendor-id-attempt-2"
    assert payout.transfer_status == Payout.TransferStatus.COMPLETED


@pytest.mark.django_db
def test_toss_payout_webhook_stale_attempt_delivery_is_discarded(
    client, category, landing_type
):
    """설계 결정(5차 코드리뷰): 웹훅의 refPayoutId가 가리키는 attempt가
    Payout의 현재 transfer_attempt보다 낮으면(낡은/지연 배달) 조용히
    버려야 한다 -- 이미 확정된 최신 attempt를 되돌리면 안 된다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    confirm_resp = _confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.json()["transfer_status"] == "completed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    # 지금 진행 중인(그리고 이미 확정된) attempt가 2라고 흉내낸다 -- 실물
    # TossPayoutAdapter가 재시도마다 이 값을 올리는 것과 같은 모양이다.
    Payout.objects.filter(pk=payout.pk).update(transfer_attempt=2)

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            # attempt=1(낡은 시도)의 지연 배달을 흉내낸다 -- 이미 attempt 2로
            # 넘어간 뒤라 이 결과는 버려야 한다.
            "entityBody": {"refPayoutId": f"{requested['idempotency_key']}-1", "status": "FAILED"},
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

    payout.refresh_from_db()
    # 되돌리지 않았다 -- COMPLETED도, attempt 자체도.
    assert payout.transfer_status == Payout.TransferStatus.COMPLETED
    assert payout.transfer_attempt == 2


@pytest.mark.django_db
def test_toss_payout_interrupted_claim_is_recoverable_after_staleness_threshold(
    client, category, landing_type
):
    """#57 코드리뷰 지적 6(5차): 벤더에 닿기도 전에 끊긴 요청(ConnectionError)은
    transfer_status=REQUESTED로 영구히 멈춘다 -- query_status도 vendor_payout_id가
    없어 우리 ref로 조회하는데, 그 조회조차 pending만 돌려주면 회복 경로가
    없다. transfer_claimed_at 기반 재선점(staleness threshold)이 그 회복
    경로다: 문턱을 넘기 전에는 재선점하지 않고(진행 중일 수 있으니), 넘긴
    뒤에는 새 attempt로 다시 시도할 수 있다."""

    from unittest.mock import Mock, patch

    import requests

    from payouts.adapters_toss import jwe_encrypt

    def _encrypted_response(status_code, body):
        token = jwe_encrypt(body, secure_key_hex=_R4_SECURE_KEY_HEX)
        response = Mock()
        response.status_code = status_code
        response.text = token
        response.json.side_effect = ValueError("jwe body")
        return response

    def _not_found_response():
        response = Mock()
        response.status_code = 404
        response.text = ""
        response.json.side_effect = ValueError("no body")
        return response

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    # 이 Developer는 이미 Seller가 READY다 -- confirm_payout의 첫 직접 호출이
    # 곧바로 실이체(POST)를 시도하는 시나리오를 재현한다.
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    Seller.objects.create(
        developer_id=developer_id,
        seller_id="already-ready-seller-interrupt",
        status=Seller.Status.PARTIALLY_APPROVED,
        weekly_limit_amount=10_000_000,
    )

    t0 = timezone.now()
    _freeze(t0)

    with override_settings(
        PAYOUT_ADAPTER_MODE="payouts.adapters_toss.TossPayoutAdapter",
        TOSS_API_SECRET_KEY="test-secret-key",
        TOSS_API_SECURE_KEY=_R4_SECURE_KEY_HEX,
    ):
        # 1) 벤더에 닿기도 전에 끊긴다 -- POST는 ConnectionError, 이어서
        #    confirm_payout이 PayoutTimeoutError를 잡고 query_status로
        #    재확인하지만 vendor_payout_id가 없어 ref 조회로 폴백하고,
        #    벤더는 이 시도 자체를 모르므로 404("pending")를 준다.
        with patch(
            "payouts.adapters_toss.requests.post",
            side_effect=requests.ConnectionError("connection reset"),
        ):
            with patch("payouts.adapters_toss.requests.get") as mock_get_1:
                mock_get_1.return_value = _not_found_response()
                first_resp = _confirm_payout(client, dev, requested["idempotency_key"])

        assert first_resp.status_code == 200
        payout.refresh_from_db()
        assert payout.status == Payout.Status.REQUESTED  # 아직 확정 안 됨(pending)
        assert payout.transfer_status == Payout.TransferStatus.REQUESTED
        assert payout.transfer_attempt == 1
        claimed_at_after_interrupt = payout.transfer_claimed_at
        assert claimed_at_after_interrupt is not None

        # 2) 문턱(60초)을 넘기 전에 곧바로 재시도하면 아직 재선점하지 않는다
        #    -- 실제로 진행 중일 수도 있으므로 성급하게 뺏지 않는다. 벤더
        #    POST는 이번에도 나가지 않아야 한다.
        with patch("payouts.adapters_toss.requests.post") as mock_post_too_soon:
            with patch("payouts.adapters_toss.requests.get") as mock_get_2:
                mock_get_2.return_value = _not_found_response()
                too_soon_resp = _confirm_payout(client, dev, requested["idempotency_key"])

        assert too_soon_resp.status_code == 200
        mock_post_too_soon.assert_not_called()
        payout.refresh_from_db()
        assert payout.transfer_attempt == 1  # 재선점되지 않았다
        assert payout.transfer_status == Payout.TransferStatus.REQUESTED

        # 3) 문턱을 넘긴 뒤에는 재선점해 새 attempt로 다시 시도할 수 있고,
        #    이번엔 벤더가 실제로 성공을 돌려준다 -- 중단된 상태가 영구히
        #    멈추지 않고 회복됐다.
        _freeze(t0 + timedelta(seconds=61))
        with patch("payouts.adapters_toss.requests.post") as mock_post_recovered:
            mock_post_recovered.return_value = _encrypted_response(
                200, {"id": "toss-vendor-id-recovered", "status": "COMPLETED"}
            )
            recovered_resp = _confirm_payout(client, dev, requested["idempotency_key"])

    assert recovered_resp.status_code == 200
    assert recovered_resp.json()["transfer_status"] == "completed"
    assert mock_post_recovered.call_count == 1

    payout.refresh_from_db()
    assert payout.transfer_attempt == 2  # 재선점으로 새 attempt를 받았다
    assert payout.transfer_status == Payout.TransferStatus.COMPLETED
    assert payout.vendor_payout_id == "toss-vendor-id-recovered"


@pytest.mark.django_db
def test_participation_says_request_payout_when_the_last_payout_attempt_failed(
    client, category, landing_type
):
    """벤더가 거절해 Payout 이 FAILED 로 끝나면 「내 참가 현황」은 「지급대행 등록 대기」가
    아니라 「지급을 다시 요청하세요」다 (#130) — 실제로 가능한 행동이 그것이고
    (get_or_create_payout 이 FAILED 뒤 새 REQUESTED 행을 만든다), 지급 화면의 문구도 이미
    그렇게 말한다. 전에는 status 별 분기의 fallthrough 가 FAILED 를 잘못 말했다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    failed = _confirm_payout(client, dev, requested["idempotency_key"], simulate="failed")
    assert failed.json()["status"] == "failed"

    from scoring.models import Score

    Score.objects.create(
        submission_id=submission["id"], percentage=100, model_version="test", prompt="", reasoning=[]
    )

    resp = client.get("/api/submissions/mine", **_auth_header(dev["access"]))
    assert resp.status_code == 200
    row = next(r for r in resp.json()["items"] if r["contest_id"] == contest["id"])
    assert row["next_action"] == "request_payout"


@pytest.mark.django_db
def test_operator_queue_flags_an_unclassifiable_payout_as_operator_hold_and_logs(
    client, category, landing_type, caplog
):
    """Hold 표에 없는 조합은 조용히 지나가지 않는다 (#130) — 돈은 움직이지 않고 사람의
    차례로 표시되며 ERROR 로그가 남는다. 도달 불가여야 하는 곳에 도달했다면 불변식이
    깨진 것이고, 무엇이 참인지 모르는 상태에서 통과시킬 이유가 없다(ADR-0025 와 같은
    규율). 표 밖의 status 값을 DB 에 직접 심어 재현한다."""

    import logging

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    Payout.objects.filter(idempotency_key=requested["idempotency_key"]).update(status="bogus")

    operator = _operator_client()
    with caplog.at_level(logging.ERROR):
        resp = operator.get("/api/operator/payouts")
    assert resp.status_code == 200
    row = next(r for r in _queue_rows(resp) if r["idempotency_key"] == requested["idempotency_key"])
    assert row["blocked_on"] == "operator"
    assert any("bogus" in record.getMessage() for record in caplog.records)


# --- #91: 지급 화면·운영자 큐 정리 — #57 이 의도적으로 남긴 것들 ------------------


@pytest.mark.django_db
def test_toss_payout_webhook_falls_back_to_vendor_payout_id_when_ref_is_absent(
    client, category, landing_type
):
    """`refPayoutId` 없이 `data.id` 만 온 웹훅도 받는다 (#91).

    폴백 경로는 `data.id` 를 우리 `refPayoutId`(`{idempotency_key}-{attempt}`)인 양
    파싱했는데, `data.id` 는 **벤더가 만든 자기 식별자**다(`TossPayoutAdapter` 가 POST
    응답의 `id` 를 그대로 `Payout.vendor_payout_id` 에 저장한다). UUID 도 아니고 attempt
    접미어도 없으니 `parse_vendor_ref` 가 언제나 None 을 돌려주고, 이 폴백은 **항상 422**
    였다 — 있으나 마나가 아니라, 있는데 반드시 실패하는 경로였다. 벤더 식별자로 조회하는
    길이 이미 있으므로(`vendor_payout_id`) 그것을 쓴다.
    """

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    # 실이체 시도가 벤더 식별자를 받아 둔 상태를 재현한다 — adapter 가 POST 응답의
    # `id` 를 저장하는 그 자리다.
    Payout.objects.filter(idempotency_key=requested["idempotency_key"]).update(
        vendor_payout_id="toss-vendor-payout-99"
    )

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            # refPayoutId 가 없다 — 벤더가 자기 식별자만 실어 보낸 경우다.
            "entityBody": {"id": "toss-vendor-payout-99", "status": "COMPLETED"},
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
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID="whid-fallback-1",
        )

    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING


@pytest.mark.django_db
def test_toss_payout_webhook_still_404s_on_an_unknown_vendor_payout_id(
    client, category, landing_type
):
    """폴백이 열렸다고 아무 식별자나 통과시키지 않는다 (#91) — 모르는 벤더 식별자는
    404 다(아는 idempotency_key 가 아닐 때와 같은 답)."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    _request_payout(client, dev, contest["id"])

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {"eventType": "payout.changed", "entityBody": {"id": "nobody-knows-this", "status": "COMPLETED"}}
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID="whid-fallback-2",
        )

    assert resp.status_code == 404, resp.content


@pytest.mark.django_db
def test_operator_payout_queue_does_not_query_per_row(client, category, landing_type):
    """운영자 지급 큐는 행이 늘어도 질의 수가 늘지 않는다 (#91).

    `hold_of` 는 「조회를 내지 않는다 — 호출부가 Seller 와 신원 제출 여부를 미리
    가져온다」고 못 박아 두었는데(`payouts/progress.py`), 이 큐만 그 규율을 지키지
    않아 행마다 Seller 1회 + TaxIdentity 1회를 쳤다. 홈이 세 큐를 병렬로 부르므로
    그대로 3배가 된다.
    """

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    sponsor1, dev1, contest1, _s1 = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-nplus1-1", dev_uid="dev-nplus1-1"
    )
    requested1 = _request_payout(client, dev1, contest1["id"])
    _confirm_payout(client, dev1, requested1["idempotency_key"], seller_simulate="review_required")

    operator = _operator_client(username="payouts-op-nplus1")

    with CaptureQueriesContext(connection) as one_row:
        resp = operator.get("/api/operator/payouts")
        assert resp.status_code == 200
    assert len(_queue_rows(resp)) == 1

    ClockOverride.objects.filter(pk=1).delete()
    _sponsor2, dev2, contest2, _s2 = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-nplus1-2", dev_uid="dev-nplus1-2"
    )
    requested2 = _request_payout(client, dev2, contest2["id"])
    _confirm_payout(client, dev2, requested2["idempotency_key"])  # identity_pending

    ClockOverride.objects.filter(pk=1).delete()
    _sponsor3, dev3, contest3, _s3 = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-nplus1-3", dev_uid="dev-nplus1-3"
    )
    requested3 = _request_payout(client, dev3, contest3["id"])
    _confirm_payout(client, dev3, requested3["idempotency_key"], seller_simulate="rejected")

    with CaptureQueriesContext(connection) as three_rows:
        resp = operator.get("/api/operator/payouts")
        assert resp.status_code == 200
    assert len(_queue_rows(resp)) == 3

    assert len(three_rows) == len(one_row), (
        "행이 1개에서 3개로 늘었는데 질의 수가 늘었다 — 행마다 조회하고 있다.\n"
        + "\n".join(q["sql"][:160] for q in three_rows)
    )


class _CountingSellerAdapter(FakeSellerAdapter):
    """`register()` 호출 횟수를 세는 테스트 전용 더블 (#91).

    등록이 READY 로 끝나지 않는 시나리오를 골라(`approval_required`)
    `ensure_seller_registered` 의 조기 반환에 걸리지 않게 한다 — 그래야
    「Payout 마다 벤더를 부른다」가 실제로 드러난다.
    """

    calls: list[str] = []

    def register(self, registration, *, simulate: str | None = None) -> SellerRegistrationResult:
        type(self).calls.append(registration.ref_seller_id)
        return super().register(registration, simulate="approval_required")


@pytest.mark.django_db
def test_submit_seller_phone_calls_the_vendor_once_no_matter_how_many_payouts(
    client, category, landing_type
):
    """전화번호 제출 한 번이 Payout 개수만큼 벤더를 부르지 않는다 (#91).

    Seller 는 Developer 단위 개념이라 등록도 한 번이면 된다. 그런데
    `submit_seller_phone` 은 대기 중인 Payout 마다 `retry_seller_registration` 을
    불렀고, 그 각각이 `ensure_seller_registered` 를 거쳐 최대 30초짜리 벤더 호출을
    했다 — 몫이 여럿인 Developer 의 제출 요청은 워커 타임아웃을 넘긴다.
    `advance_seller_pending_payouts` 가 이미 쓰는 모양(등록은 밖에서 한 번, 루프는
    `register_seller=False`)을 따른다.
    """

    _CountingSellerAdapter.calls = []

    with override_settings(SELLER_ADAPTER_MODE="tests.test_payouts._CountingSellerAdapter"):
        sponsor1, dev, contest1, _s1 = _ready_for_payout(
            client, category, landing_type, sponsor_uid="sponsor-phone-1", dev_uid="dev-phone-1"
        )
        requested1 = _request_payout(client, dev, contest1["id"])
        _confirm_payout(client, dev, requested1["idempotency_key"])

        ClockOverride.objects.filter(pk=1).delete()
        _sponsor2, dev_again, contest2, _s2 = _ready_for_payout(
            client, category, landing_type, sponsor_uid="sponsor-phone-2", dev_uid="dev-phone-1"
        )
        requested2 = _request_payout(client, dev_again, contest2["id"])
        _confirm_payout(client, dev_again, requested2["idempotency_key"])

        # 둘 다 Seller 대기에 걸려 있다 — 여기까지가 준비다.
        assert Payout.objects.filter(status=Payout.Status.CONFIRMED_SELLER_PENDING).count() == 2

        _CountingSellerAdapter.calls = []
        resp = client.post(
            f"{PAYOUTS_URL}/{requested1['idempotency_key']}/seller-phone",
            data={"phone_number": "01012345678"},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )

    assert resp.status_code == 200, resp.content
    assert len(_CountingSellerAdapter.calls) == 1, (
        f"Payout 2건에 벤더 등록 호출이 {len(_CountingSellerAdapter.calls)}회 났다 — "
        "Seller 는 Developer 단위라 한 번이면 된다."
    )


@pytest.mark.django_db
def test_toss_payout_webhook_falls_back_when_the_reference_is_present_but_unparseable(
    client, category, landing_type
):
    """참조가 **있는데 못 읽는** 경우에도 폴백이 산다 (#91, 코드리뷰).

    폴백을 「refPayoutId 가 아예 없을 때」로만 열어 두면, 벤더가 접미어 없는 옛
    참조를 돌려주거나 값이 잘려 오는 순간 그 웹훅은 재전송을 몇 번 받든 영구히
    422 다 — 폴백이 막으려던 바로 그 상황이다. 읽을 수 없는 참조는 「없는 것」과
    같이 취급하고 벤더 식별자로 넘어간다.
    """

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    Payout.objects.filter(idempotency_key=requested["idempotency_key"]).update(
        vendor_payout_id="toss-vendor-payout-legacy"
    )

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "entityBody": {
                # 접미어가 없다 — `parse_vendor_ref` 가 읽지 못하는 형식이다.
                "refPayoutId": str(requested["idempotency_key"]),
                "id": "toss-vendor-payout-legacy",
                "status": "COMPLETED",
            },
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
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID="whid-fallback-3",
        )

    assert resp.status_code == 200, resp.content
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING


@pytest.mark.django_db
def test_toss_payout_webhook_422s_when_neither_identifier_can_be_resolved(
    client, category, landing_type
):
    """폴백까지 실패하면 그때는 422 다 (#91) — 읽을 수 없는 참조에 짚이는
    벤더 식별자도 없으면 이 웹훅으로는 어느 Payout 인지 알 길이 없다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    _request_payout(client, dev, contest["id"])

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {"eventType": "payout.changed", "entityBody": {"refPayoutId": "not-a-reference", "status": "COMPLETED"}}
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        resp = client.post(
            f"{PAYOUTS_URL}/webhook/toss",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID="whid-fallback-4",
        )

    assert resp.status_code == 422, resp.content


# --- #173: 웹훅의 봉투는 entityBody 다 ---------------------------------------------


@pytest.mark.django_db
def test_toss_payout_webhook_422s_when_entity_body_is_missing(client, category, landing_type):
    """entityBody 자체가 없으면 「우리 추정이 또 틀렸다」는 신호다(#173) —
    #170 이 200 으로 덮은 것은 모르는 *참조*이지 못 읽는 *본문*이 아니다.
    (예전 봉투 키 `data` 로 온 웹훅이 바로 이 모양이다.)"""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "data": {"refPayoutId": f"{requested['idempotency_key']}-0", "status": "COMPLETED"},
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
    assert resp.status_code == 422, resp.content

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.REQUESTED  # 건드리지 않았다


@pytest.mark.django_db
def test_toss_seller_webhook_422s_when_entity_body_is_missing(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approval_required")

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {"eventType": "seller.changed", "data": {"refSellerId": "x", "status": "APPROVED"}}
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
    assert resp.status_code == 422, resp.content


@pytest.mark.django_db
def test_toss_seller_webhook_falls_back_to_id_field_when_ref_seller_id_is_unrecognized(
    client, category, landing_type
):
    """벤더 문서의 Seller 객체 필드는 `id` 다(#173, 웹 확인) — `sellerId` 는
    없다. `refSellerId`(우리가 보낸 `laurio-developer-{id}`)로 찾는 기존
    경로가 안 먹히면 `entityBody.id`(우리가 등록 시점에 저장해 둔
    `seller.seller_id`)로 폴백한다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approval_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.seller_id  # Fake 등록이 이미 벤더 식별자를 줬다

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "seller.changed",
            "entityBody": {
                "refSellerId": "not-our-convention",
                "id": seller.seller_id,
                "status": "PARTIALLY_APPROVED",
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
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "partially_approved"

    seller.refresh_from_db()
    assert seller.status == Seller.Status.PARTIALLY_APPROVED


@pytest.mark.django_db
def test_toss_seller_webhook_partially_approved_uses_policy_weekly_limit_not_entity_body(
    client, category, landing_type
):
    """벤더 문서의 Seller 객체에 weeklyLimit 필드가 없다(#173, 웹 확인) —
    entityBody 에 그 필드를 실어 보내도(실제로는 절대 안 온다) 무시하고
    정책의 기본 한도(ADR-0020)를 쓴다는 판단을 남긴다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="approval_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    ref_seller_id = f"laurio-developer-{developer_id}"

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "seller.changed",
            "entityBody": {
                "refSellerId": ref_seller_id,
                "id": seller.seller_id,
                "status": "PARTIALLY_APPROVED",
                # 문서에 없는 필드다 — 코드가 이 값을 읽지 않는다는 것을 함께 증명한다.
                "weeklyLimit": {"amount": 1},
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
    assert resp.status_code == 200, resp.content

    seller.refresh_from_db()
    assert seller.weekly_limit_amount == 10_000_000  # 정책 기본값 -- entityBody 의 1 이 아니다


# --- #174: 벤더 상태 어휘를 문서에 맞춘다 -------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("vendor_status", ["CANCELED", "DELETED", "REJECTED"])
def test_toss_payout_webhook_maps_undocumented_terminal_statuses_to_failed(
    client, category, landing_type, vendor_status
):
    """벤더 문서(웹 확인 — #174)의 Payout.status 일곱 값 중 CANCELED·
    DELETED·REJECTED 를 예전엔 어댑터가 예외로, 이 웹훅은 "진행 중"으로
    서로 다르게 다뤘다. 셋 다 "돈이 나가지 못했다"는 사실이므로 FAILED 와
    같은 도메인 값으로 옮긴다 — 어댑터·웹훅이 같은 표(`adapters_toss` 의
    분류 집합)를 본다."""

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "entityBody": {
                "refPayoutId": f"{requested['idempotency_key']}-0",
                "status": vendor_status,
            },
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
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID=f"whid-{vendor_status.lower()}",
        )
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "failed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.FAILED
    assert payout.journal_entry_id is None  # 원장 분개가 아예 없다 -- 첫 확정 전 거절이다.


@pytest.mark.django_db
def test_toss_payout_webhook_unknown_status_logs_loudly_and_stays_pending(
    client, category, landing_type, caplog
):
    """#174 AC: 벤더 문서의 일곱 값 밖의 새 문자열이 와도 이 Payout 하나
    때문에 요청이 죽지 않고(500이 아니라 200), 조용히 삼켜지지도 않는다
    (ERROR 로그로 크게 남는다) — 상태는 건드리지 않는다."""

    import logging

    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)
    requested = _request_payout(client, dev, contest["id"])

    transmission_time = "2024-01-01T00:00:00+09:00"
    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "entityBody": {
                "refPayoutId": f"{requested['idempotency_key']}-0",
                "status": "SOMETHING_NEW_FROM_THE_VENDOR",
            },
        }
    ).encode("utf-8")

    with override_settings(TOSS_API_SECURE_KEY=_TEST_TOSS_SECURE_KEY):
        signature = _sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        with caplog.at_level(logging.ERROR):
            resp = client.post(
                f"{PAYOUTS_URL}/webhook/toss",
                data=payload,
                content_type="application/json",
                HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
                HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
            )
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "requested"  # 건드리지 않았다

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.REQUESTED
    assert any("알 수 없는 status" in record.getMessage() for record in caplog.records)


# --- #149: 좁히기를 SQL 로 내린다 --------------------------------------------------


def _clone_blocked_payouts(count: int, *, contest_id: int, developer, status: str) -> list[Payout]:
    """막혀 있는 Payout 을 `count` 개 더 만든다 — 페이지네이션과 질의 수를 보기 위한
    부피용이다.

    HTTP 흐름(`_ready_for_payout`)을 스물몇 번 다시 태울 이유가 없다 — 여기서 확인할
    것은 개최·심사·선정이 아니라 **큐가 어떻게 좁히고 자르는가**다. 픽스처는 ORM 으로,
    단언은 HTTP 로(`test_contest_listing._publish` 와 같은 관용구).
    """

    from awards.models import Award
    from contests.models import Contest
    from handovers.models import Handover
    from submissions.models import Submission

    template = Contest.objects.get(id=contest_id)
    deliverable_types = list(template.deliverable_types.all())
    made: list[Payout] = []
    for index in range(count):
        contest = Contest.objects.create(
            sponsor=template.sponsor,
            title=f"{template.title} 사본 {index}",
            category=template.category,
            prize=template.prize,
            deadline_at=template.deadline_at,
            status=Contest.Status.CLOSED,
        )
        contest.deliverable_types.set(deliverable_types)
        submission = Submission.objects.create(
            contest=contest, developer=developer, source_object_key=f"src-{contest.id}"
        )
        award = Award.objects.create(
            contest=contest, submission=submission, awarded_at=timezone.now()
        )
        handover = Handover.objects.create(
            award=award,
            status=Handover.Status.RELEASED,
            release_deadline_at=timezone.now() + timedelta(days=7),
        )
        made.append(
            Payout.objects.create(
                handover=handover,
                prize_amount=1_000_000,
                platform_fee_amount=100_000,
                withholding_tax_amount=44_000,
                net_amount=856_000,
                platform_fee_bps=1_000,
                withholding_tax_bps=440,
                status=status,
            )
        )
    return made


@pytest.mark.django_db
def test_operator_queue_ignores_payouts_that_are_not_blocked_at_all(
    client, category, landing_type
):
    """막혀 있지 않은 Payout 은 큐의 질의에도 응답에도 없다 (#149).

    이전에는 `Payout` 테이블 전체를 가져온 뒤 파이썬 루프가 걸렀다 — 아직
    REQUESTED 이거나 이미 CONFIRMED 인 행까지 전부 DB 에서 끌어와 Seller 를 찾고
    나서야 버렸다. 확정되지 않은 지급이 쌓일수록 운영자 홈이 느려지는데, 그 행들은
    운영자가 볼 것이 아니다.
    """

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-149-1", dev_uid="dev-149-1"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer

    operator = _operator_client(username="payouts-op-149-1")
    with CaptureQueriesContext(connection) as before:
        resp = operator.get("/api/operator/payouts")
    assert [row["idempotency_key"] for row in _queue_rows(resp)] == [requested["idempotency_key"]]

    # 막혀 있지 않은 것들을 잔뜩 심는다 — 확정 전(REQUESTED)과 이미 끝난 것(CONFIRMED).
    _clone_blocked_payouts(
        10, contest_id=contest["id"], developer=developer, status=Payout.Status.REQUESTED
    )
    _clone_blocked_payouts(
        10, contest_id=contest["id"], developer=developer, status=Payout.Status.CONFIRMED
    )

    with CaptureQueriesContext(connection) as after:
        resp = operator.get("/api/operator/payouts")
    assert [row["idempotency_key"] for row in _queue_rows(resp)] == [requested["idempotency_key"]]
    assert resp.json()["count"] == 1, "막히지 않은 20건이 건수에 섞였다"
    assert len(after) == len(before), (
        "막혀 있지 않은 Payout 20건을 심었더니 질의 수가 달라졌다 — 큐가 그것들까지 "
        "가져오고 있다.\n" + "\n".join(q["sql"][:200] for q in after)
    )


@pytest.mark.django_db
def test_operator_queue_filter_narrows_the_query_not_just_the_response(
    client, category, landing_type
):
    """`blocked_on=identity` 가 DB 에서 오는 행 수를 실제로 줄인다 (#149).

    파이썬 `continue` 로 거를 때는 필터를 줘도 질의가 그대로였다 — 「지금 내가 처리할
    것은 어느 쪽인가」에 답하는 화면이 어느 쪽을 골라도 같은 비용을 냈다.
    """

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-149-2", dev_uid="dev-149-2"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    _clone_blocked_payouts(
        5,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_IDENTITY_PENDING,
    )

    operator = _operator_client(username="payouts-op-149-2")

    everything = operator.get("/api/operator/payouts")
    assert everything.json()["count"] == 6

    identity_only = operator.get("/api/operator/payouts?blocked_on=identity")
    assert identity_only.json()["count"] == 5
    assert requested["idempotency_key"] not in {
        row["idempotency_key"] for row in _queue_rows(identity_only)
    }

    seller_only = operator.get("/api/operator/payouts?blocked_on=seller")
    assert seller_only.json()["count"] == 1
    assert [row["idempotency_key"] for row in _queue_rows(seller_only)] == [
        requested["idempotency_key"]
    ]


@pytest.mark.django_db
def test_operator_queue_pages_without_losing_or_repeating_a_row(client, category, landing_type):
    """페이지가 갈려도 빠지거나 겹치는 행이 없다 (#149).

    `created_at` 만으로 정렬하면 같은 시각의 두 행 순서를 DB 가 보장할 이유가 없고,
    그러면 **같은 Payout 이 두 페이지에 나오고 다른 하나는 어느 페이지에도 안
    나온다**(#39 가 공개 목록에서 겪은 그것). 운영자 큐에서 그 누락은 「처리해야 할
    것을 못 본다」다 — 그래서 픽스처의 `created_at` 을 일부러 같은 값으로 맞춘다.
    """

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-149-3", dev_uid="dev-149-3"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    _clone_blocked_payouts(
        24,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_SELLER_PENDING,
    )
    same_moment = timezone.now()
    Payout.objects.all().update(created_at=same_moment)

    operator = _operator_client(username="payouts-op-149-3")

    first = operator.get("/api/operator/payouts")
    assert first.json()["count"] == 25
    first_keys = [row["idempotency_key"] for row in _queue_rows(first)]
    assert len(first_keys) == 20, "한 페이지가 20행이어야 한다"

    # 다음 묶음은 「마지막으로 본 행 다음부터」다(#151) — 「2페이지」가 아니다.
    second = operator.get(f"/api/operator/payouts?after={first.json()['next']}")
    second_keys = [row["idempotency_key"] for row in _queue_rows(second)]
    assert len(second_keys) == 5

    assert not set(first_keys) & set(second_keys), "같은 행이 두 페이지에 나왔다"
    assert len(set(first_keys) | set(second_keys)) == 25, "어느 페이지에도 없는 행이 있다"


@pytest.mark.django_db
def test_operator_queue_counts_answer_without_sending_the_rows(client, category, landing_type):
    """홈의 배지 숫자를 목록을 받아 세지 않는다 (#149) — 한 요청, 행 0개."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-149-4", dev_uid="dev-149-4"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    _clone_blocked_payouts(
        3,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_IDENTITY_PENDING,
    )
    # 막혀 있지 않은 것은 세지 않는다.
    _clone_blocked_payouts(
        7, contest_id=contest["id"], developer=developer, status=Payout.Status.REQUESTED
    )

    operator = _operator_client(username="payouts-op-149-4")
    resp = operator.get("/api/operator/payouts/counts")

    assert resp.status_code == 200, resp.content
    assert resp.json() == {"identity": 3, "seller": 1, "transfer": 0, "operator": 0}


@pytest.mark.django_db
def test_operator_queue_rejects_an_unknown_blocked_on_instead_of_saying_zero(
    client, category, landing_type
):
    """알 수 없는 `blocked_on` 은 빈 큐가 아니라 422 다 (#149).

    빈 큐는 「처리할 것이 없다」는 뜻이라, 오타 하나가 그렇게 읽히면 운영자가 밀린
    일을 못 본 채 지나간다(`contests.api.list_contests` 와 같은 규율).
    """

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-149-5", dev_uid="dev-149-5"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    operator = _operator_client(username="payouts-op-149-5")
    resp = operator.get("/api/operator/payouts?blocked_on=selller")

    assert resp.status_code == 422, resp.content


@pytest.mark.django_db
def test_operator_queue_resolves_seller_and_identity_for_the_distribution_path_too(
    client, category, landing_type
):
    """Seller·신원 주석이 두 지급 경로 모두에서 풀린다 (#149).

    `Payout` 은 Handover(Award 경로)나 DistributionShare(무응답 1/N 배분 경로) 중
    하나를 가리킨다. `with_hold_facts` 는 Developer 를 그 둘 중 채워진 쪽으로 찾는데,
    한쪽만 맞춰 두면 다른 경로의 Payout 은 Seller 가 있어도 NULL 로 읽혀 늘 「등록
    대기」로 분류된다 — 조용히 틀린 큐가 된다.
    """

    from distributions.models import Distribution, DistributionShare
    from submissions.models import Submission

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-149-6", dev_uid="dev-149-6"
    )
    requested = _request_payout(client, dev, contest["id"])
    # Seller 를 READY 로 만들어 둔다 — 그래야 「seller 가 아니라 transfer」라는 구별이
    # 주석이 실제로 풀렸을 때만 나온다.
    _confirm_payout(client, dev, requested["idempotency_key"])
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    assert Seller.objects.get(developer=developer).status in Seller.READY_STATUSES

    # 배분은 **다른** Contest 에서 일어난다 — 같은 Developer 가 한 Contest 에 두 번
    # 제출할 수는 없다(unique_submission_per_contest_developer).
    template = Contest.objects.get(id=contest["id"])
    contest_row = Contest.objects.create(
        sponsor=template.sponsor,
        title="배분 경로 공모전",
        category=template.category,
        prize=template.prize,
        deadline_at=template.deadline_at,
        status=Contest.Status.CLOSED,
    )
    contest_row.deliverable_types.set(template.deliverable_types.all())
    distribution = Distribution.objects.create(
        contest=contest_row,
        cutline_percentage=0,
        total_prize=1_000_000,
        qualifying_count=1,
        share_amount=1_000_000,
    )
    share_submission = Submission.objects.create(
        contest=contest_row, developer=developer, source_object_key="src-share"
    )
    share = DistributionShare.objects.create(
        distribution=distribution, submission=share_submission, amount=1_000_000
    )
    distribution_payout = Payout.objects.create(
        distribution_share=share,
        prize_amount=1_000_000,
        platform_fee_amount=100_000,
        withholding_tax_amount=44_000,
        net_amount=856_000,
        platform_fee_bps=1_000,
        withholding_tax_bps=440,
        status=Payout.Status.CONFIRMED_SELLER_PENDING,
    )

    operator = _operator_client(username="payouts-op-149-6")
    resp = operator.get("/api/operator/payouts?blocked_on=transfer")

    keys = {row["idempotency_key"] for row in _queue_rows(resp)}
    assert str(distribution_payout.idempotency_key) in keys, (
        "Distribution 경로의 Payout 에서 Seller 상태가 안 풀렸다 — READY 인데 "
        "seller 대기로 분류됐다"
    )


# --- #151: 커서 페이지네이션 --------------------------------------------------------


@pytest.mark.django_db
def test_operator_queue_does_not_repeat_or_lose_a_row_when_the_list_grows(
    client, category, landing_type
):
    """1페이지를 받은 뒤 목록이 자라도 같은 행이 두 번 나오거나 빠지지 않는다 (#151).

    오프셋(`?page=N`)이던 시절에는 **머리 쪽에서** 새 행이 하나만 생겨도 경계가 한 칸
    밀려서, 2페이지가 1페이지의 마지막 행을 다시 돌려주고 원래 그 자리에 와야 했던 행은
    어느 페이지에도 안 나왔다. 운영자 큐는 스캔이 60초마다 Payout 을 확정하므로 「더 보기」를
    누르는 그 몇 초 사이에 실제로 일어난다.
    """

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-151-1", dev_uid="dev-151-1"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    _clone_blocked_payouts(
        24,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_SELLER_PENDING,
    )

    operator = _operator_client(username="payouts-op-151-1")

    first = operator.get("/api/operator/payouts")
    assert first.status_code == 200, first.content
    first_body = first.json()
    first_keys = [row["idempotency_key"] for row in first_body["items"]]
    assert len(first_keys) == 20
    assert first_body["next"], "더 있는데 다음 커서를 주지 않았다"

    # **여기서 목록이 자란다** — 머리 쪽에 새 행이 셋 생긴다(스캔이 하는 일 그대로).
    _clone_blocked_payouts(
        3,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_SELLER_PENDING,
    )

    second = operator.get(f"/api/operator/payouts?after={first_body['next']}")
    assert second.status_code == 200, second.content
    second_keys = [row["idempotency_key"] for row in second.json()["items"]]

    assert not set(first_keys) & set(second_keys), (
        "목록이 자란 뒤 2페이지가 1페이지의 행을 다시 돌려줬다"
    )
    # 1페이지 이후로 밀린 다섯(25건 중 나머지)은 그대로 나온다 — 새로 생긴 셋은 이미 지나간
    # 커서보다 앞이라 나오지 않는 것이 옳다(그건 다음 조회의 몫이다).
    assert len(second_keys) == 5, second_keys


@pytest.mark.django_db
def test_operator_queue_walks_every_blocked_row_exactly_once(client, category, landing_type):
    """끝까지 넘기면 그 시점에 막혀 있던 모든 행이 정확히 한 번씩 나온다 (#151)."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-151-2", dev_uid="dev-151-2"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    _clone_blocked_payouts(
        44,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_SELLER_PENDING,
    )
    # 같은 시각이 섞여도 흔들리지 않아야 한다 — 정렬 마지막 키가 id 인 이유다.
    Payout.objects.all().update(created_at=timezone.now())

    operator = _operator_client(username="payouts-op-151-2")

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # 45건이면 세 번이면 끝난다 — 넉넉히 두고 무한 루프만 막는다
        url = "/api/operator/payouts" + (f"?after={cursor}" if cursor else "")
        body = operator.get(url).json()
        seen.extend(row["idempotency_key"] for row in body["items"])
        cursor = body["next"]
        if cursor is None:
            break

    assert cursor is None, "끝까지 못 갔다"
    assert len(seen) == 45, len(seen)
    assert len(set(seen)) == 45, "같은 행이 두 번 나왔다"
    assert set(seen) == set(
        str(key) for key in Payout.objects.values_list("idempotency_key", flat=True)
    )


@pytest.mark.django_db
def test_operator_queue_still_reports_the_total_count(client, category, landing_type):
    """전체 건수는 그대로 전체 건수다 (#151) — 커서로 바꾸면서 「막혀 있는 지급 N건」을
    잃지 않는다. 홈 배지와 이 숫자가 맞는다는 단언이 그 위에 서 있다."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-151-3", dev_uid="dev-151-3"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")
    developer = Payout.objects.get(idempotency_key=requested["idempotency_key"]).developer
    _clone_blocked_payouts(
        24,
        contest_id=contest["id"],
        developer=developer,
        status=Payout.Status.CONFIRMED_SELLER_PENDING,
    )

    operator = _operator_client(username="payouts-op-151-3")
    body = operator.get("/api/operator/payouts").json()

    assert body["count"] == 25
    assert len(body["items"]) == 20


@pytest.mark.django_db
def test_operator_queue_rejects_a_cursor_it_cannot_read(client, category, landing_type):
    """읽을 수 없는 커서는 조용히 처음부터가 아니라 422 다 (#151).

    조용히 1페이지를 돌려주면 「더 보기」를 눌렀는데 목록이 처음으로 되돌아간 화면이 되고,
    운영자는 무엇을 봤고 무엇을 못 봤는지 알 수 없게 된다.
    """

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="sponsor-151-4", dev_uid="dev-151-4"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    operator = _operator_client(username="payouts-op-151-4")
    resp = operator.get("/api/operator/payouts?after=not-a-cursor")

    assert resp.status_code == 422, resp.content
