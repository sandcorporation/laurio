from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field


class ErrorOut(Schema):
    detail: str


class AppealCreateIn(Schema):
    reason: str = Field(min_length=1, max_length=4000)


class AppealOut(Schema):
    """Developer 가 보는 자기 이의의 상태.

    심판 결과는 이제 별도 테이블에 살지만(AppealRuling, #44) 여기 필드 구성은
    그대로 둔다 — Developer 쪽 계약을 바꿀 이유가 없다. 심판 전에는 전부 비어 있고,
    `ruled_by` 는 여기에 넣지 않는다: 이의를 제기한 사람에게 심판한 개인의 이름을
    노출할 이유가 없고, 감사에 필요한 것은 운영자 표면에서 조회된다.
    """

    id: int
    submission_id: int
    reason: str
    status: str
    ruling_note: str
    correction_amount: int | None = None
    ruled_at: datetime | None = None
    created_at: datetime


class ScoreSnapshotOut(Schema):
    """운영자가 심판 근거로 보는 Score 스냅샷 그대로 — 점수·근거·프롬프트·모델버전
    전부(#21 AC, ADR-0006).
    """

    percentage: str
    model_version: str
    prompt: str
    reasoning: list[dict]
    created_at: datetime


class RulingOut(Schema):
    """심판 기록 — 운영자 표면에서만 보인다.

    `ruled_by_*` 가 이 스펙의 목적 그 자체다. 이 행이 존재하는데 이 필드가 비어
    있는 상태는 스키마상 만들 수 없다(AppealRuling 참고).
    """

    decision: str
    ruled_by_id: int
    ruled_by_username: str
    note: str
    ruled_at: datetime
    correction_amount: int | None = None
    correction_journal_entry_id: int | None = None


class AppealDetailOut(AppealOut):
    """운영자 전용 상세 — 이의제기 자체에 Score 스냅샷과 심판 기록을 얹는다."""

    score: ScoreSnapshotOut
    ruling: RulingOut | None = None


class AppealRulingIn(Schema):
    decision: str  # "uphold" | "reject"
    ruling_note: str = Field(default="", max_length=4000)
    # decision == "uphold"일 때만 필수다. 운영자가 근거를 검토해 직접 정하는
    # 정정 금액 — 자동으로 계산되지 않는다(재채점 경로가 없는 것과 같은 이유).
    correction_amount: int | None = Field(default=None, gt=0, le=1_000_000_000)
