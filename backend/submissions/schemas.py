from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field


class EvidenceIn(Schema):
    kind: str
    value: str = Field(max_length=500)


class EvidenceOut(Schema):
    kind: str
    value: str


class RequirementResponseIn(Schema):
    requirement_id: int
    is_met: bool = False
    note: str = ""
    evidence: list[EvidenceIn] = []


class RequirementResponseOut(Schema):
    requirement_id: int
    is_met: bool
    note: str
    evidence: list[EvidenceOut]
    # Evidence가 하나도 연결되지 않은 자가 응답인지 (ADR-0014 — 미연결은 거부가
    # 아니라 표시만 한다. 점수화는 #12 소관).
    is_linked: bool


class SubmissionIn(Schema):
    source_object_key: str = Field(max_length=600)
    demo_video_object_key: str | None = None
    demo_url: str | None = None
    test_account: str | None = None
    requirement_responses: list[RequirementResponseIn] = []


class CompletionOut(Schema):
    """시연 영상·데모 URL·테스트 계정·Evidence 연결 상태를 요약한 완성도 지표.

    강제 항목은 아무 것도 없다 — 소스만 필수다. 이 지표는 신호일 뿐이다.
    """

    has_demo_video: bool
    has_demo_url: bool
    has_test_account: bool
    total_requirement_count: int
    linked_requirement_count: int
    unlinked_requirement_count: int


class SubmissionOut(Schema):
    id: int
    contest_id: int
    developer_id: int
    is_owner: bool
    # 뷰어가 볼 수 없는 필드는 값을 지우지 않고 아예 null로 내려 "존재하지만 안 보임"과
    # "비어 있음"을 구분한다.
    source_object_key: str | None
    demo_video_object_key: str | None
    demo_url: str | None
    test_account: str | None
    requirement_responses: list[RequirementResponseOut]
    completion: CompletionOut
    created_at: datetime
    updated_at: datetime
