"""운영자 지급 큐가 막힌 지급을 실제로 진행시킨다 (#182).

셋업 헬퍼는 `tests.test_payouts` 의 것을 그대로 쓴다. Origin 검증
(`OperatorOriginMiddleware`, ADR-0016)이 걸리므로 운영자의 모든 변경 요청에
`HTTP_ORIGIN`을 붙인다 — `test_appeals.py` 와 같은 관용구다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import override_settings

from contests.models import Category, DeliverableType
from ledger.services import contest_balance
from payouts.models import OperatorPayoutAction, Payout, Seller
from payouts.progress import MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS
from tests import test_payouts as p

OPERATOR_ORIGIN = "http://testserver"
SELLER_RECOVERY_SCAN_URL = "/api/internal/scans/seller-registration-recovery"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="관리자 페이지", minimum_prize=500_000)


def _operator_post(operator, path):
    return operator.post(path, HTTP_ORIGIN=OPERATOR_ORIGIN)


@pytest.mark.django_db
def test_operator_can_retry_a_rejected_seller_registration(client, category, landing_type):
    """SELLER_REJECTED — 운영자가 큐에서 재등록을 트리거할 수 있고, 기존 재시도
    경로(`retry_seller_registration`, Developer 의 「다시 시도」와 같은 함수)를
    그대로 탄다. 누가 눌렀는지 남는다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="rejected")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert Seller.objects.get(developer_id=payout.handover.award.submission.developer_id).status == (
        Seller.Status.REJECTED
    )

    operator = p._operator_client(username="payout-retry-op-1")

    # 큐 화면이 버튼을 뜨게 하는 바로 그 신호다 — 세 갈래(SELLER_REJECTED·
    # SELLER_REGISTRATION_STUCK·TRANSFER_OPERATOR) 모두 이 필드로 게이트되므로,
    # 이 값이 실제 재시도 가능 여부와 갈리면 버튼은 있는데 눌러도 409만 돌아온다.
    queue_resp = operator.get("/api/operator/payouts?blocked_on=seller")
    row = next(
        r for r in queue_resp.json()["items"]
        if r["idempotency_key"] == requested["idempotency_key"]
    )
    assert row["operator_actionable"] is True

    resp = _operator_post(
        operator, f"/api/operator/payouts/{requested['idempotency_key']}/retry"
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    # 기본 Fake 어댑터로 재등록하면 즉시 부분 승인이다 — Seller 대기가 풀린다.
    assert body["status"] in ("confirmed_identity_pending", "confirmed")
    assert body["blocked_on"] != "seller"

    seller = Seller.objects.get(developer_id=payout.handover.award.submission.developer_id)
    assert seller.status in Seller.READY_STATUSES

    action = OperatorPayoutAction.objects.get(payout=payout)
    assert action.operator.username == "payout-retry-op-1"
    assert action.hold_kind == "seller_rejected"

    ledger_id = _contest_ledger_id(contest["id"])
    assert contest_balance(ledger_id)["is_balanced"] is True


def _contest_ledger_id(contest_id):
    from contests.models import Contest

    return Contest.objects.get(id=contest_id).ledger_id


class _AlwaysFailingSellerAdapter(p.FakeSellerAdapter):
    """실물 어댑터의 5xx 를 흉내내는 테스트 더블 — `register()`가 항상
    `SellerError`를 던진다(#57 코드리뷰와 같은 모양, 이 파일 전용 사본이다).
    `override_settings(SELLER_ADAPTER_MODE=...)`가 dotted path 로 클래스를
    import 하므로 모듈 최상위에 있어야 한다."""

    def register(self, registration, *, simulate=None):
        from payouts.adapters import SellerError

        raise SellerError("fake vendor 5xx")


@pytest.mark.django_db
def test_operator_can_retry_a_stuck_seller_registration(client, category, landing_type):
    """SELLER_REGISTRATION_STUCK(#178) — 자력 회복 스캔이 포기한 뒤에도 운영자가
    같은 재등록 경로로 풀 수 있다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._submit_seller_contact(
        client, dev, requested["idempotency_key"],
        phone_number="01099998888", email="stuck@example.com",
    )

    with override_settings(
        SELLER_ADAPTER_MODE=f"{__name__}._AlwaysFailingSellerAdapter"
    ):
        p._confirm_payout(client, dev, requested["idempotency_key"])
        for _ in range(MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS - 1):
            resp = client.post(SELLER_RECOVERY_SCAN_URL, **_internal_headers())
            assert resp.status_code == 200

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    assert Seller.objects.get(developer_id=developer_id).registration_error_count == (
        MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS
    )

    operator = p._operator_client(username="payout-retry-op-2")
    queue_resp = operator.get("/api/operator/payouts?blocked_on=seller")
    row = next(
        r for r in queue_resp.json()["items"]
        if r["developer_user_id"] == payout.handover.award.submission.developer.user_id
    )
    assert row["seller_registration_status"] == "stuck"
    assert row["operator_actionable"] is True

    retry_resp = _operator_post(
        operator, f"/api/operator/payouts/{requested['idempotency_key']}/retry"
    )
    assert retry_resp.status_code == 200, retry_resp.content

    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status in Seller.READY_STATUSES
    assert seller.registration_error_count == 0


@pytest.mark.django_db
def test_operator_can_retry_a_confirmed_payout_with_failed_transfer(client, category, landing_type):
    """TRANSFER_OPERATOR — CONFIRMED 뒤 뒤늦게 실이체 실패가 확인된 경우, 지금까지
    아무도 다시 부를 수 없던 실이체를 운영자가 재시도할 수 있다(#182)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    # 기본(정상) Fake 어댑터로 끝까지 보낸다 — Seller 가 즉시 READY 가 되고
    # 실이체도 즉시 성공해, 신원까지 내면 CONFIRMED·COMPLETED 에 닿는다.
    p._confirm_payout(client, dev, requested["idempotency_key"])
    identity_resp = client.post(
        f"{p.PAYOUTS_URL}/{requested['idempotency_key']}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **p._auth_header(dev["access"]),
    )
    assert identity_resp.json()["status"] == "confirmed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED
    assert payout.transfer_status == Payout.TransferStatus.COMPLETED

    # 뒤늦게 벤더가 이 실이체를 실패로 보고했다고 흉내낸다 — 실물 웹훅이 지연
    # 도착하는 경로의 대역이다(`payouts.services.resolve_transfer_webhook`의
    # "failed" 분기가 실제로 반영하는 것과 같은 값: `status`는 그대로 두고
    # `transfer_status`만 바꾼다, ADR-0004).
    Payout.objects.filter(pk=payout.pk).update(transfer_status=Payout.TransferStatus.FAILED)

    operator = p._operator_client(username="payout-retry-op-3")
    queue_resp = operator.get("/api/operator/payouts?blocked_on=transfer")
    row = next(
        r for r in queue_resp.json()["items"]
        if r["developer_user_id"] == payout.handover.award.submission.developer.user_id
    )
    assert row["operator_actionable"] is True

    retry_op_resp = _operator_post(
        operator, f"/api/operator/payouts/{requested['idempotency_key']}/retry"
    )
    assert retry_op_resp.status_code == 200, retry_op_resp.content
    assert retry_op_resp.json()["transfer_status"] == "completed"

    payout.refresh_from_db()
    assert payout.status == Payout.Status.CONFIRMED
    assert payout.transfer_status == Payout.TransferStatus.COMPLETED

    action = OperatorPayoutAction.objects.get(payout=payout)
    assert action.hold_kind == "transfer_operator"


@pytest.mark.django_db
def test_operator_retry_rejects_a_developer_turn_payout(client, category, landing_type):
    """운영자 전용 재시도 로직이 아니다 — Developer 의 차례인 Payout(예: 신원
    미제출)에는 이 엔드포인트가 아무 것도 하지 않고 409다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"])

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING

    operator = p._operator_client(username="payout-retry-op-4")

    # 큐에서도 이 행에는 버튼이 뜨지 않아야 한다 — Developer 의 차례에 진행
    # 버튼을 보여주면 눌러도 서버가 거절하는 버튼이 된다.
    queue_resp = operator.get("/api/operator/payouts?blocked_on=identity")
    row = next(
        r for r in queue_resp.json()["items"]
        if r["idempotency_key"] == requested["idempotency_key"]
    )
    assert row["operator_actionable"] is False

    resp = _operator_post(
        operator, f"/api/operator/payouts/{requested['idempotency_key']}/retry"
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_operator_retry_rejects_an_unknown_hold_combination(client, category, landing_type, caplog):
    """UNKNOWN(표에 없는 조합)에는 버튼이 아니라 사람의 판단이 필요하다는 것이
    이 티켓의 결정이다(#182 AC) — 이 엔드포인트는 그 갈래를 받지 않는다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    Payout.objects.filter(idempotency_key=requested["idempotency_key"]).update(status="bogus")

    operator = p._operator_client(username="payout-retry-op-5")
    resp = _operator_post(
        operator, f"/api/operator/payouts/{requested['idempotency_key']}/retry"
    )
    assert resp.status_code == 409
    assert not OperatorPayoutAction.objects.filter(
        payout__idempotency_key=requested["idempotency_key"]
    ).exists()


@pytest.mark.django_db
def test_non_operator_cannot_retry_a_payout(client, category, landing_type):
    """세션 자체가 없으면 401, Operator 가 아니면 403 — 라우터 기본값
    (`OperatorAuth`)이 지킨다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="rejected")

    resp = client.post(
        f"/api/operator/payouts/{requested['idempotency_key']}/retry",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert resp.status_code in (401, 403)
