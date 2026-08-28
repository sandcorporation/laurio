"""결제 · Escrow 예치 도메인 모델 (#9, ADR-0004, ADR-0007).

`Payment`는 한 `Contest`의 `Prize` + 개최 등록비를 한 번에 결제하는 시도 하나를
나타낸다. 실제 돈의 최종 진실은 원장(`ledger`)에만 있다 — 이 모델은 PG와의 대화
상태(요청됨/완료/실패)만 들고, 완료로 전이하는 순간에만 원장에 분개를 남긴다.

동시성·재전송에 안전한 이유는 `services.mark_paid`/`mark_failed`가 ADR-0003과 같은
조건부 `UPDATE ... WHERE status='requested'` 규율을 그대로 따르기 때문이다 — 이
티켓은 그 일반 스케줄러 메커니즘(별도 브랜치에서 chain A가 만드는 것)을 가져오지
않고, 같은 규율만 이 파일 안에서 반복한다.
"""

from __future__ import annotations

import uuid

from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "요청됨"
        PAID = "paid", "결제완료"
        FAILED = "failed", "결제실패"

    contest = models.ForeignKey(
        "contests.Contest", related_name="payments", on_delete=models.CASCADE
    )
    # PG에 전달하는 주문 참조값. Fake PG 웹훅도 이 값으로 어떤 결제인지 찾는다.
    order_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # 결제 시점의 스냅샷 — Contest.prize나 등록비 정책이 나중에 바뀌어도 이미 요청된
    # 결제 금액은 흔들리지 않는다.
    prize_amount = models.PositiveIntegerField()
    listing_fee_amount = models.PositiveIntegerField()

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)

    # 이 결제가 원장에 남긴 예치 분개. 성공 시 정확히 한 번만 채워진다(감사용 — 실제
    # 중복 방지는 status의 조건부 UPDATE가 담당하므로 이 필드가 비어 있다고 해서
    # 다시 채워 넣지 않는다).
    journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Payment(order_id={self.order_id}, status={self.status})"

    @property
    def total_amount(self) -> int:
        return self.prize_amount + self.listing_fee_amount


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
