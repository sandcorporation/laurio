"""`/api/ledger` 요청/응답 스키마.

`account`·`side`는 Django 모델과 같은 Enum(`Account`/`EntrySide`)을 그대로 쓴다 —
계정과목 다섯 개 이외의 값은 여기서 422로 거부된다. `amount`는 정수만 받는다(원 단위,
ADR-0004) — 소수가 섞인 값은 여기서 거부된다.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Field, Schema

from ledger.models import Account, EntrySide


class LedgerLineIn(Schema):
    account: Account
    side: EntrySide
    amount: int = Field(gt=0)


class JournalEntryIn(Schema):
    contest_id: UUID
    memo: str = ""
    reverses_id: int | None = None
    # 최소 두 줄 — 차변 한 줄·대변 한 줄이 없으면 애초에 복식부기가 아니다.
    lines: list[LedgerLineIn] = Field(min_length=2)


class LedgerLineOut(Schema):
    account: Account
    side: EntrySide
    amount: int


class JournalEntryOut(Schema):
    id: int
    contest_id: UUID
    memo: str
    reverses_id: int | None = None
    created_at: datetime
    lines: list[LedgerLineOut]


class ContestBalanceOut(Schema):
    contest_id: UUID
    balance: int
    is_balanced: bool


class ErrorOut(Schema):
    detail: str
