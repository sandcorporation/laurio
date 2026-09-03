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
