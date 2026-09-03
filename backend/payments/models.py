"""결제 · Escrow 예치 도메인 모델 (#9, ADR-0004, ADR-0007).

`Payment`는 한 `Contest`의 `Prize` + 개최 등록비를 한 번에 결제하는 시도 하나를
나타낸다. 실제 돈의 최종 진실은 원장(`ledger`)에만 있다 — 이 모델은 PG와의 대화
상태(요청됨/완료/실패)만 들고, 완료로 전이하는 순간에만 원장에 분개를 남긴다.

동시성·재전송에 안전한 이유는 `payments.charges.apply_vendor_outcome`이 ADR-0003과 같은
조건부 `UPDATE ... WHERE status='requested'` 규율을 그대로 따르기 때문이다 — 이
티켓은 그 일반 스케줄러 메커니즘(별도 브랜치에서 chain A가 만드는 것)을 가져오지
않고, 같은 규율만 이 파일 안에서 반복한다.
"""

from __future__ import annotations

from django.db import models

from .charges import ChargeBase


class Payment(ChargeBase):
    """Sponsor 의 Prize 예치 + 개최 등록비 결제 시도 하나 — Charge(CONTEXT.md)의 한 종류
    (#127, #118). 뼈대(`payments.charges.ChargeBase`)는 심사 연장비와 같고, 이 종류에
    고유한 것은 분개의 줄(`journal` — 예치금/미지급금/수수료 3줄), 확정에 딸려오는 부모
    전이(`on_paid` — Contest 공개), 그리고 환불 상태 셋이다.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "요청됨"
        PAID = "paid", "결제완료"
        FAILED = "failed", "결제실패"
        # 참여자 0명 전액 환불(#17, ADR-0004)의 유일한 경로로만 도달한다 — PAID에서만
        # 조건부 UPDATE로 REFUND_REQUESTED로 넘어가고(services.request_refund), PG
        # 확정 결과에 따라 REFUNDED 또는 REFUND_FAILED로 전이한다. REQUESTED에서 한 번만
        # 전이하고 절대 되돌아가지 않는 것과 같은 이유로, REFUND_REQUESTED는 PAID로도
        # 되돌아가지 않는다 — 되돌아가면 재전송된 refund_failed 웹훅이 그 사이 새로
        # 시작된 다른(더 최신) 환불 시도를 잘못 취소시킬 수 있다(리뷰 지적 1). 실패는
        # REFUND_FAILED라는 새로운 종결 상태로만 전진한다.
        REFUND_REQUESTED = "refund_requested", "환불요청됨"
        REFUNDED = "refunded", "환불완료"
        REFUND_FAILED = "refund_failed", "환불실패"

    contest = models.ForeignKey(
        "contests.Contest", related_name="payments", on_delete=models.CASCADE
    )

    # 결제 시점의 스냅샷 — Contest.prize나 등록비 정책이 나중에 바뀌어도 이미 요청된
    # 결제 금액은 흔들리지 않는다.
    prize_amount = models.PositiveIntegerField()
    listing_fee_amount = models.PositiveIntegerField()

    # ChargeBase 의 세 값에 환불 셋을 더한 이 종류의 상태 — 필드 정의는 같고 choices 만 넓다.
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)

    # 이 결제를 취소한 반대 분개(journal_entry_id가 가리키는 원본 예치 분개를
    # reverses한다). REFUNDED로 전이하는 순간 정확히 한 번만 채워진다 — journal_entry_id
    # 와 같은 감사용 필드다(실제 중복 방지는 status의 조건부 UPDATE가 담당한다).
    refund_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 진행 중이거나 완료된 결제는 Contest 당 정확히 하나뿐이어야 한다
            # (#9 리뷰 지적 3) — initiate_payment의 조회-후-생성이 락 없이 경합하면
            # 같은 Contest에 활성 Payment가 두 개 생겨, 둘 다 확정될 경우 원장에
            # 예치 분개가 두 번 남는다(정확히 ADR-0003이 막으려는 이중 반영이다).
            # failed는 제외해 재시도(새 결제)를 막지 않는다 — 부분 인덱스라서
            # status='failed'인 행끼리는 이 제약에 걸리지 않는다.
            models.UniqueConstraint(
                fields=["contest"],
                condition=models.Q(status__in=["requested", "paid"]),
                name="unique_active_payment_per_contest",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Payment(order_id={self.order_id}, status={self.status})"

    @property
    def total_amount(self) -> int:
        return self.prize_amount + self.listing_fee_amount

    @property
    def charged_amount(self) -> int:
        return self.total_amount

    def journal(self):
        """예치 분개 — 결제 총액(Prize + 개최 등록비)이 발주자 예치금에서 빠져나와, Prize는
        개발자 미지급금(Escrow — 이후 Payout·Distribution·환불로만 빠져나간다)으로, 등록비는
        플랫폼 수수료 수익으로 즉시 인식되는 것으로 기록한다."""

        from ledger.models import Account, EntrySide
        from ledger.services import LineInput

        return (
            self.contest.ledger_id,
            (
                f"Contest #{self.contest_id} 결제 예치 — "
                f"상금 {self.prize_amount:,}원 + 개최 등록비 {self.listing_fee_amount:,}원"
            ),
            [
                LineInput(account=Account.SPONSOR_DEPOSIT, side=EntrySide.DEBIT, amount=self.total_amount),
                LineInput(
                    account=Account.DEVELOPER_PAYABLE, side=EntrySide.CREDIT, amount=self.prize_amount
                ),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.CREDIT,
                    amount=self.listing_fee_amount,
                ),
            ],
        )

    def on_paid(self) -> None:
        """결제가 문을 닫는다(CONTEXT.md Contest) — draft 일 때만 published 로. 이 결제가 이미
        REQUESTED→PAID 를 이겼으므로 정상 경로에서는 항상 draft 여야 하지만, 조건을 남겨
        이중 공개를 구조적으로 막는다."""

        from contests.models import Contest

        Contest.objects.filter(pk=self.contest_id, status=Contest.Status.DRAFT).update(
            status=Contest.Status.PUBLISHED
        )


class WebhookDelivery(models.Model):
    """Fake PG(혹은 실제 PG)가 보낸 웹훅 전달 시도 하나. 감사 로그 + 재전송 관찰용.

    멱등성의 실제 방어선은 `Payment.status`의 조건부 UPDATE다(같은 웹훅이 두 번 와도,
    또 다른 채널(동기 confirm)이 먼저 도착해도 원장 분개는 한 번만 남는다). 이 테이블은
    "정말로 같은 webhook_id가 두 번 왔는가"를 나중에 사람이 들여다볼 수 있게 남기는
    용도이므로 unique 제약을 걸지 않는다 — 재전송 자체를 막는 게 아니라 관찰하는 것이
    목적이다.
    """

    payment = models.ForeignKey(
        Payment, related_name="webhook_deliveries", on_delete=models.CASCADE, null=True, blank=True
    )
    webhook_id = models.CharField(max_length=64)
    order_id = models.UUIDField()
    event_status = models.CharField(max_length=16)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"WebhookDelivery(webhook_id={self.webhook_id}, order_id={self.order_id})"
