"""Payout 정산 상태기계(`payouts.progress.advance`)의 표 — 네 축의 조합마다 결과 하나 (#131).

입구가 무엇이든(신원 제출·재시도·웹훅·sweep·확정) 같은 advance 가 같은 답을 내므로, 조합은
한 곳에 적고 입구별 도달 순서만 다르다. HTTP 가 유일한 시임이다(CLAUDE.md) — 셋업 헬퍼는
`tests.test_payouts` 의 것을 그대로 쓴다.
"""

from __future__ import annotations

import pytest

from contests.models import Category, DeliverableType
from payouts.models import Payout, TaxIdentity
from tests import test_payouts as p


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _submit_identity(client, dev, idempotency_key, rrn="9001011234567"):
    return client.post(
        f"{p.PAYOUTS_URL}/{idempotency_key}/identity",
        data={"resident_registration_number": rrn},
        content_type="application/json",
        **p._auth_header(dev["access"]),
    )


# (Seller 등록 시나리오, 신원 제출 뒤 기대 status). Fake 실이체는 기본 즉시 COMPLETED 다.
IDENTITY_TABLE = [
    pytest.param(None, "confirmed", id="seller-ready"),
    pytest.param("approved", "confirmed", id="seller-approved"),
    pytest.param("review_required", "confirmed_seller_pending", id="seller-under-review"),
    pytest.param("approval_required", "confirmed_seller_pending", id="seller-auth-required"),
    pytest.param("rejected", "confirmed_seller_pending", id="seller-rejected"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("seller_simulate,expected", IDENTITY_TABLE)
def test_identity_submission_advances_by_the_two_waits_table(
    client, category, landing_type, seller_simulate, expected
):
    """신원 제출 뒤의 상태는 Seller 가 READY 인가에만 달렸다 — READY 면 실이체까지 확정돼
    CONFIRMED, 아니면 남은 한 대기(Seller)만 보여준다(ADR-0020)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"], seller_simulate=seller_simulate)

    resp = _submit_identity(client, dev, requested["idempotency_key"])
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == expected
    assert resp.json()["has_identity"] is True


@pytest.mark.django_db
def test_identity_resubmission_after_confirmed_replaces_the_value_and_keeps_confirmed(
    client, category, landing_type
):
    """CONFIRMED 뒤의 정정 제출 — 표에서 아직 검증되지 않았던 칸. 상태는 그대로이고 값만 바뀐다
    (TaxIdentity 는 세무 신고용 현재값 저장소지 원장이 아니다)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"])
    first = _submit_identity(client, dev, requested["idempotency_key"], rrn="9001011234567")
    assert first.json()["status"] == "confirmed"

    second = _submit_identity(client, dev, requested["idempotency_key"], rrn="9001017654321")
    assert second.status_code == 200, second.content
    assert second.json()["status"] == "confirmed"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED
    identity = TaxIdentity.objects.get(payout=payout)
    from verification.crypto import decrypt

    assert decrypt(identity.resident_registration_number_encrypted) == "9001017654321"


def _toss_payout_webhook(client, *, idempotency_key: str, vendor_status: str, attempt: int = 0):
    """실물 payout.changed 웹훅 — refPayoutId 는 `{key}-{attempt}` 형식이다."""

    import json

    from django.test import override_settings

    payload = json.dumps(
        {
            "eventType": "payout.changed",
            "entityBody": {"refPayoutId": f"{idempotency_key}-{attempt}", "status": vendor_status},
        }
    ).encode("utf-8")
    transmission_time = "2024-01-01T00:00:00+09:00"
    with override_settings(TOSS_API_SECURE_KEY=p._TEST_TOSS_SECURE_KEY):
        signature = p._sign_toss_webhook(payload=payload, transmission_time=transmission_time)
        return client.post(
            f"{p.PAYOUTS_URL}/webhook/toss",
            data=payload,
            content_type="application/json",
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_TIME=transmission_time,
            HTTP_TOSSPAYMENTS_WEBHOOK_SIGNATURE=signature,
            HTTP_TOSSPAYMENTS_WEBHOOK_TRANSMISSION_ID="whid-progress",
        )


@pytest.mark.django_db
def test_late_paid_webhook_after_identity_with_failed_transfer_reaches_confirmed(
    client, category, landing_type
):
    """표의 빈칸이었던 조합 — 확정 시점에 Seller 가 이미 READY 라 신원 대기(CIP)로 갔는데 실이체는
    거절됐고, 그 상태에서 신원을 냈다(실이체가 아직이라 CIP 에 머문다). 뒤늦게 payout.changed
    COMPLETED 가 오면 두 대기가 모두 풀린 것이므로 CONFIRMED 다. (#132: 웹훅 입구도 사실만
    기록하고 advance 가 판정한다 — 전에는 이 조합에서 status 가 CIP 에 그대로 남았다.)"""

    from django.test import override_settings

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    key = requested["idempotency_key"]

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
    ):
        confirmed = p._confirm_payout(client, dev, key)
        assert confirmed.json()["status"] == "confirmed_identity_pending"
        assert confirmed.json()["transfer_status"] == "failed"

        identity = _submit_identity(client, dev, key)
        assert identity.json()["status"] == "confirmed_identity_pending"  # 실이체가 아직
        assert identity.json()["has_identity"] is True

    # 웹훅의 refPayoutId 는 지금 진행 중인 attempt 를 가리켜야 한다 — caller 가 실이체를 시도하며
    # attempt 를 선점했으므로(#135) 기본값 0 이 아니다. 낡은 attempt 의 배달은 조용히 버려진다.
    attempt = Payout.objects.get(idempotency_key=key).transfer_attempt
    resp = _toss_payout_webhook(client, idempotency_key=key, vendor_status="COMPLETED", attempt=attempt)
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "confirmed"

    payout = Payout.objects.get(idempotency_key=key)
    assert payout.status == Payout.Status.CONFIRMED
    assert payout.transfer_status == Payout.TransferStatus.COMPLETED


@pytest.mark.django_db
def test_failed_vendor_webhook_before_any_confirm_ends_the_attempt_as_failed(
    client, category, landing_type
):
    """REQUESTED 에서 실물 웹훅이 FAILED 를 보고하면 이 시도는 FAILED 로 끝난다 — 원장에는
    아무것도 남지 않고, 새 요청을 낼 수 있다(표의 빈칸이었던 「실물 웹훅 경유 mark_failed」)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    key = requested["idempotency_key"]

    resp = _toss_payout_webhook(client, idempotency_key=key, vendor_status="FAILED")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "failed"

    payout = Payout.objects.get(idempotency_key=key)
    assert payout.status == Payout.Status.FAILED
    assert payout.journal_entry_id is None

    retry = p._request_payout(client, dev, contest["id"])
    assert retry["idempotency_key"] != key
