"""접수되지 않은 Seller 등록의 자력 회복 스캔 (#178).

**시나리오.** Developer 가 연락처를 냈고 Laurio 가 토스에 등록을 시도했는데
토스가 5xx 를 냈다. 이 스캔이 끝나면 그 일시적 벤더 오류가 상금을 영구히
잠그지 않는다 — 시스템이 스스로 다시 시도해 회복하거나, 상한만큼 시도하고도
안 풀리면 Operator 의 차례로 넘긴다.

셋업 헬퍼는 `tests.test_payouts` 의 것을 그대로 쓴다(HTTP 가 유일한 시임이라는
규율은 `test_payout_notifications.py`·`test_payout_progress.py` 와 같다). 스캔
자체는 내부 엔드포인트(`/api/internal/scans/seller-registration-recovery`)로
하나만 돌린다(#137/#140 관용구). 벤더 5xx 는 `payouts.adapters.SellerError` 를
던지는 테스트 더블을 `SELLER_ADAPTER_MODE` 로 바꿔 붙여 재현한다(#57 코드리뷰의
`_AlwaysFailingSellerAdapter` 와 같은 관용구) — Fake 어댑터의 시나리오
(`simulate=`)만으로는 이 예외 자체를 낼 수 없어서다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import override_settings

from contests.models import Category, DeliverableType
from ledger.services import contest_balance
from payouts.adapters import FakeSellerAdapter, SellerError
from payouts.models import Payout, Seller
from payouts.progress import MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS
from tests import test_payouts as p

SCAN_URL = "/api/internal/scans/seller-registration-recovery"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _run_scan(client):
    resp = client.post(SCAN_URL, **_internal_headers())
    assert resp.status_code == 200, resp.content
    return resp.json()


def _get_payout(client, dev, contest_id):
    resp = client.get(f"{p.CONTESTS_URL}/{contest_id}/payout", **p._auth_header(dev["access"]))
    assert resp.status_code == 200, resp.content
    return resp.json()


class _AlwaysFailingSellerAdapter(FakeSellerAdapter):
    """실물 어댑터의 5xx·네트워크 장애를 흉내내는 테스트 더블 — `register()`가
    항상 `SellerError`를 던진다(#57 코드리뷰의 것과 같은 모양, 이 파일 전용
    사본이다 — 서로 다른 파일이 같은 클래스를 얹으면 어느 한쪽이 몰래 바뀌어도
    다른 쪽 테스트가 못 잡는다)."""

    def register(self, registration, *, simulate: str | None = None):
        raise SellerError("fake vendor 5xx")


def _confirm_with_vendor_error(client, dev, idempotency_key):
    with override_settings(SELLER_ADAPTER_MODE=f"{__name__}._AlwaysFailingSellerAdapter"):
        return p._confirm_payout(client, dev, idempotency_key)


def _run_scan_with_vendor_error(client):
    with override_settings(SELLER_ADAPTER_MODE=f"{__name__}._AlwaysFailingSellerAdapter"):
        return _run_scan(client)


@pytest.mark.django_db
def test_confirming_with_a_failing_vendor_leaves_the_payout_recoverable(
    client, category, landing_type
):
    """벤더 5xx 로 첫 등록이 접수되지 않아도 Payout 은 정체하지 않는다(#178
    핵심 불변식) — Seller 는 PENDING·`seller_id` 는 빈 값으로 남고, 원장 분개는
    그대로다(ADR-0004)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._submit_seller_contact(
        client, dev, requested["idempotency_key"],
        phone_number="01011112222", email="dev@example.com",
    )

    confirm_resp = _confirm_with_vendor_error(client, dev, requested["idempotency_key"])
    assert confirm_resp.status_code == 200, confirm_resp.content
    body = confirm_resp.json()
    assert body["status"] == "confirmed_seller_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status == Seller.Status.PENDING
    assert seller.seller_id == ""
    assert seller.registration_error_count == 1

    # 원장은 그대로다 — 확정 시점에 이미 남은 수수료·원천징수 분개가 사라지지 않는다.
    ledger_id = _contest_ledger_id(contest["id"])
    assert contest_balance(ledger_id)["is_balanced"] is True

    # 화면이 거짓말하지 않는다 — "진행 중"이 아니라 "접수되지 않았고 자동으로
    # 다시 시도한다"고 말한다.
    message = _get_payout(client, dev, contest["id"])["next_action_message"]
    assert "접수되지 않았" in message
    assert "자동으로 다시 시도" in message


def _contest_ledger_id(contest_id):
    from contests.models import Contest

    return Contest.objects.get(id=contest_id).ledger_id


@pytest.mark.django_db
def test_scan_recovers_once_the_vendor_starts_accepting_the_registration(
    client, category, landing_type
):
    """스캔이 실패한 등록을 다시 시도하고, 벤더가 이번엔 받아들이면 대기 중이던
    Payout 이 그대로 다음 단계로 이어진다(#178 AC — 새 진행 경로를 만들지
    않는다, `advance_seller_pending_payouts` 가 그대로 이어받는다)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._submit_seller_contact(
        client, dev, requested["idempotency_key"],
        phone_number="01033334444", email="dev2@example.com",
    )
    _confirm_with_vendor_error(client, dev, requested["idempotency_key"])

    # 스캔이 아직 벤더가 살아나지 않은 동안 한 번 더 실패해도 죽지 않는다.
    scan_result = _run_scan_with_vendor_error(client)
    assert scan_result["failed"] == []

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id
    assert Seller.objects.get(developer_id=developer_id).registration_error_count == 2

    # 이제 벤더가 정상으로 돌아온다(기본 Fake 어댑터) — 스캔이 등록을 접수시키고
    # 대기 중이던 Payout 을 그대로 밀어준다.
    scan_result = _run_scan(client)
    assert len(scan_result["rows"]) == 1
    assert scan_result["rows"][0]["developer_id"] == developer_id

    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.status in Seller.READY_STATUSES
    assert seller.seller_id != ""
    assert seller.registration_error_count == 0

    payout.refresh_from_db()
    # 신원은 아직 안 냈으므로 신원 대기로 — Seller 대기는 풀렸다.
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING

    # 회복된 뒤에는 더 이상 이 스캔의 후보가 아니다(멱등 — 계속 벤더를 부르지 않는다).
    scan_result = _run_scan(client)
    assert scan_result["rows"] == []


@pytest.mark.django_db
def test_repeated_vendor_errors_stop_retrying_and_escalate_to_operator(
    client, category, landing_type
):
    """계속 실패해도 스캔이 죽지 않고, 상한만큼 시도한 뒤에는 재시도를 멈추고
    Operator 의 차례로 넘긴다(#178 AC) — 벤더에 같은 요청을 무한히 쏘지 않는다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._submit_seller_contact(
        client, dev, requested["idempotency_key"],
        phone_number="01055556666", email="dev3@example.com",
    )
    _confirm_with_vendor_error(client, dev, requested["idempotency_key"])  # 1회째 오류

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.developer_id

    # 상한에 이를 때까지 스캔이 계속 재시도한다.
    for _ in range(MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS - 1):
        result = _run_scan_with_vendor_error(client)
        assert result["failed"] == []

    seller = Seller.objects.get(developer_id=developer_id)
    assert seller.registration_error_count == MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS
    assert seller.seller_id == ""

    # 상한에 이른 뒤에는 더 이상 후보가 아니다 — 벤더를 무한히 다시 부르지 않는다.
    result = _run_scan_with_vendor_error(client)
    assert result["rows"] == []
    seller.refresh_from_db()
    assert seller.registration_error_count == MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS

    # 화면이 사실대로 말한다 — Operator 의 차례.
    message = _get_payout(client, dev, contest["id"])["next_action_message"]
    assert "반복적으로 접수되지 않았" in message
    assert "운영자" in message

    # 원장은 여전히 그대로다.
    ledger_id = _contest_ledger_id(contest["id"])
    assert contest_balance(ledger_id)["is_balanced"] is True

    # 운영자 큐도 "지급대행사 처리 대기"가 아니라 사람의 차례임을 구별해 낼 수
    # 있는 사실을 함께 내려준다(#178 남은 인수조건).
    operator = p._operator_client(username="seller-recovery-op")
    queue_resp = operator.get("/api/operator/payouts?blocked_on=seller")
    assert queue_resp.status_code == 200
    rows = queue_resp.json()["items"]
    row = next(r for r in rows if r["developer_user_id"] == payout.handover.award.submission.developer.user_id)
    assert row["seller_registration_status"] == "stuck"
