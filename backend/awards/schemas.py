from __future__ import annotations

from datetime import datetime

from ninja import Schema


class AwardIn(Schema):
    submission_id: int


class AwardOut(Schema):
    contest_id: int
    submission_id: int
    awarded_at: datetime
