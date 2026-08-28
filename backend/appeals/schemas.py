from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field


class ErrorOut(Schema):
    detail: str


class AppealCreateIn(Schema):
    reason: str = Field(min_length=1, max_length=4000)


class AppealOut(Schema):
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


class AppealDetailOut(AppealOut):
    """운영자 전용 상세 — 이의제기 자체에 Score 스냅샷을 얹어 함께 돌려준다."""

    score: ScoreSnapshotOut


class AppealRulingIn(Schema):
    decision: str  # "uphold" | "reject"
    ruling_note: str = Field(default="", max_length=4000)
    # decision == "uphold"일 때만 필수다. 운영자가 근거를 검토해 직접 정하는
    # 정정 금액 — 자동으로 계산되지 않는다(재채점 경로가 없는 것과 같은 이유).
    correction_amount: int | None = Field(default=None, gt=0, le=1_000_000_000)
