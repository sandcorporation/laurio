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
    # RequirementResponse.note와 같은 길이(#10 리뷰 지적) — 스키마가 막지 않으면
    # DB CHECK(varchar(1000))이 대신 걸려 422 대신 500(DataError)이 난다.
    note: str = Field(default="", max_length=1000)
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
    # 아래 세 max_length는 각각 submissions.models.Submission의 같은 필드와
    # 길이를 맞춘다(#10 리뷰 지적) — 스키마가 막지 않으면 DB CHECK가 대신 걸려
    # 422 대신 500(DataError)이 난다.
    source_object_key: str = Field(max_length=600)
    demo_video_object_key: str | None = Field(default=None, max_length=600)
    demo_url: str | None = Field(default=None, max_length=2000)
    test_account: str | None = Field(default=None, max_length=500)
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


class PublicSubmissionOut(Schema):
    """Developer 공개 프로필 아카이브 한 항목 (#11, ADR-0014).

    마감된 Contest의 데모·영상만 담는다 — 소스·test_account는 이 스키마 자체에
    없다("존재하지만 안 보임"이 아니라 애초에 필드가 없다). ADR-0014의 "마감 후"
    칸에 있는 건 데모·영상뿐이다.
    """

    submission_id: int
    contest_id: int
    contest_title: str
    demo_video_object_key: str | None
    demo_url: str | None
    created_at: datetime


class DeveloperPublicProfileOut(Schema):
    developer_id: int
    display_name: str
    bio: str
    submissions: list[PublicSubmissionOut]
