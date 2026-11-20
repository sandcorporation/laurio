"""배분 몫(DistributionShare) 지급 스캔 `distribution-share-payout` (#16, #140) — `distributions.services` 에서 옮겼다(#1086).

`Payout` 이 몫을 FK 로 가리키므로 payouts 가 distributions 위에 선다. 몫 지급이 distributions 에 있으면
distributions 가 다시 payouts 를 불러 두 앱이 한 순환이 된다. 스캔 이름·동작은 그대로 —
`payouts.apps` 가 등록한다(배분 생성 `distribution-create` 다음에 오도록 INSTALLED_APPS 에서 distributions 가 앞이다).
"""

from __future__ import annotations

from core.contest_switch import paid_contest_product_enabled
from core.scans import ScanSpec, scan_params
from distributions.models import DistributionShare

from .adapters import PayoutError, get_adapter
from .models import Payout
from .progress import advance
from .services import get_or_create_payout
from .targets import PayoutTarget


def share_payout_target(share: DistributionShare) -> PayoutTarget:
    """이 몫을 지급 사유로 하는 Payout 생성에 필요한 것 (#129) — `DistributionShare.payout_target` 에서 옮겼다(#1086)."""

    return PayoutTarget(
        fk_name="distribution_share",
        lock=lambda: DistributionShare.objects.select_for_update().get(pk=share.pk),
        prize_amount_of=lambda locked: locked.amount,
    )


def _attempt_share_payout(
    share: DistributionShare, *, force_failure: bool
) -> dict:
    """이 몫에 대한 지급을 시도(신규 요청 또는 재시도)한다.

    `payouts.services.get_or_create_payout`가 이미 활성 Payout이 있으면 그대로
    돌려주므로, 여기서 새 요청이 중복으로 나가지 않는다. `force_failure`는 fake
    어댑터 전용 테스트 시나리오 선택이다(`payments.api.ConfirmPaymentIn.simulate`와
    같은 원칙) — 실제 어댑터에서는 의미가 없다.

    `policy`는 스캔 실행의 스코프에서 한 번 읽은 것이다(`policies.scope`, #75, #145,
    ADR-0023) — 여기서 다시 읽지 않는다. 그러지 않으면 이 스캔이 시도하는 몫
    수만큼 정책 조회가 나간다.
    """

    payout = get_or_create_payout(share_payout_target(share))

    if payout.status != Payout.Status.REQUESTED:
        # 이미 다른 경로(웹훅 등)로 확정·실패되어 있다 — 그대로 지나간다.
        return {
            "submission_id": share.submission_id,
            "idempotency_key": str(payout.idempotency_key),
            "status": payout.status,
        }

    # 벤더 확인·실이체·Seller 등록·원장 분개 전부 advance 가 한다(#133, #135) — Award 경로의
    # 확정 엔드포인트와 같은 함수다. `force_failure`는 fake 어댑터 전용 시나리오 선택이다. 벤더의
    # 명시적 거절(PayoutError)은 이 몫의 이번 시도를 실패로 끝낸다 — 다음 스캔이 새 요청으로 재시도.
    try:
        payout = advance(
            payout,
            register_seller=True,
            adapter=get_adapter(),
            confirm_with_vendor=True,
            simulate="failed" if force_failure else None,
        )
    except PayoutError:
        payout = advance(payout, register_seller=False, confirmed_by_vendor=False)

    return {
        "submission_id": share.submission_id,
        "idempotency_key": str(payout.idempotency_key),
        "status": payout.status,
    }


def _pending_shares(as_of, ctx):
    return (
        DistributionShare.objects.exclude(payouts__status__in=Payout.Status.SETTLED.statuses)
        .select_related("distribution", "submission")
        .distinct()
    )


def _attempt_payout(share, as_of, ctx):
    # `fail_submission_ids`(scan_params)는 fake 지급대행 어댑터 전용 테스트 시나리오 선택이다 —
    # 여기 나열된 submission_id 의 지급 시도만 강제로 실패시킨다. 실제 어댑터에서는 의미가 없다.
    fail_submission_ids = set(scan_params(ctx).get("fail_submission_ids", []))
    outcome = _attempt_share_payout(
        share, force_failure=share.submission_id in fail_submission_ids
    )
    outcome["event"] = "payout_attempted"
    return outcome


# 배치 50은 뼈대 기본값 그대로다. `enabled=paid_contest_product_enabled`(#413) — 배분은 유료 공모전 전용이다.
DISTRIBUTION_PAYOUT_SCANS = (
    ScanSpec(
        name="distribution-share-payout",
        candidates=_pending_shares,
        handle_row=_attempt_payout,
        enabled=paid_contest_product_enabled,
    ),
)
