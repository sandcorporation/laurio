"""심사기간 유료 연장 결제 확정 도메인 로직 (#13, ADR-0003/0004/0007/0008).

API 레이어(`contests.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기
함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

`payments.services.mark_paid`/`mark_failed`와 똑같은 규율(ADR-0003과 같은 조건부
UPDATE): `JudgingExtensionPayment.status`를
`UPDATE ... WHERE order_id=? AND status='requested'`로만 `paid`/`failed`로
전이시키고, rowcount가 1일 때만 원장에 분개를 남기고 실제로 심사기간을 늘린다. 이
하나의 규율이 payments 앱과 같은 장애 흐름들을 막는다 — 같은 confirm이 두 번
온다, confirm 호출이 타임아웃됐지만 실제로는 성공했다(호출자가 `query_status`로
확인한 뒤에만 이 함수들을 부른다).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction

from core.clock import Clock
from core.transitions import claim_transition
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from policies.services import get_current_policy

from .models import Contest, JudgingExtensionPayment


def mark_extension_paid(order_id) -> JudgingExtensionPayment:
    """연장 결제를 완료로 확정한다. 이미 확정되어 있으면 아무 것도 다시 하지 않는다.

    이겼을 때만(rowcount==1) 원장에 분개를 남기고 심사기간을 늘린다. 원장 반영과
    심사기간 연장은 순수 DB 쓰기만 하는 하나의 트랜잭션 안에서 함께 일어난다 — 이
    시점에는 이미 PG 호출 결과(paid)가 확정되어 있으므로, 트랜잭션이 외부 네트워크
    호출을 걸치지 않는다(#13 리뷰 지적: 외부 호출은 이 함수를 부르기 *전에* 이미
    끝나 있어야 한다).
    """

    with transaction.atomic():
        updated = JudgingExtensionPayment.objects.filter(
            order_id=order_id, status=JudgingExtensionPayment.Status.REQUESTED
        ).update(status=JudgingExtensionPayment.Status.PAID)
        payment = JudgingExtensionPayment.objects.select_related("contest").get(order_id=order_id)

        if updated != 1:
            # 이미 paid거나 failed다 — 다른 채널(재시도 confirm 등)이 먼저
            # 이겼거나 재전송이다. 원장·심사기간에는 이미 반영되어 있으므로 다시
            # 손대지 않는다.
            return payment

        entry = post_journal_entry(
            contest_id=payment.contest.ledger_id,
            memo=(
                f"Contest #{payment.contest_id} 심사기간 연장 {payment.extension_number}회차 — "
                f"{payment.amount:,}원"
            ),
            lines=[
                LineInput(
                    account=Account.SPONSOR_DEPOSIT, side=EntrySide.DEBIT, amount=payment.amount
                ),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.CREDIT,
                    amount=payment.amount,
                ),
            ],
        )
        JudgingExtensionPayment.objects.filter(pk=payment.pk).update(journal_entry_id=entry.id)
        payment.journal_entry_id = entry.id

        # 결제가 확정되는 사이(초기화 요청 -> confirm 사이) Award되었거나 이미
        # 심사기간이 종료됐다면, 더 늘릴 대상이 없다. 그 경우에도 위 원장 반영은
        # 그대로 둔다 — Sponsor가 낸 돈이 대사 가능한 흔적(JudgingExtensionPayment
        # PAID + JournalEntry)으로 남아 있어야 하기 때문이다(#13 리뷰 지적 1). 그
        # 돈을 어떻게 처리할지(환불 등)는 이 티켓 범위 밖이다(#17/#22).
        contest = Contest.objects.select_for_update().get(pk=payment.contest_id)
        if contest.status == Contest.Status.CLOSED and contest.judging_ends_at is not None:
            # 이 요청(confirm 한 번) 스코프에서 정책을 한 번만 읽는다(#78,
            # ADR-0023) — 이 분기 안에서만 필요하므로 위 재전송 조기 반환 뒤에
            # 읽는다.
            policy = get_current_policy()
            new_count = contest.judging_extension_count + 1
            new_refund_disabled = contest.refund_disabled or new_count >= 2
            new_judging_ends_at = contest.judging_ends_at + timedelta(
                days=policy.judging_extension_days
            )

            # claim_transition을 그대로 재사용한다 — from_state와 to_state가 둘 다
            # CLOSED인 "제자리" 전이이지만(상태 자체는 안 바뀐다), 그 덕분에
            # ① WHERE status='closed' 조건부 UPDATE라 위에서 이미 잠근 행이라도
            # 같은 규율을 한 번 더 지키고, ② auto_now 필드(updated_at)를 이
            # 메커니즘이 자동으로 채워준다(#13 리뷰 지적 6 — QuerySet.update()를
            # 직접 쓰면 updated_at이 갱신되지 않는다).
            claim_transition(
                Contest,
                contest.pk,
                from_state=Contest.Status.CLOSED,
                to_state=Contest.Status.CLOSED,
                state_field="status",
                now=Clock.now(),
                extra_fields={
                    "judging_ends_at": new_judging_ends_at,
                    "judging_extension_count": new_count,
                    "refund_disabled": new_refund_disabled,
                    # 심사기간 종료 임박 알림(#19)이 이미 발송된 뒤에 연장되면,
                    # 이 표식을 비워야 새로 늘어난 종료일이 다가올 때 다시 알릴
                    # 수 있다(#19 리뷰 지적 1). 안 비우면 "알림을 보고 연장했다"
                    # 는 정상 경로에서 Sponsor가 두 번째 종료일 앞에서는 아무
                    # 경고도 못 받고 바로 무응답 Distribution으로 넘어간다 —
                    # REQUEST.md가 이 티켓의 존재 이유로 든 "발주자가 깜빡한다"
                    # 를 정확히 재현하는 사고였다.
                    "judging_end_reminder_sent_at": None,
                },
            )

    return payment


def mark_extension_failed(order_id) -> JudgingExtensionPayment:
    """연장 결제를 실패로 확정한다. 이미 확정되어 있으면 아무 것도 다시 하지 않는다.

    실패 경로는 원장에도, 심사기간에도 아무 흔적을 남기지 않는다 — 돈이 움직이지
    않았다(payments.services.mark_failed와 같은 원칙).
    """

    JudgingExtensionPayment.objects.filter(
        order_id=order_id, status=JudgingExtensionPayment.Status.REQUESTED
    ).update(status=JudgingExtensionPayment.Status.FAILED)
    return JudgingExtensionPayment.objects.get(order_id=order_id)
