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


class ClassroomProblemMineOut(Schema):
    """참여자가 보는 문제 하나(#286) — 강사 전용 `ProblemOut`과 달리 `status`가
    없다(참여자는 열린 문제만 이 자리에 닿으므로 구별할 이유가 없다).

    이름이 `Classroom` 접두어를 든다 — `contests.submission_schemas.
    ProblemOut`은 없지만 `SubmissionIn`·`SubmissionOut`은 있고, django-ninja가
    OpenAPI 컴포넌트 이름을 클래스명 그대로 쓰기 때문에 겹치면 조용히 한쪽을
    덮어써 공개 앱의 생성 타입이 깨진다(실제로 한 번 그랬다 — `pnpm --dir
    frontend typecheck`가 잡았다). 이 파일의 다른 `Submission*` 스키마도 같은
    이유로 전부 `Classroom` 접두어를 든다."""

    id: int
    classroom_id: int
    title: str
    description: str
    submission_format: str
    checklist_items: list[ChecklistItemOut] = []


class ClassroomSubmissionIn(Schema):
    #: `submission_format`이 소스면 storage가 발급한 object_key, 저장소면
    #: GitHub URL — 종류는 Problem이 이미 정해 두었으므로 페이로드에 다시
    #: 싣지 않는다(공모전의 다중 자료 배열과 다른 점).
    value: str = Field(min_length=1, max_length=2000)
    #: 업로드 발급 시 받은 content-type(#241과 같은 이유) — 소스가 아니면
    #: 무시한다. 다운로드 파일명의 확장자를 유도한다.
    content_type: str | None = None


class ClassroomSubmissionOut(Schema):
    id: int
    problem_id: int
    attempt_number: int
    submission_format: str
    value: str
    #: 소스 제출에만 채워진다 — 저장소는 `value` 자체가 이미 열어 볼 수 있는
    #: URL이라 별도 다운로드가 필요 없다. 파일명은 제출자 본인의 User 정보를
    #: 따른다(강의실 참여자는 DeveloperProfile이 없다, #286 AC).
    download_url: str | None = None
    created_at: datetime


class ClassroomProblemSubmissionsOut(Schema):
    problem: ClassroomProblemMineOut
    submissions: list[ClassroomSubmissionOut]
