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
from submissions.models import Submission

from .adapters import PGError, PGTimeoutError, get_adapter
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


# --- 참여자 0명 전액 환불 (#17, ADR-0004) ------------------------------------
#
# mark_paid/mark_failed와 같은 조건부 UPDATE 규율을 그대로 반복한다:
#
# 1) request_refund가 PAID -> REFUND_REQUESTED로 조건부 전이시켜 "이 스캔이 이
#    Payment의 환불을 시작할 권리를 가져갔다"를 표시한다. 두 스캔이 동시에 같은
#    Payment를 집어도 하나만 rowcount==1을 가져간다.
# 2) PG 어댑터의 확정 결과(성공/실패/타임아웃 후 조회)에 따라 mark_refunded 또는
#    mark_refund_failed를 부른다. 어느 쪽도 REFUND_REQUESTED가 아닌 상태에서는
#    조건부 UPDATE의 rowcount가 0이라 아무 일도 하지 않는다 — 같은 웹훅이 두 번
#    오거나, 스캔이 이미 동기적으로 확정한 뒤에 뒤늦게 웹훅이 다시 와도 원장에는
#    정확히 한 번만 반대 분개가 남는다.


def request_refund(order_id) -> Payment | None:
    """PAID 결제를 refund_requested로 조건부 전이시킨다.

    다른 스캔이 이미 선점했거나(REFUND_REQUESTED/REFUNDED),애초에 PAID가 아니면
    None을 돌려준다 — 호출자는 그 Payment를 건드리지 않고 넘어가야 한다.
    """

    updated = Payment.objects.filter(order_id=order_id, status=Payment.Status.PAID).update(
        status=Payment.Status.REFUND_REQUESTED
    )
    if updated != 1:
        return None
    return Payment.objects.select_related("contest").get(order_id=order_id)


def mark_refunded(order_id) -> Payment:
    """환불을 완료로 확정한다. REFUND_REQUESTED 상태에서만 전이하며, 이겼을 때만
    (rowcount==1) 원장에 반대 분개를 남긴다.

    반대 분개는 mark_paid가 남긴 예치 분개의 각 라인 차/대변을 그대로 뒤집는다 —
    발주자 예치금은 다시 대변(환불), 개발자 미지급금(Prize)과 플랫폼 수수료 수익
    (개최 등록비)은 차변으로 취소된다. 세 라인 모두 원본과 금액이 같으므로 이
    Contest의 원장 순합계는 정확히 0으로 돌아온다.
    """

    with transaction.atomic():
        updated = Payment.objects.filter(
            order_id=order_id, status=Payment.Status.REFUND_REQUESTED
        ).update(status=Payment.Status.REFUNDED)
        payment = Payment.objects.select_related("contest").get(order_id=order_id)

        if updated != 1:
            # 이미 refunded다 — 같은 웹훅 재전송이거나, 스캔이 동기적으로 이미
            # 확정한 뒤에 뒤늦게 도착한 웹훅이다. 원장에는 이미 반영되어 있으므로
            # 다시 손대지 않는다.
            return payment

        entry = post_journal_entry(
            contest_id=payment.contest.ledger_id,
            reverses_id=payment.journal_entry_id,
            memo=(
                f"Contest #{payment.contest_id} 환불 — 참여자 0명 전액 환불 "
                f"(상금 {payment.prize_amount:,}원 + 개최 등록비 {payment.listing_fee_amount:,}원)"
            ),
            lines=[
                LineInput(
                    account=Account.DEVELOPER_PAYABLE,
                    side=EntrySide.DEBIT,
                    amount=payment.prize_amount,
                ),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.DEBIT,
                    amount=payment.listing_fee_amount,
                ),
                LineInput(
                    account=Account.SPONSOR_DEPOSIT,
                    side=EntrySide.CREDIT,
                    amount=payment.total_amount,
                ),
            ],
        )

        Payment.objects.filter(pk=payment.pk).update(refund_journal_entry_id=entry.id)
        payment.refund_journal_entry_id = entry.id

    return payment


def mark_refund_failed(order_id) -> Payment:
    """환불 실패 시 PAID로 되돌려 다음 스캔이 재시도할 수 있게 한다.

    실패 경로는 원장에 아무 흔적도 남기지 않는다 — 돈이 아직 움직이지 않았다.
    """

    Payment.objects.filter(order_id=order_id, status=Payment.Status.REFUND_REQUESTED).update(
        status=Payment.Status.PAID
    )
    return Payment.objects.get(order_id=order_id)


def run_pending_refunds(*, simulate: str | None = None) -> list[dict]:
    """CLOSED Contest 중 Submission이 0건인 채 결제가 완료된 것을 찾아 전액 환불한다.

    Submission이 하나라도 있으면 이 스캔은 그 Contest의 Payment를 절대 건드리지
    않는다 — 참여자 0명 전액 환불은 ADR-0004가 허용하는 유일한 환불 경로다(#17).

    `simulate`는 이 스캔이 집는 모든 후보에게 그대로 전달되는 fake PG 전용
    시나리오 선택 값이다(`payments.api.ConfirmPaymentIn.simulate`와 같은 원칙 —
    실제 어댑터는 무시한다). 운영에서는 이 스캔이 Celery beat로 짧은 주기마다
    반복 호출되어 core의 마감 전이(#11) 직후 사실상 "마감 직후"로 수렴한다
    (scoring.services.run_pending_scoring과 같은 구조).
    """

    contests_with_submissions = Submission.objects.values_list("contest_id", flat=True)

    candidates = list(
        Payment.objects.filter(
            status=Payment.Status.PAID,
            contest__status=Contest.Status.CLOSED,
        )
        .exclude(contest_id__in=contests_with_submissions)
        .select_related("contest")
        .order_by("id")
    )

    adapter = get_adapter()
    results: list[dict] = []

    for candidate in candidates:
        claimed = request_refund(candidate.order_id)
        if claimed is None:
            # 다른 스캔이 이미 이 Payment의 환불을 선점했다 — 건드리지 않는다.
            continue

        try:
            status = adapter.refund(
                order_id=str(claimed.order_id), amount=claimed.total_amount, simulate=simulate
            )
        except PGTimeoutError:
            # 타임아웃은 실패가 아니다 — 실제 결과를 조회로 확정한다
            # (payments.api.confirm_payment와 같은 규율).
            status = adapter.query_refund_status(order_id=str(claimed.order_id))
        except PGError as exc:
            mark_refund_failed(claimed.order_id)
            results.append(
                {
                    "payment_id": claimed.id,
                    "contest_id": claimed.contest_id,
                    "status": "error",
                    "error": str(exc),
                }
            )
            continue

        if status == "refunded":
            mark_refunded(claimed.order_id)
            results.append(
                {"payment_id": claimed.id, "contest_id": claimed.contest_id, "status": "refunded"}
            )
        elif status == "failed":
            mark_refund_failed(claimed.order_id)
            results.append(
                {"payment_id": claimed.id, "contest_id": claimed.contest_id, "status": "failed"}
            )
        else:
            # pending — 아직 확정할 수 없다. REFUND_REQUESTED로 남겨두고 이후 웹훅이나
            # 재스캔이 마저 확정한다.
            results.append(
                {"payment_id": claimed.id, "contest_id": claimed.contest_id, "status": "pending"}
            )

    return results
