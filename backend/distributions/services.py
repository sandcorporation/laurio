"""Distribution 도메인 로직 (#16, ADR-0003, ADR-0004, ADR-0006).

API 레이어(`distributions.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로
여기 함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

두 단계로 나뉜 스캔이다(`payments.services.run_pending_refunds`와 같은 구조):

1. 새로 기한이 된 Contest — JUDGING_ENDED로 옮겨간 지 DISTRIBUTION_WAIT_DAYS가
   지났는데 아직 Distribution이 없는 Contest를 찾아 Distribution + N개의
   DistributionShare를 만들고, 1/N 나머지를 단수처리 분개로 남긴다. Contest를
   `select_for_update`로 잠그고 Distribution 존재 여부를 그 안에서 확인하므로
   (core.transitions.claim_transition과 같은 정신 — 다만 부수효과가 분개 생성이라
   단순 조건부 UPDATE가 아니라 락 기반이다), 틱을 두 번 쏴도 두 번째는 이미 있는
   Distribution을 보고 그대로 지나간다(#16 AC).
2. 아직 확정되지 않은 몫(DistributionShare) — 새로 만들어졌거나, 이전 시도가
   FAILED로 끝나 재시도 대상이 된 몫에 대해 `payouts` 앱의 기존 경로
   (`get_or_create_payout`/`mark_confirmed`/`mark_failed`)를 그대로 재사용해
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

from django.conf import settings
from django.db import transaction

from contests.models import Contest
from core.clock import Clock
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from notifications.lifecycle import notify_distribution_shares
from payouts.adapters import PayoutError, PayoutTimeoutError, get_adapter
from payouts.models import Payout
from payouts.services import get_or_create_payout, mark_confirmed, mark_failed
from policies.models import PlatformPolicy
from policies.services import get_current_policy
from submissions.models import Submission

from .models import Distribution, DistributionCutline, DistributionShare

logger = logging.getLogger(__name__)

# 한 스캔에서 시도하는 최대 행 수 — handovers.api.BATCH_SIZE와 같은 이유. 무제한
# 스캔은 백로그가 쌓였을 때 이 요청 자체를 타임아웃으로 몰아넣는다.
BATCH_SIZE = 50

# unique_active_payout_per_distribution_share와 같은 집합이어야 한다
# (payouts.services._ACTIVE_PAYOUT_STATUSES와 같은 이유) — 이 상태들에 도달한
# 몫은 이미 확정됐으므로 다시 시도하지 않는다.
_SETTLED_PAYOUT_STATUSES = [Payout.Status.CONFIRMED_IDENTITY_PENDING, Payout.Status.CONFIRMED]


def get_cutline_percentage():
    """DB 조정 가능한 컷라인 값을 읽는다. 행이 없으면 기본값으로 만든다."""

    cutline, _ = DistributionCutline.objects.get_or_create(pk=1)
    return cutline.minimum_percentage


def _create_distribution_for_contest(contest_id: int) -> Distribution | None:
    """이 Contest에 대한 Distribution을 멱등하게 만든다.

    참여자가 0명이면 아무 것도 만들지 않고 None을 돌려준다 — 참여자 0명 전액
    환불은 #17의 몫이지, 여기서 대신 처리하지 않는다(0으로 나누는 사고도 이렇게
    구조적으로 피한다).
    """

    with transaction.atomic():
        locked_contest = Contest.objects.select_for_update().get(pk=contest_id)

        existing = Distribution.objects.filter(contest=locked_contest).first()
        if existing is not None:
            return existing

        if locked_contest.status != Contest.Status.JUDGING_ENDED:
            # 잠근 뒤 다시 읽은 최신 상태로 한 번 더 확인한다 — 이 배치가 만들어질
            # 때와 실제로 잠그는 시점 사이에 Award가 끼어들었을 수 있다.
            return None

        submissions = list(
            Submission.objects.filter(contest=locked_contest).select_related(
                "score", "developer__user"
            )
        )
        if not submissions:
            return None

        cutline = get_cutline_percentage()
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
    share: DistributionShare, *, policy: PlatformPolicy, force_failure: bool
) -> dict:
    """이 몫에 대한 지급을 시도(신규 요청 또는 재시도)한다.

    `payouts.services.get_or_create_payout`가 이미 활성 Payout이 있으면 그대로
    돌려주므로, 여기서 새 요청이 중복으로 나가지 않는다. `force_failure`는 fake
    어댑터 전용 테스트 시나리오 선택이다(`payments.api.ConfirmPaymentIn.simulate`와
    같은 원칙) — 실제 어댑터에서는 의미가 없다.

    `policy`는 `run_due_distributions`가 스캔 스코프당 한 번 읽어 넘긴다(#75,
    ADR-0023) — 여기서 다시 읽지 않는다. 그러지 않으면 이 스캔이 시도하는 몫
    수만큼 정책 조회가 나간다.
    """

    payout = get_or_create_payout(distribution_share=share, policy=policy)

    if payout.status != Payout.Status.REQUESTED:
        # 이미 다른 경로(웹훅 등)로 확정·실패되어 있다 — 그대로 지나간다.
        return {
            "submission_id": share.submission_id,
            "idempotency_key": str(payout.idempotency_key),
            "status": payout.status,
        }

    adapter = get_adapter()
    adapter.request_payout(idempotency_key=str(payout.idempotency_key), amount=payout.net_amount)

    simulate = "failed" if force_failure else None
    try:
        result_status = adapter.confirm(idempotency_key=str(payout.idempotency_key), simulate=simulate)
    except PayoutTimeoutError:
        # 타임아웃은 실패가 아니다 — 실제 결과를 조회로 확정한다(ADR-0008).
        result_status = adapter.query_status(idempotency_key=str(payout.idempotency_key))
    except PayoutError:
        result_status = "failed"

    if result_status == "paid":
        payout = mark_confirmed(payout.idempotency_key)
    elif result_status == "failed":
        payout = mark_failed(payout.idempotency_key)
    else:
        # 아직 확정할 수 없다(pending) — REQUESTED로 남겨 웹훅이나 다음 스캔이
        # 마저 확정하게 한다.
        payout.refresh_from_db()

    return {
        "submission_id": share.submission_id,
        "idempotency_key": str(payout.idempotency_key),
        "status": payout.status,
    }


def run_due_distributions(*, fail_submission_ids: set[int] | None = None) -> list[dict]:
    """무응답 14일이 지난 Contest를 스캔해 Distribution을 만들고, 아직 확정되지
    않은 몫에 대한 지급을 시도(또는 재시도)한다.
    """

    as_of = Clock.now()
    # 이 스캔 스코프에서 정책을 한 번만 읽는다(#75, ADR-0023) — as_of를 스캔
    # 시작 시점에 한 번만 구해 재사용하는 것과 같은 이유. 아래 for share in
    # pending_shares 루프가 몫마다 정책을 다시 읽으면 쿼리가 몫 수만큼 늘어난다.
    policy = get_current_policy()
    fail_submission_ids = fail_submission_ids or set()
    results: list[dict] = []

    cutoff = as_of - timedelta(days=settings.DISTRIBUTION_WAIT_DAYS)
    due_contest_ids = list(
        Contest.objects.filter(
            status=Contest.Status.JUDGING_ENDED,
            judging_ends_at__lte=cutoff,
            distribution__isnull=True,
        )
        .order_by("id")
        .values_list("id", flat=True)[:BATCH_SIZE]
    )

    for contest_id in due_contest_ids:
        # 한 Contest의 처리가 여기서 예외를 던져도(예기치 못한 버그) 나머지
        # 배치가 막히면 안 된다 — order_by("id")로 스캔하는 이상, 그 예외를
        # 밖으로 흘리면 이 Contest가 항상 배치 맨 앞에서 다시 걸려 그 뒤의
        # 정상 건들까지 영원히 처리되지 못하는 poison pill이 된다
        # (scoring.services.run_pending_scoring이 이미 겪고 고친 것과 같은
        # 종류의 사고 — #21 리뷰).
        try:
            distribution = _create_distribution_for_contest(contest_id)
        except Exception as exc:  # noqa: BLE001 - 한 Contest의 실패가 배치를 막으면 안 된다.
            logger.exception(
                "Contest(pk=%s) Distribution 생성 중 예외, 다음 건으로 계속", contest_id
            )
            results.append(
                {
                    "event": "distribution_creation_failed",
                    "contest_id": contest_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        if distribution is not None:
            results.append(
                {
                    "event": "distribution_created",
                    "contest_id": contest_id,
                    "distribution_id": distribution.id,
                    "qualifying_count": distribution.qualifying_count,
                    "share_amount": distribution.share_amount,
                    "remainder_amount": distribution.remainder_amount,
                    "cutline_waived": distribution.cutline_waived,
                }
            )

    pending_shares = (
        DistributionShare.objects.exclude(payouts__status__in=_SETTLED_PAYOUT_STATUSES)
        .select_related("distribution", "submission")
        .order_by("id")
        .distinct()[:BATCH_SIZE]
    )

    for share in pending_shares:
        # 같은 이유로 몫 하나의 지급 시도가 던지는 예외도 밖으로 흘리지 않는다 —
        # FAILED로 끝난 몫은 계속 재시도 후보로 남으므로(의도된 동작, "실패한
        # 지급만 다음 스캔이 자동으로 재시도한다"), 그 재시도 경로 자체가
        # order_by("id")의 맨 앞을 영구히 차지한 채 예외로 죽으면 그 뒤의 배치가
        # 통째로 막힌다.
        try:
            outcome = _attempt_share_payout(
                share, policy=policy, force_failure=share.submission_id in fail_submission_ids
            )
        except Exception as exc:  # noqa: BLE001 - 한 몫의 실패가 배치를 막으면 안 된다.
            logger.exception(
                "DistributionShare(pk=%s) 지급 시도 중 예외, 다음 건으로 계속", share.id
            )
            results.append(
                {
                    "event": "payout_attempt_failed",
                    "submission_id": share.submission_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        outcome["event"] = "payout_attempted"
        results.append(outcome)

    return results
