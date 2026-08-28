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


# 1,000조 원(10^15) — PostgreSQL bigint 범위(~9.22 * 10^18)보다 훨씬 안쪽이면서
# 실제 있을 법한 Contest 상금·수수료보다는 넉넉한 상식적 상한. 이 값을 넘는 금액은
# 여기서 422로 거부한다 — 안 그러면 PositiveBigIntegerField의 검증(full_clean)이 API
# 경로에서 호출되지 않으므로, bigint 범위를 넘는 값이 그대로 INSERT까지 가서 처리되지
# 않은 DataError로 500이 난다.
MAX_AMOUNT = 1_000_000_000_000_000


class LedgerLineIn(Schema):
    account: Account
    side: EntrySide
    amount: int = Field(gt=0, le=MAX_AMOUNT)


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
