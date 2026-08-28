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


class ContestReopenIn(Schema):
    """유찰 재개최 시 새로 지정하는 값 — Prize와 마감기한뿐이다(#22).

    요구사항·체크리스트·DeliverableType·Category·제목·설명은 원본에서 그대로
    복제되므로 여기서 다시 받지 않는다(ADR-0001 — "요구사항 명세를 처음부터
    다시 쓰지 않는다").
    """

    prize: int = Field(gt=0)
    deadline_at: datetime
