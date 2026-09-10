from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema


class ErrorOut(Schema):
    detail: str


class ClassIn(Schema):
    name: str = Field(min_length=1, max_length=200)


class ClassPatchIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    default_model: str | None = None


class ClassOut(Schema):
    id: int
    name: str
    join_code: str
    created_at: datetime
    default_model: str
    has_openai_key: bool
    openai_key_masked: str | None = None


class OpenAIKeyIn(Schema):
    api_key: str = Field(min_length=1, max_length=400)


class ScoringModelOut(Schema):
    id: str
    label: str
    context_window: int


class JoinLinkOut(Schema):
    join_code: str


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
    #: 빈 문자열을 보내면 문제 자신의 모델을 지우고 클래스 기본값을
    #: 따르게 한다 — `None`(필드 생략)은 "바꾸지 않는다"는 기존 PATCH
    #: 관례 그대로다.
    model: str | None = None


class ProblemOut(Schema):
    id: int
    classroom_id: int
    title: str
    description: str
    submission_format: str
    status: str
    order: int
    #: 이 문제 자신의 값. 빈 문자열이면 클래스 기본값을 따른다는 뜻이다.
    model: str
    #: 실제로 채점에 쓰일 값 — `model`이 비어 있으면 클래스의 `default_model`.
    effective_model: str
    checklist_items: list[ChecklistItemOut] = []


class ProblemReorderIn(Schema):
    problem_ids: list[int]


class JoinPreviewOut(Schema):
    class_name: str
    instructor_email: str
    problem_count: int
    participant_count: int


class JoinIn(Schema):
    display_name: str = Field(min_length=1, max_length=100)


class JoinResultOut(Schema):
    class_id: int
    class_name: str
    display_name: str


class MemberOut(Schema):
    id: int
    display_name: str
    joined_at: datetime
    expelled: bool
    is_instructor: bool
