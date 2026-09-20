"""Distribution 도메인 로직 (#16, ADR-0003, ADR-0004, ADR-0006).

API 레이어(`distributions.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로
여기 함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

두 단계로 나뉜 스캔이다(`payments.services.run_pending_refunds`와 같은 구조):

1. 새로 기한이 된 Contest — JUDGING_ENDED로 옮겨간 지
   PlatformPolicy.distribution_wait_days(#78/ADR-0023)가 지났는데 아직
   Distribution이 없는 Contest를 찾아 Distribution + N개의
   DistributionShare를 만들고, 1/N 나머지를 단수처리 분개로 남긴다. Contest를
   `select_for_update`로 잠그고 Distribution 존재 여부를 그 안에서 확인하므로
   (core.transitions.claim_transition과 같은 정신 — 다만 부수효과가 분개 생성이라
   단순 조건부 UPDATE가 아니라 락 기반이다), 틱을 두 번 쏴도 두 번째는 이미 있는
   Distribution을 보고 그대로 지나간다(#16 AC).
2. 아직 확정되지 않은 몫(DistributionShare) — 새로 만들어졌거나, 이전 시도가
   FAILED로 끝나 재시도 대상이 된 몫에 대해 `payouts` 앱의 기존 경로
   (`get_or_create_payout`/`advance`)를 그대로 재사용해
   지급을 시도한다. 실패한 몫은 REQUESTED가 아니라 FAILED로 남으므로 다음 스캔이
   자동으로 재시도한다 — "일부만 성공하면 성공분만 원장에 반영되고 나머지는
   재시도 대상으로 남는다"(#16 AC)는 이 재시도 루프의 직접적인 결과다.

컷라인 미달자만 배분에서 빠진다 — 하지만 참여자가 있는데 아무도 컷라인을
넘지 못했다면, Prize가 Sponsor에게 돌아가는 일은 없다(Escrow의 핵심 원칙,
REQUEST.md). 그 경우 컷라인을 무시하고 참여자 전원에게 배분한다
(`Distribution.cutline_waived`로 감사 기록을 남긴다).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q
from django.db import transaction

from appeals.models import Appeal
from contests.lifecycle_notifications import notify_distribution_shares
from contests.models import Contest, ContestSubmission
from core.clock import Clock
from core.contest_switch import paid_contest_product_enabled
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from payouts.adapters import PayoutError, get_adapter
from payouts.models import Payout
from payouts.progress import advance
from payouts.services import get_or_create_payout
from policies.models import PlatformPolicy
from policies.scope import current_policy

from core.scans import ScanSpec, scan_params

from .models import Distribution, DistributionShare

logger = logging.getLogger(__name__)



def _create_distribution_for_contest(
    contest_id: int, *, policy: PlatformPolicy
) -> Distribution | None:
    """이 Contest에 대한 Distribution을 멱등하게 만든다.

    참여자가 0명이면 아무 것도 만들지 않고 None을 돌려준다 — 참여자 0명 전액
    환불은 #17의 몫이지, 여기서 대신 처리하지 않는다(0으로 나누는 사고도 이렇게
    구조적으로 피한다).

    `policy`는 스캔 실행의 스코프에서 한 번 읽은 것이다(`policies.scope`, #75, #145,
    #79, ADR-0023) — 여기서 다시 읽지 않는다. 컷라인(`policy.
    distribution_cutline_percentage`)도 `_attempt_share_payout`이 쓰는 수수료·
    원천징수율과 같은 정책 행에서 나오므로, 이 스캔이 시도하는 Contest 수만큼
    정책 조회가 늘어나지 않는다.
    """

    with transaction.atomic():
        locked_contest = Contest.objects.select_for_update().get(pk=contest_id)

        existing = Distribution.objects.filter(contest=locked_contest).first()
        if existing is not None:
            return existing

        if not Contest.Status.AWAITING_DISTRIBUTION(locked_contest.status):
            # 잠근 뒤 다시 읽은 최신 상태로 한 번 더 확인한다 — 이 배치가 만들어질
            # 때와 실제로 잠그는 시점 사이에 Award가 끼어들었을 수 있다.
            return None

        submissions = list(
            ContestSubmission.objects.filter(contest=locked_contest).select_related(
                "score", "developer__user"
            )
        )
        if not submissions:
            return None

        cutline = policy.distribution_cutline_percentage
        qualifying = [s for s in submissions if hasattr(s, "score") and s.score.percentage >= cutline]

        cutline_waived = False
        if not qualifying:
            # 참여자가 있는데 아무도 컷라인을 넘지 못했다 — 그래도 Prize는
            # Sponsor에게 돌아가지 않는다(REQUEST.md "핵심 원칙": 참여자가 한
            # 명이라도 있으면 상금은 발주자에게 돌아가지 않는다). 컷라인을
            # 무시하고 참여자 전원에게 배분한다.
            qualifying = submissions
            cutline_waived = True

        n = len(qualifying)
        total_prize = locked_contest.prize
        share_amount = total_prize // n
        remainder_amount = total_prize - share_amount * n

        distribution = Distribution.objects.create(
            contest=locked_contest,
            cutline_percentage=cutline,
            total_prize=total_prize,
            qualifying_count=n,
            share_amount=share_amount,
            remainder_amount=remainder_amount,
            cutline_waived=cutline_waived,
        )

        DistributionShare.objects.bulk_create(
            DistributionShare(distribution=distribution, submission=s, amount=share_amount)
            for s in qualifying
        )

        if remainder_amount > 0:
            # 1/N 나머지는 특정 Developer의 몫이 아니므로(누구에게도 더 줄 근거가
            # 없다) 플랫폼 수수료 수익으로 명시적으로 이관한다 — 사라지지 않고
            # 단수처리 분개로 남는다(ADR-0004).
            entry = post_journal_entry(
                contest_id=locked_contest.ledger_id,
                memo=(
                    f"Contest #{locked_contest.id} Distribution 1/N 단수처리 — "
                    f"{total_prize:,}원 ÷ {n} = {share_amount:,}원 x {n} + 나머지 "
                    f"{remainder_amount:,}원"
                ),
                lines=[
                    LineInput(
                        account=Account.DEVELOPER_PAYABLE,
                        side=EntrySide.DEBIT,
                        amount=remainder_amount,
                    ),
                    LineInput(
                        account=Account.PLATFORM_FEE_REVENUE,
                        side=EntrySide.CREDIT,
                        amount=remainder_amount,
                    ),
                ],
            )
            Distribution.objects.filter(pk=distribution.pk).update(
                remainder_journal_entry_id=entry.id
            )
            distribution.remainder_journal_entry_id = entry.id

    # 트랜잭션이 커밋된 뒤에만 알린다 — notify_distribution_shares는 내부에서 모든
    # 예외를 삼키므로(#19 AC, ADR-0009: "전 채널이 미도달이어도 Distribution이
    # 예정대로 실행된다") 알림 생성 실패가 위 원장·배분 트랜잭션을 되돌리거나
    # 이 함수의 반환을 막는 일은 없다.
    notify_distribution_shares(distribution, qualifying)

    return distribution


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

    payout = get_or_create_payout(share.payout_target())

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


def distribution_due_q(as_of, policy) -> Q:
    """「배분 시각이 왔다」는 조건 그 자체 — **이의 보류를 적용하기 전의** 것이다.

    조건을 `Q` 로 내주는 이유는 소비처가 셋이고 모양이 다르기 때문이다: 스캔은
    이것으로 후보를 뽑고(그 뒤 이의 보류를 뺀다), 이의 쪽은 「이 이의가 배분을
    막고 있다」를 이 조건에 **들어 있는가**로 판정하고(#74), 개최자 목록은 행마다
    `Case/When` 으로 붙여 조회 없이 같은 것을 안다(#81).

    조건을 세 벌로 쓰면 언젠가 갈라지고, 그러면 개최자 화면은 보류라는데 이의
    큐는 아니라고 하는 날이 온다.

    **`is_free=False`도 조건이다(#417, ADR-0048).** 무료 공모전은 상금·Escrow가
    없으므로 「무응답 N일」이 지나도 배분할 돈 자체가 없다 — 심사 기간 안에
    수상하지 않으면 그대로 수상 없이 끝난 상태로 남는다(더 옮겨 갈 다음 단계가
    없다). 이 조건이 없으면 무료 공모전도 스캔 후보에 올라 `Distribution`(과
    그 이하 `Payout`)을 만들려 시도하게 된다.
    """

    return Q(
        status__in=Contest.Status.AWAITING_DISTRIBUTION.statuses,
        judging_ends_at__lte=as_of - timedelta(days=policy.distribution_wait_days),
        distribution__isnull=True,
        is_free=False,
    )


def distribution_due_contests(as_of, policy):
    """`distribution_due_q` 를 적용한 Contest 질의."""

    return Contest.objects.filter(distribution_due_q(as_of, policy))


def is_holding_distribution(appeal) -> bool:
    """이 이의가 지금 어떤 Contest 의 배분을 막고 있는가 (#74 스토리 24·37·38).

    한 사람의 이의가 그 Contest 의 배분 전체를 멈춘다 — 다른 참가자들의 돈도 함께
    미뤄진다. 그 대가를 치르기로 했으면 막고 있다는 사실이 양쪽 화면에 보여야
    한다: 운영자에게는 「이 심판이 돈을 막고 있다」는 우선순위 신호이고,
    제출자에게는 「내 이의 때문에 아직 안 움직인다 — 사라진 게 아니다」라는
    설명이다(ADR-0020 의 "침묵은 상금이 사라진 것으로 읽힌다").

    심판이 끝나면 저절로 False 가 된다 — 「막고 있다」가 영구 라벨이 되지 않는다.
    """

    if appeal.status != Appeal.Status.PENDING:
        return False

    return distribution_due_contests(Clock.now(), current_policy()).filter(
        id=appeal.submission.contestsubmission.contest_id
    ).exists()


# --- 배분 스캔 둘 (#16, #140, ADR-0003) --------------------------------------------------
#
# `distribution-create` 는 무응답 기간이 지난 Contest 에 Distribution 을 만들고,
# `distribution-share-payout` 은 아직 확정되지 않은 몫의 지급을 시도(또는 재시도)한다. 같은
# 시각에 두 번 돌아도 이미 만들어진 Distribution 은 다시 만들지 않고, 이미 확정된 몫은 다시
# 지급 시도하지 않는다(#16 AC). 행별 예외 격리는 뼈대(core.scans)의 것이다 — FAILED 로 끝난
# 몫은 계속 재시도 후보로 남으므로(의도된 동작), 그 재시도 경로가 order_by("id") 의 맨 앞을
# 영구히 차지한 채 예외로 죽으면 뒤의 배치가 통째로 막히는 poison pill 을 뼈대가 막는다.
def _due_contests(as_of, ctx):
    return (
        distribution_due_contests(as_of, current_policy())
        # **심판되지 않은 이의가 있으면 그 Contest 는 아직 배분하지 않는다**(#74).
        #
        # 이의가 묻는 것이 정확히 "내 점수가 컷라인을 넘는가" 이고, 점수가 돈을 정하는 유일한
        # 곳이 이 컷라인이다(`Score` 는 Award 를 결정하지 않는다 — ADR-0006/0014). 답이 안 나온
        # 채 배분하면 이의 제도가 무의미해진다.
        #
        # 후보 질의에서 걸러낸다 — 행 처리에서 건너뛰면 그 Contest 가 매 실행 배치의 맨 앞을
        # 차지해(order_by("id")) 뒤의 정상 건들을 밀어낸다.
        #
        # **보류는 실패가 아니다.** 심판이 끝나는 순간 이 조건이 저절로 풀려 다음 실행이 집는다
        # — 상태를 따로 두지 않는 이유다. 다만 운영자가 심판하지 않으면 무기한이므로, 운영자
        # 큐가 "이 이의가 배분을 막고 있다" 를 보여줘야 한다(#74 스펙, ADR-0020 의 "돈이
        # 사라지는 경로를 만들지 않는다").
        .exclude(submissions__appeal__status=Appeal.Status.PENDING)
    )


def _create_distribution(contest, as_of, ctx):
    distribution = _create_distribution_for_contest(contest.id, policy=current_policy())
    if distribution is None:
        return None
    return {
        "event": "distribution_created",
        "contest_id": contest.id,
        "distribution_id": distribution.id,
        "qualifying_count": distribution.qualifying_count,
        "share_amount": distribution.share_amount,
        "remainder_amount": distribution.remainder_amount,
        "cutline_waived": distribution.cutline_waived,
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


# 배치 50은 뼈대 기본값 그대로다 — 무제한 스캔은 백로그가 쌓였을 때 이 요청 자체를 타임아웃으로
# 몰아넣는다.
#
# `enabled=paid_contest_product_enabled`(#413) — Distribution 은 상금이 있는
# 유료 공모전 전용이다(무응답 1/N 배분). 유료 공모전 스위치가 꺼지면 이 둘은
# 등록부에서 사라진 것처럼 군다.
DISTRIBUTION_SCANS = (
    ScanSpec(
        name="distribution-create",
        candidates=_due_contests,
        handle_row=_create_distribution,
        enabled=paid_contest_product_enabled,
    ),
    ScanSpec(
        name="distribution-share-payout",
        candidates=_pending_shares,
        handle_row=_attempt_payout,
        enabled=paid_contest_product_enabled,
    ),
)
