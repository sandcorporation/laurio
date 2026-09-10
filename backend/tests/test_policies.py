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


# --- 자리만 만든다 (#263, ADR-0035) — 값 자체는 아직 아무 동작도 바꾸지
#     않지만, 저장 시점의 방어선(CheckConstraint)은 다른 정책값과 같은 규율을
#     받는다. ------------------------------------------------------------------


@pytest.mark.django_db
def test_platform_policy_has_reasonable_defaults_for_the_new_prefactor_fields(db):
    """기본값이 합리적이다 — 영상은 소스보다 크고, 스크린샷 개수는 다른 자료
    개수 상한과 어울린다(#263 AC)."""

    policy = PlatformPolicy.objects.create()

    assert policy.max_demo_video_asset_bytes > policy.max_source_asset_bytes
    assert 1 <= policy.max_screenshot_assets <= 50
    assert policy.demo_video_retention_grace_days >= 0
    assert policy.max_build_asset_bytes > 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name, bad_value",
    [
        ("max_source_asset_bytes", 0),
        ("max_source_asset_bytes", 2_000_000_001),
        ("max_demo_video_asset_bytes", 0),
        ("max_demo_video_asset_bytes", 5_000_000_001),
        ("max_screenshot_asset_bytes", 0),
        ("max_screenshot_asset_bytes", 100_000_001),
        ("max_build_asset_bytes", 0),
        ("max_build_asset_bytes", 1_000_000_001),
        ("demo_video_retention_grace_days", 181),
        ("max_screenshot_assets", 0),
        ("max_screenshot_assets", 51),
    ],
)
def test_platform_policy_rejects_out_of_range_prefactor_fields(db, field_name, bad_value):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformPolicy.objects.create(**{field_name: bad_value})


@pytest.mark.django_db
def test_platform_policy_accepts_prefactor_fields_exactly_at_their_bounds(db):
    policy = PlatformPolicy.objects.create(
        pk=1,
        max_source_asset_bytes=2_000_000_000,
        max_demo_video_asset_bytes=5_000_000_000,
        max_screenshot_asset_bytes=100_000_000,
        max_build_asset_bytes=1_000_000_000,
        demo_video_retention_grace_days=0,
        max_screenshot_assets=50,
    )

    assert policy.demo_video_retention_grace_days == 0
    assert policy.max_screenshot_assets == 50


@pytest.mark.django_db
def test_screenshot_byte_cap_default_matches_contest_image_cap(db):
    """`max_screenshot_asset_bytes`의 기본값은 `MAX_CONTEST_IMAGE_BYTES`를 리터럴로
    복사한 것이다(순환 임포트를 피하려고 — `contests.images`가 이미
    `policies.scope`를 가져다 쓴다). 이 테스트가 그 둘이 갈라지지 않게 지킨다 —
    지우면 `contests.images.MAX_CONTEST_IMAGE_BYTES`가 바뀌어도 아무도 모른다."""

    from contests.images import MAX_CONTEST_IMAGE_BYTES

    policy = PlatformPolicy.objects.create()

    assert policy.max_screenshot_asset_bytes == MAX_CONTEST_IMAGE_BYTES
