"""결제 확정 도메인 로직.

API 레이어(`payments.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기
함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

핵심 규율(ADR-0003과 같은 조건부 UPDATE): `Payment.status`를
`UPDATE ... WHERE order_id=? AND status='requested'`로만 `paid`/`failed`로
전이시키고, rowcount가 1일 때만 원장에 분개를 남기고 Contest를 공개한다. 이 하나의
규율이 세 가지 장애 흐름을 전부 막는다:

- 같은 웹훅이 두 번 온다 — 두 번째 UPDATE는 rowcount 0이라 아무 것도 하지 않는다.
- 웹훅이 동기 confirm보다 먼저 도착한다 — 먼저 도착한 쪽이 rowcount 1을 가져가고,
  나중 것은 이미 바뀐 상태를 보고 조용히 넘어간다. 어느 쪽이 이기든 결과는 같다.
- confirm 호출이 타임아웃됐지만 실제로는 성공했다 — 타임아웃을 실패로 오인해 바로
  `failed`로 적으면 안 되므로, 호출자는 `query_status`로 진짜 결과를 확인한 뒤에만
  이 함수들을 부른다.
"""

from __future__ import annotations

from django.db import transaction

from contests.models import Contest
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry

from .models import Payment


def mark_paid(order_id) -> Payment:
    """결제를 완료로 확정한다. 이미 확정되어 있으면 아무 것도 다시 하지 않는다.

    이겼을 때만(rowcount==1) 원장에 예치 분개를 남기고 Contest를 공개한다. 예치
    분개는 결제 총액(Prize + 개최 등록비)이 발주자 예치금에서 빠져나와, Prize는
    개발자 미지급금(Escrow — 이후 Payout·Distribution·환불로만 빠져나간다)으로,
    등록비는 플랫폼 수수료 수익으로 즉시 인식되는 것으로 기록한다.
    """

    with transaction.atomic():
        updated = Payment.objects.filter(order_id=order_id, status=Payment.Status.REQUESTED).update(
            status=Payment.Status.PAID
        )
        payment = Payment.objects.select_related("contest").get(order_id=order_id)

        if updated != 1:
            # 이미 paid거나 failed다 — 다른 채널(웹훅/동기 confirm)이 먼저 이겼거나
            # 재전송이다. 원장에는 이미 반영되어 있으므로 다시 손대지 않는다.
            return payment

        entry = post_journal_entry(
            contest_id=payment.contest.ledger_id,
            memo=(
                f"Contest #{payment.contest_id} 결제 예치 — "
                f"상금 {payment.prize_amount:,}원 + 개최 등록비 {payment.listing_fee_amount:,}원"
            ),
            lines=[
                LineInput(
                    account=Account.SPONSOR_DEPOSIT,
                    side=EntrySide.DEBIT,
                    amount=payment.total_amount,
                ),
                LineInput(
                    account=Account.DEVELOPER_PAYABLE,
                    side=EntrySide.CREDIT,
                    amount=payment.prize_amount,
                ),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.CREDIT,
                    amount=payment.listing_fee_amount,
                ),
            ],
        )

        Payment.objects.filter(pk=payment.pk).update(journal_entry_id=entry.id)
        payment.journal_entry_id = entry.id

        # Contest 공개도 같은 조건부 UPDATE 규율을 따른다 — draft일 때만 published로
        # 간다. 이 결제가 이미 그 전이를 성공시켰으므로(위 rowcount==1) 정상 경로에서는
        # 항상 draft여야 하지만, 방어적으로 조건을 남겨 이중 공개를 구조적으로 막는다.
        Contest.objects.filter(pk=payment.contest_id, status=Contest.Status.DRAFT).update(
            status=Contest.Status.PUBLISHED
        )

    return payment


def mark_failed(order_id) -> Payment:
    """결제를 실패로 확정한다. 이미 확정되어 있으면 아무 것도 다시 하지 않는다.

    실패 경로는 원장에 아무 흔적도 남기지 않는다 — 돈이 움직이지 않았다.
    """

    Payment.objects.filter(order_id=order_id, status=Payment.Status.REQUESTED).update(
        status=Payment.Status.FAILED
    )
    return Payment.objects.get(order_id=order_id)
