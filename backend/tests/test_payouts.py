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
from payouts.adapters import FakePayoutAdapter
from payouts.models import Payout, TaxIdentity

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
    client, *, category, deliverable_type, sponsor_uid="sponsor-1", deadline_at=None
) -> tuple[dict, dict]:
    sponsor = _verified_user(client, sponsor_uid, f"{sponsor_uid}-ci")
    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))

    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{sponsor_uid}의 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "prize": 1_000_000,
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


def _ready_for_payout(client, category, landing_type, *, sponsor_uid="sponsor-1", dev_uid="dev-1"):
    """Escrow까지 해제된 Contest 하나를 만들어 (sponsor, dev, contest, submission)를
    돌려준다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid=sponsor_uid, deadline_at=deadline,
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


def _confirm_payout(client, dev: dict, idempotency_key: str, *, simulate=None):
    return client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/confirm",
        data={"simulate": simulate} if simulate is not None else {},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )


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
    sponsor, dev, contest, submission = _ready_for_payout(client, category, landing_type)

    payout = _request_payout(client, dev, contest["id"])
    prize = contest["prize"]
    expected_fee = prize * settings.PAYOUT_PLATFORM_FEE_BPS // 10_000
    expected_withholding = prize * settings.PAYOUT_WITHHOLDING_TAX_BPS // 10_000
    expected_net = prize - expected_fee - expected_withholding

    assert payout["prize_amount"] == prize
    assert payout["platform_fee_amount"] == expected_fee
    assert payout["withholding_tax_amount"] == expected_withholding
    assert payout["net_amount"] == expected_net
    assert payout["status"] == "requested"


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
