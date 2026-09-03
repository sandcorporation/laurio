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
    # "direct" | "widget" — 위젯을 거칠지는 PG 어댑터 모드가 가른다(#112).
    # 클라이언트 키의 유무가 아니다 — 그러면 키를 깜빡한 배포가 조용히
    # fake처럼 동작한다. payments.adapters.checkout_flow_for_current_mode 참고.
    checkout_flow: str
    created_at: datetime


class ConfirmPaymentIn(Schema):
    # fake PG 전용 시나리오 선택. 실제 어댑터(PAYMENT_ADAPTER_MODE=real)에서는 무시된다
    # — FakePGAdapter만 이 값을 해석한다(ADR-0007).
    simulate: str | None = None
    # 결제 건 식별자(#86) — 실물 PG(토스)가 결제 승인에 요구하는 값으로, 브라우저
    # 위젯이 성공했을 때만 생긴다. FakePGAdapter는 이 값을 무시하므로 optional —
    # 이 필드가 있어야 실물 어댑터(#87)가 값을 지어내지 않고 그대로 넘길 자리가
    # 생긴다.
    payment_key: str | None = None


class RunRefundsIn(Schema):
    # fake PG 전용 시나리오 선택. ConfirmPaymentIn.simulate와 같은 원칙 — 실제
    # 어댑터(PAYMENT_ADAPTER_MODE=real)에서는 무시된다(#17, ADR-0007).
    simulate: str | None = None


class WebhookIn(Schema):
    webhook_id: str
    order_id: UUID
    status: str  # "paid" | "failed" | "refunded" | "refund_failed" (#17)
    # PG(Fake PG 포함)만 계산할 수 있는 HMAC-SHA256 서명. 없거나 틀리면 402가
    # 아니라 401로 거부되고, 원장·Payment 상태 어느 것도 건드리지 않는다
    # (payments.webhook_security, #9 리뷰 지적 2).
    signature: str


class WebhookOut(Schema):
    received: bool
    order_id: UUID
    status: str


class ErrorOut(Schema):
    detail: str
