"""원장 도메인 로직.

API 레이어(`ledger.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기 함수를
테스트에서 직접 부르지 않는다(`CLAUDE.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from ledger.models import Account, EntrySide, JournalEntry, LedgerLine


class UnbalancedEntryError(Exception):
    """차변 합과 대변 합이 일치하지 않는 분개를 등록하려 한 경우."""

    def __init__(self, debit_total: int, credit_total: int):
        self.debit_total = debit_total
        self.credit_total = credit_total
        super().__init__(
            f"차변 합({debit_total})과 대변 합({credit_total})이 일치하지 않는다."
        )


class UnknownReversalTargetError(Exception):
    """존재하지 않는 분개를 반대 분개 대상으로 지정한 경우."""


@dataclass(frozen=True)
class LineInput:
    account: str
    side: str
    amount: int


def post_journal_entry(
    *,
    contest_id: UUID,
    lines: list[LineInput],
    memo: str = "",
    reverses_id: int | None = None,
) -> JournalEntry:
    """분개 하나를 원장에 기록한다.

    차변 합 == 대변 합이 아니면 `UnbalancedEntryError`를 던지고 아무 것도 저장하지
    않는다(원자적). 원장은 append-only이므로 이 함수는 오직 새 행만 만든다 — 기존
    `JournalEntry`/`LedgerLine`을 절대 건드리지 않는다.
    """

    debit_total = sum(line.amount for line in lines if line.side == EntrySide.DEBIT)
    credit_total = sum(line.amount for line in lines if line.side == EntrySide.CREDIT)

    if debit_total != credit_total:
        raise UnbalancedEntryError(debit_total, credit_total)

    with transaction.atomic():
        reverses = None
        if reverses_id is not None:
            try:
                reverses = JournalEntry.objects.get(pk=reverses_id)
            except JournalEntry.DoesNotExist as exc:
                raise UnknownReversalTargetError(
                    f"반대 분개 대상 JournalEntry(id={reverses_id})가 존재하지 않는다."
                ) from exc

        entry = JournalEntry.objects.create(
            contest_id=contest_id, memo=memo, reverses=reverses
        )
        LedgerLine.objects.bulk_create(
            LedgerLine(entry=entry, account=line.account, side=line.side, amount=line.amount)
            for line in lines
        )

    return entry


def contest_balance(contest_id: UUID) -> int:
    """한 Contest의 원장 순합계(차변 - 대변)를 구한다.

    정상적으로 기록된 원장이라면(모든 분개가 차변==대변) 항상 0이어야 한다 — 이 함수는
    그 불변식을 운영자가 눈으로 확인할 수 있게 노출하는 감사용 조회다.
    """

    lines = LedgerLine.objects.filter(entry__contest_id=contest_id)
    debit_total = sum(
        line.amount for line in lines if line.side == EntrySide.DEBIT
    )
    credit_total = sum(
        line.amount for line in lines if line.side == EntrySide.CREDIT
    )
    return debit_total - credit_total


def contest_entries(contest_id: UUID):
    """한 Contest에 속한 분개를 등록 순서대로 돌려준다(라인 포함)."""

    return (
        JournalEntry.objects.filter(contest_id=contest_id)
        .prefetch_related("lines")
        .order_by("id")
    )


ACCOUNTS = list(Account.values)
