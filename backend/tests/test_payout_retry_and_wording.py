"""실패한 지급의 재시도 버튼과, 신원 기록됨 갈래의 문구 정정 (#181).

셋업 헬퍼는 `tests.test_payouts` 의 것을 그대로 쓴다(HTTP 가 유일한 시임이라는
규율은 다른 payout 테스트 파일들과 같다).
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from contests.models import Category, DeliverableType
from ledger.services import contest_balance
from payouts.models import Payout
from tests import test_payouts as p


@pytest.fixture
def category(db):
    return Category.objects.create(name="교육")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="모바일 앱", minimum_prize=500_000)


@pytest.mark.django_db
def test_requesting_payout_again_after_a_failed_attempt_creates_a_new_active_payout(
    client, category, landing_type
):
    """벤더가 거절해 Payout 이 FAILED 로 끝나도, 화면이 시키는 대로 다시 요청할 수
    있다(#181) — 백엔드는 이미 이 경우를 지원한다(`get_or_create_payout`). 새
    재시도 경로가 아니라 처음 요청과 같은 엔드포인트를 그대로 탄다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    failed_resp = p._confirm_payout(client, dev, requested["idempotency_key"], simulate="failed")
    assert failed_resp.json()["status"] == "failed"

    retry_resp = p._request_payout(client, dev, contest["id"])
    assert retry_resp["status"] == "requested"
    # 새 Payout 이다 -- 실패한 시도를 되살리지 않는다(#50 이 이미 세운 규율,
    # get_or_create_payout 독스트링).
    assert retry_resp["idempotency_key"] != requested["idempotency_key"]

    # 두 번째 시도는 정상적으로 끝까지 진행할 수 있다.
    confirm_resp = p._confirm_payout(client, dev, retry_resp["idempotency_key"])
    assert confirm_resp.json()["status"] in (
        "confirmed_identity_pending",
        "confirmed_seller_pending",
    )

    # 활성 지급이 하나뿐이다 -- 화면이 부추기는 중복 요청 경로를 열지 않는다
    # (#181 AC "활성 지급이 있을 때는 버튼이 없다"는 프론트가 지키고, 백엔드는
    # 활성 Payout 이 하나만 남는다는 사실로 그것을 뒷받침한다).
    active_count = Payout.objects.filter(
        handover__award__contest_id=contest["id"], status__in=Payout.Status.ACTIVE.statuses
    ).count()
    assert active_count == 1

    ledger_id = _contest_ledger_id(contest["id"])
    assert contest_balance(ledger_id)["is_balanced"] is True


def _contest_ledger_id(contest_id):
    from contests.models import Contest

    return Contest.objects.get(id=contest_id).ledger_id


@pytest.mark.django_db
def test_transfer_retry_identity_recorded_message_does_not_ask_for_the_rrn_again(
    client, category, landing_type
):
    """「실이체 실패 · 신원 기록됨」은 정의상 주민등록번호가 이미 제출된 상태다
    (#181) — 문구가 이미 낸 값을 다시 내라고 하지 않고, 실제로 가능한 행동
    (이체 재시도)을 안내한다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
    ):
        p._confirm_payout(client, dev, requested["idempotency_key"])
        identity_resp = client.post(
            f"{p.PAYOUTS_URL}/{requested['idempotency_key']}/identity",
            data={"resident_registration_number": "9001011234567"},
            content_type="application/json",
            **p._auth_header(dev["access"]),
        )

    body = identity_resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["transfer_status"] == "failed"
    assert body["has_identity"] is True

    message = body["next_action_message"]
    assert "계속 제출해주세요" not in message
    assert "다시 시도" in message


@pytest.mark.django_db
def test_identity_missing_with_failed_transfer_still_asks_for_the_rrn(
    client, category, landing_type
):
    """옆 갈래(신원 미제출 + 이체 실패)는 계속 주민등록번호 제출을 안내해야
    한다(#181 AC "빌려 쓰는 쪽의 문구는 그쪽에 맞게 유지한다") — 이 문구가
    TRANSFER_RETRY_IDENTITY_RECORDED 자신의 문구가 바뀌어도 흔들리지 않는지
    확인한다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
    ):
        confirm_resp = p._confirm_payout(client, dev, requested["idempotency_key"])

    body = confirm_resp.json()
    assert body["status"] == "confirmed_identity_pending"
    assert body["transfer_status"] == "failed"
    assert body["has_identity"] is False

    message = body["next_action_message"]
    assert "주민등록번호를 제출해주세요" in message
    assert "다시 시도" in message
