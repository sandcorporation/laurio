"""「지급이 당신을 기다린다」 알림 스캔 (#169, ADR-0009, ADR-0010 개정).

셋업 헬퍼는 `tests.test_payouts` 의 것을 그대로 쓴다(HTTP 가 유일한 시임이라는
규율은 `test_payout_progress.py` 와 같다). 스캔 자체는 내부 엔드포인트
(`/api/internal/scans/payout-awaits-you`)로 하나만 돌린다(#137/#140 관용구).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.test import override_settings

from contests.models import Category, DeliverableType
from core.models import ClockOverride
from notifications.models import Notification, NotificationType
from payouts.models import Payout, Seller
from tests import test_payouts as p

KST = ZoneInfo("Asia/Seoul")
SCAN_URL = "/api/internal/scans/payout-awaits-you"


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _run_scan(client):
    resp = client.post(SCAN_URL, **_internal_headers())
    assert resp.status_code == 200, resp.content
    return resp.json()


def _payout_awaits_you_notifications(user_id):
    return Notification.objects.filter(
        recipient_id=user_id, notification_type=NotificationType.PAYOUT_AWAITS_YOU
    )


@pytest.mark.django_db
def test_payout_awaiting_identity_sends_exactly_one_sms(client, category, landing_type):
    """이메일이 없는 Developer 도(#168) 신원 미제출로 CONFIRMED_IDENTITY_PENDING 에
    남는 것과 같은 모양이다 — 차례가 Developer 로 바뀐 Payout 에 SMS 가 정확히
    한 번 나간다. 스캔을 두 번 돌려도 둘이 되지 않는다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    confirm_resp = p._confirm_payout(client, dev, requested["idempotency_key"])
    assert confirm_resp.json()["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_user_id = payout.handover.award.submission.contestsubmission.developer.user_id

    result = _run_scan(client)
    assert result["count"] == 1
    notifications = _payout_awaits_you_notifications(developer_user_id)
    assert notifications.count() == 1
    assert notifications.first().context["hold_kind"] == "identity"

    # 다시 돌려도 멱등 — 여전히 하나다.
    _run_scan(client)
    assert _payout_awaits_you_notifications(developer_user_id).count() == 1


@pytest.mark.django_db
def test_payout_awaiting_vendor_turn_gets_no_notification(client, category, landing_type):
    """벤더의 차례(심사 대기)에는 나가지 않는다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    confirm_resp = p._confirm_payout(
        client, dev, requested["idempotency_key"], seller_simulate="review_required"
    )
    assert confirm_resp.json()["status"] == "confirmed_seller_pending"
    assert confirm_resp.json()["seller_status"] == "under_review"

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_user_id = payout.handover.award.submission.contestsubmission.developer.user_id

    result = _run_scan(client)
    assert result["count"] == 0
    assert _payout_awaits_you_notifications(developer_user_id).count() == 0


@pytest.mark.django_db
def test_payout_awaiting_missing_contact_sends_notification(client, category, landing_type):
    """#168 이 넓힌 SELLER_CONTACT 도 이 스캔이 그대로 이어받는다 — 새 개념을
    들이지 않고 `hold_of` 를 다시 계산할 뿐이다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"], seller_simulate="review_required")

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_id = payout.handover.award.submission.contestsubmission.developer_id
    developer_user_id = payout.handover.award.submission.contestsubmission.developer.user_id
    # 실물 어댑터가 연락처 없이 PENDING 에 머무는 상황을 흉내낸다(#168 과 같은
    # 관용구) — Fake 는 이 상태를 직접 만들 시나리오가 없다.
    Seller.objects.filter(developer_id=developer_id).update(status=Seller.Status.PENDING, seller_id="")

    result = _run_scan(client)
    assert result["count"] == 1
    notification = _payout_awaits_you_notifications(developer_user_id).get()
    assert notification.context["hold_kind"] == "seller_contact"


@pytest.mark.django_db
def test_retry_failure_after_retry_failure_notifies_again(client, category, landing_type):
    """재시도가 다시 실패하면 다시 간다 — 시도 횟수가 dedup_context 에 실려 두
    번째 거절도 침묵 속에서 일어나지 않는다(#57 5차 코드리뷰, #169)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
    ):
        p._confirm_payout(
            client, dev, requested["idempotency_key"], seller_simulate="review_required"
        )
        # Seller 가 READY 가 되도록 재시도한다 — 실이체 자체는 이 어댑터 아래서 거절된다.
        first_retry = p._retry_seller_registration(client, dev, requested["idempotency_key"])
        assert first_retry.json()["transfer_status"] == "failed"

        payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
        developer_user_id = payout.handover.award.submission.contestsubmission.developer.user_id

        first_result = _run_scan(client)
        assert first_result["count"] == 1
        assert _payout_awaits_you_notifications(developer_user_id).count() == 1

        # 같은 attempt 로 다시 스캔해도 하나 그대로다.
        _run_scan(client)
        assert _payout_awaits_you_notifications(developer_user_id).count() == 1

        # 재시도가 다시 실패한다 — transfer_attempt 가 오른다.
        second_retry = p._retry_seller_registration(client, dev, requested["idempotency_key"])
        assert second_retry.json()["transfer_status"] == "failed"

    second_result = _run_scan(client)
    assert second_result["count"] == 1
    assert _payout_awaits_you_notifications(developer_user_id).count() == 2


@pytest.mark.django_db
def test_payout_notification_sends_immediately_at_night_while_other_types_are_deferred(
    client, category, landing_type
):
    """야간 시계에서 이 유형만 즉시 발송되고 다른 유형은 유예된다(ADR-0010 개정,
    #169)."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"])

    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    developer_user_id = payout.handover.award.submission.contestsubmission.developer.user_id

    _freeze(datetime(2026, 1, 10, 23, 0, tzinfo=KST))
    try:
        _run_scan(client)
    finally:
        ClockOverride.objects.filter(pk=1).delete()

    notification = _payout_awaits_you_notifications(developer_user_id).get()
    assert notification.status == Notification.Status.SENT

    # 같은 야간 시각에 다른 유형을 만들면(내부 엔드포인트) — 그대로 연기된다.
    _freeze(datetime(2026, 1, 10, 23, 0, tzinfo=KST))
    try:
        resp = client.post(
            "/api/internal/notifications",
            data={
                "recipient_id": developer_user_id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_internal_headers(),
        )
    finally:
        ClockOverride.objects.filter(pk=1).delete()
    assert resp.status_code == 200
    assert resp.json()["status"] == Notification.Status.DEFERRED


@pytest.mark.django_db
def test_payout_notification_failure_does_not_touch_payout_status(client, category, landing_type):
    """알림 실패가 Payout 을 건드리지 않는다(ADR-0009) — 발송 채널 전부가
    실패해도 스캔은 정상 종료하고 Payout 상태는 그대로다."""

    sponsor, dev, contest, submission = p._ready_for_payout(client, category, landing_type)
    requested = p._request_payout(client, dev, contest["id"])
    p._confirm_payout(client, dev, requested["idempotency_key"])

    payout_before = Payout.objects.get(idempotency_key=requested["idempotency_key"])

    with override_settings(NOTIFICATION_FAKE_FAILING_CHANNELS=["alimtalk", "sms", "lms"]):
        result = _run_scan(client)

    assert result["failed"] == []
    payout_after = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout_after.status == payout_before.status
    assert payout_after.transfer_status == payout_before.transfer_status

    developer_user_id = payout_before.handover.award.submission.contestsubmission.developer.user_id
    notification = _payout_awaits_you_notifications(developer_user_id).get()
    assert notification.status == Notification.Status.FAILED
    assert notification.dispatches.count() == 3
