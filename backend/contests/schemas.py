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
