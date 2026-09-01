from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Field, Schema


class PayoutOut(Schema):
    idempotency_key: UUID
    contest_id: int
    prize_amount: int
    platform_fee_amount: int
    withholding_tax_amount: int
    net_amount: int
    status: str
    has_identity: bool
    # Seller가 아직 등록되지 않았으면 None. 있으면 "pending" | "partially_approved"
    # | "under_review" | "rejected" 중 하나(#50, ADR-0020) — 두 대기(신원/Seller)
    # 중 이쪽이 무엇을 기다리는지 Developer·Operator가 조회할 수 있어야 한다.
    seller_status: str | None
    # Developer가 다음에 무엇을 해야 하는지(또는 왜 아직 기다려야 하는지)를
    # 사람이 읽을 수 있는 한국어 문장으로 준다 — 침묵은 상금이 사라진 것으로
    # 읽힌다(#50 AC).
    #
    # **이름이 `next_action` 이었다가 바뀌었다(#74).** 「내 참가 현황」이
    # `next_action` 을 **타입 있는 enum** 으로 쓰기 시작했는데(submissions.
    # participation.NextAction), 같은 API 안에 같은 이름의 두 계약 — 하나는
    # 판정값, 하나는 한국어 문장 — 이 공존하면 생성된 타입을 읽는 사람이 어느
    # 쪽인지 알 수 없다. 그리고 "문구를 서버가 소유한다" 는 #74 심문에서
    # 명시적으로 택하지 않은 쪽이다(문구 하나 고치는 데 백엔드 배포가 필요해지고
    # i18n 을 나중에 넣기 어려워진다). 이 필드는 #50 이 먼저 만든 것이라 지금
    # 지우지 않고 이름만 자기가 무엇인지 말하게 바꾼다 — 지급 화면을 만드는
    # 슬라이스가 이 자리에 enum 을 더하고 문구를 프론트로 옮긴다.
    next_action_message: str
    created_at: datetime


class ConfirmPayoutIn(Schema):
    # fake 토스 지급대행 전용 시나리오 선택. 실제 어댑터(PAYOUT_ADAPTER_MODE=real)
    # 에서는 무시된다 — FakePayoutAdapter만 이 값을 해석한다(ADR-0007).
    simulate: str | None = None
    # fake Seller 등록 어댑터 전용 시나리오 선택("success"(기본)/"limit_exceeded"/
    # "review_required"/"rejected"). 같은 원칙(ADR-0007) — 실제 어댑터에서는
    # 무시된다. Payout이 이 confirm 호출로 처음 확정될 때만 의미가 있다 — 이미
    # 확정된 뒤의 재호출은 이 값을 보지 않는다(payouts.services.mark_confirmed).
    seller_simulate: str | None = None


class SellerRegistrationRetryIn(Schema):
    # ConfirmPayoutIn.seller_simulate와 같은 원칙 — fake Seller 등록 어댑터
    # 전용 시나리오 선택이다.
    simulate: str | None = None


class WebhookIn(Schema):
    webhook_id: str
    idempotency_key: UUID
    status: str  # "paid" | "failed"
    # 토스(Fake 포함)만 계산할 수 있는 HMAC-SHA256 서명. 없거나 틀리면 401로
    # 거부되고, 원장·Payout 상태 어느 것도 건드리지 않는다(payments.webhook_security
    # 를 그대로 재사용, #9 리뷰 지적 2와 같은 이유).
    signature: str


class WebhookOut(Schema):
    received: bool
    idempotency_key: UUID
    status: str


class IdentitySubmitIn(Schema):
    # 형식만 검증한다(숫자로만 이루어진 13자리) — 실제 유효성(생년월일·성별 코드
    # 정합, 체크섬)까지 검사하는 건 이 티켓 범위 밖이다. 길이만 보고 통과시키면
    # "13자리 문자열"이면 뭐든(공백·기호 포함) 암호화되어 저장되고 만다(#15
    # 리뷰 지적 4) — 패턴으로 숫자만 허용한다.
    resident_registration_number: str = Field(pattern=r"^\d{13}$")


class ErrorOut(Schema):
    detail: str


class OperatorPayoutOut(Schema):
    """Operator가 Payout 하나가 무엇을 기다리는지 보는 표면(#50 AC).

    `blocked_on`은 "identity" | "seller" | None(둘 다 안 기다림 — 이미
    CONFIRMED거나 아직 REQUESTED/FAILED) 중 하나다. 두 대기를 한 상태로
    뭉치지 않는다는 요구가 Operator 조회에서도 그대로 지켜져야 한다.
    """

    idempotency_key: UUID
    contest_id: int
    developer_user_id: int
    net_amount: int
    status: str
    blocked_on: str | None
    seller_status: str | None
    has_identity: bool
    created_at: datetime
