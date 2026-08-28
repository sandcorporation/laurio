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
    created_at: datetime
    # 심사기간 · 유료 연장 (#13, ADR-0003). CLOSED로 전이하기 전에는 아직 null이다.
    judging_ends_at: datetime | None
    judging_extension_count: int
    refund_disabled: bool


class ExtendJudgingPeriodIn(Schema):
    # fake PG 전용 시나리오 선택. 실제 어댑터에서는 무시된다(payments.schemas의
    # ConfirmPaymentIn과 같은 원칙, ADR-0007).
    simulate: str | None = None


class ExtendJudgingPeriodOut(Schema):
    contest_id: int
    judging_ends_at: datetime
    judging_extension_count: int
    refund_disabled: bool
