from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema


class ErrorOut(Schema):
    detail: str


class ClassIn(Schema):
    name: str = Field(min_length=1, max_length=200)


class ClassOut(Schema):
    id: int
    name: str
    created_at: datetime
    has_openai_key: bool
    openai_key_masked: str | None = None


class OpenAIKeyIn(Schema):
    api_key: str = Field(min_length=1, max_length=400)


class ChecklistItemIn(Schema):
    label: str = Field(min_length=1, max_length=200)
    required: bool = True


class ChecklistItemPatchIn(Schema):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    required: bool | None = None


class ChecklistItemOut(Schema):
    id: int
    label: str
    required: bool
    order: int


class ChecklistReorderIn(Schema):
    item_ids: list[int]


class ProblemIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    submission_format: str


class ProblemPatchIn(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    submission_format: str | None = None


class ProblemOut(Schema):
    id: int
    classroom_id: int
    title: str
    description: str
    submission_format: str
    status: str
    order: int
    checklist_items: list[ChecklistItemOut] = []


class ProblemReorderIn(Schema):
    problem_ids: list[int]
