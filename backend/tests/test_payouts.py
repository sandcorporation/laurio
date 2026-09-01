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
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from handovers.models import Handover
from ledger.services import contest_entries
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
    묻는다. "요율 필드가 있다"에서 멈추지 않고 요율을 실제로 바꿔 확인한다."""

    from policies.models import PlatformPolicy

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

    # 운영자가 요율을 바꿨다고 가정한다 — DB 행을 직접 조정한다
    # (distributions.models.DistributionCutline을 테스트가 조정하는 것과 같은
    # 관용구, 운영자 API는 #76의 몫).
    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"platform_fee_bps": 1500, "withholding_tax_bps": 500}
    )

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
