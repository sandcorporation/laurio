from datetime import datetime

from ninja import Schema
from pydantic import Field


class CategoryOut(Schema):
    id: int
    name: str


class DeliverableTypeOut(Schema):
    id: int
    name: str
    minimum_prize: int


class QuoteIn(Schema):
    deliverable_type_ids: list[int]


class QuoteOut(Schema):
    deliverable_type_ids: list[int]
    minimum_total: int


class RequirementIn(Schema):
    text: str = Field(max_length=500)
    grade: str  # "required" | "optional"


class RequirementOut(Schema):
    id: int
    text: str
    grade: str
    order: int


class ContestCreateIn(Schema):
    title: str = Field(max_length=200)
    category_id: int
    deliverable_type_ids: list[int]
    description: str = ""
    # Prize는 Sponsor가 실제로 예치하는 금액이다 — 0 이하는 개최로 성립하지 않는다.
    # 스키마에서 막지 않으면 음수가 PositiveIntegerField의 DB CHECK에 걸려 422 대신
    # 500이 난다.
    prize: int = Field(gt=0)
    deadline_at: datetime
    requirements: list[RequirementIn] = []


class ContestOut(Schema):
    id: int
    title: str
    category: CategoryOut
    deliverable_types: list[DeliverableTypeOut]
    description: str
    prize: int
    deadline_at: datetime
    status: str
    required_minimum_prize: int
    is_underfunded: bool
    requirements: list[RequirementOut]
    # 유찰 재개최(#22, ADR-0001)로 만들어진 사본이면 원본 Contest의 id를 가리킨다.
    # 원본이면 None이다.
    source_contest_id: int | None = None
    created_at: datetime
    # 심사기간 종료 시각(#13, ADR-0003) — CLOSED로 전이하기 전에는 아직 null이다.
    # deadline_at처럼 "언제까지"를 알려주는 사실 정보라 공개해도 무방하다.
    #
    # judging_extension_count·refund_disabled는 **일부러 여기 넣지 않는다** —
    # Sponsor가 유료 연장을 몇 번 샀는지, 환불이 잠겼는지는 그 Sponsor의 상업적
    # 정보다(#13 리뷰 지적 8). 이 스키마는 인증 없이도 누구나 받는 공개 목록/상세
    # 응답에 그대로 쓰이므로(contests.api.list_contests/get_contest), 여기 넣으면
    # 익명 방문자도 볼 수 있게 된다. 이 값들은 JudgingExtensionPaymentOut(연장
    # 확정 응답, Sponsor 본인 인증 필요)과 Django admin(운영자 전용)에서만 노출한다.
    judging_ends_at: datetime | None


class InitiateJudgingExtensionIn(Schema):
    pass


class ConfirmJudgingExtensionIn(Schema):
    # fake PG 전용 시나리오 선택. 실제 어댑터에서는 무시된다(payments.schemas의
    # ConfirmPaymentIn과 같은 원칙, ADR-0007).
    simulate: str | None = None


class JudgingExtensionPaymentOut(Schema):
    """payments.schemas.PaymentOut과 같은 형태 — 결제 시도 하나의 현재 상태."""

    order_id: str
    contest_id: int
    amount: int
    extension_number: int
    status: str
    checkout_url: str | None = None
    created_at: datetime
    # 이 응답을 만드는 시점 Contest의 최신 심사기간 상태(Sponsor 본인에게만
    # 노출된다 — 이 엔드포인트들은 jwt_auth + sponsor 소유 확인을 거친다).
    judging_ends_at: datetime | None
    judging_extension_count: int
    refund_disabled: bool


class RequirementCreateIn(Schema):
    text: str = Field(min_length=1, max_length=500)
    grade: str  # "required" | "optional"


class RequirementUpdateIn(Schema):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    grade: str | None = None
    # Requirement.order는 PositiveIntegerField(0 허용)라 DB CHECK가 "order" >= 0
    # 이다. ContestCreateIn.prize(위 Field(gt=0))와 같은 이유로 여기서 막지 않으면
    # 음수 order가 422가 아니라 IntegrityError -> 500으로 샌다.
    order: int | None = Field(default=None, ge=0)


class RequirementChatMessageIn(Schema):
    message: str = Field(min_length=1, max_length=2000)


class RequirementProposalOut(Schema):
    text: str
    grade: str


class RequirementChatTurnOut(Schema):
    role: str
    content: str
    created_at: datetime


class RequirementChatResponseOut(Schema):
    reply: str
    proposed_requirements: list[RequirementProposalOut]
    messages: list[RequirementChatTurnOut]


class ContestReopenIn(Schema):
    """유찰 재개최 시 새로 지정하는 값 — Prize와 마감기한뿐이다(#22).

    요구사항·체크리스트·DeliverableType·Category·제목·설명은 원본에서 그대로
    복제되므로 여기서 다시 받지 않는다(ADR-0001 — "요구사항 명세를 처음부터
    다시 쓰지 않는다").
    """

    prize: int = Field(gt=0)
    deadline_at: datetime
