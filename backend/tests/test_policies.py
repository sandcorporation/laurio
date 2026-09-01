"""PlatformPolicy — 리드타임·요금·기간 상한 CheckConstraint (#78 코드리뷰 지적 1).

`test_payouts.py`의 `test_platform_policy_rejects_a_fee_bps_above_the_sane_upper_bound`
와 같은 관용구다 — 운영자 API(#76)가 오기 전까지는 이 모델의 CheckConstraint가
말이 안 되는 값을 막는 유일한 방어선이므로, HTTP 시임이 없는 지금은 ORM으로
직접 제약을 친다.

**되돌릴 수 없는 손상 시나리오**: `deadline_reminder_lead_hours`에 상한이
없으면 24 대신 2400으로 오타내는 순간, 다음 스캔에서 모든 PUBLISHED
Contest가 "마감 임박" 알림을 받는다. `deadline_reminder_sent_at`은 Contest당
한 번만 찍히는 플래그라, 값을 24로 되돌려도 그 Contest들의 *진짜* 마감
알림은 영영 나가지 않는다. 이 파일의 상한 테스트들이 없으면 그 사고가
저장 시점이 아니라 몇 주 뒤 "왜 마감 알림이 안 갔지"라는 문의로만 드러난다.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from policies.models import PlatformPolicy


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name, over_the_limit_value",
    [
        ("contest_listing_fee", 10_000_001),
        ("judging_extension_fee", 10_000_001),
        ("judging_period_days", 181),
        ("judging_extension_days", 181),
        ("handover_acceptance_period_days", 181),
        ("distribution_wait_days", 181),
        ("deadline_reminder_lead_hours", 721),
        ("judging_end_reminder_lead_hours", 721),
        ("distribution_final_warning_lead_days", 31),
        ("seller_weekly_limit_amount", 1_000_000_001),
    ],
)
def test_platform_policy_rejects_a_value_above_the_sane_upper_bound(
    db, field_name, over_the_limit_value
):
    """상한 CheckConstraint를 지우면 이 테스트가 빨간불이 된다 — 저장이
    그냥 성공해버리기 때문이다."""

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformPolicy.objects.create(**{field_name: over_the_limit_value})


@pytest.mark.django_db
def test_platform_policy_accepts_values_exactly_at_the_sane_upper_bound(db):
    """경계값 자체(상한과 정확히 같은 값)는 거부되지 않는다 — 전부 `__lte`라
    상한을 포함한다."""

    policy = PlatformPolicy.objects.create(
        pk=1,
        contest_listing_fee=10_000_000,
        judging_extension_fee=10_000_000,
        judging_period_days=180,
        judging_extension_days=180,
        handover_acceptance_period_days=180,
        distribution_wait_days=180,
        deadline_reminder_lead_hours=720,
        judging_end_reminder_lead_hours=720,
        distribution_final_warning_lead_days=30,
        seller_weekly_limit_amount=1_000_000_000,
    )

    assert policy.pk == 1
    assert policy.deadline_reminder_lead_hours == 720
