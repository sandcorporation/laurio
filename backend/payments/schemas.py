from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Schema


class InitiatePaymentIn(Schema):
    contest_id: int


class PaymentOut(Schema):
    order_id: UUID
    contest_id: int
    prize_amount: int
    listing_fee_amount: int
    total_amount: int
    status: str
    checkout_url: str | None = None
    created_at: datetime


class ConfirmPaymentIn(Schema):
    # fake PG 전용 시나리오 선택. 실제 어댑터(PAYMENT_ADAPTER_MODE=real)에서는 무시된다
    # — FakePGAdapter만 이 값을 해석한다(ADR-0007).
    simulate: str | None = None


class WebhookIn(Schema):
    webhook_id: str
    order_id: UUID
    status: str  # "paid" | "failed"


class WebhookOut(Schema):
    received: bool
    order_id: UUID
    status: str


class ErrorOut(Schema):
    detail: str
