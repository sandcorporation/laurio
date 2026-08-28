"""원장 도메인 로직.

API 레이어(`ledger.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기 함수를
테스트에서 직접 부르지 않는다(`CLAUDE.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

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


class CrossContestReversalError(Exception):
    """다른 Contest에 속한 분개를 반대 분개 대상으로 지정한 경우."""


class DuplicateReversalError(Exception):
    """이미 반대 분개가 걸린 원본 분개를 다시 반대 분개하려 한 경우.

    재시도·중복 클릭으로 같은 정정이 두 번 들어가면 금액이 이중으로 취소·가산되는
    이중지급류 버그가 된다(ADR-0003, ADR-0004) — 그런데 반대 분개도 그 자체로는
    차변==대변이 맞아떨어지므로 전체 순합계만 보면 이상이 감춰진다. 그래서 이 검증은
    금액 합계 검증과 별개로, 반드시 막아야 한다.
    """


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
            # select_for_update로 원본 행을 잠근다 — 동시에 들어온 두 요청이 같은
            # 분개를 동시에 반대 분개하려 하면 하나는 여기서 대기했다가, 먼저 커밋된
            # 트랜잭션이 풀리고 나서 아래 existence 체크에서 걸린다. 잠금 없이 존재
            # 체크만 하면 두 트랜잭션이 동시에 통과해버리는 경합이 남는다.
            try:
                reverses = JournalEntry.objects.select_for_update().get(pk=reverses_id)
            except JournalEntry.DoesNotExist as exc:
                raise UnknownReversalTargetError(
                    f"반대 분개 대상 JournalEntry(id={reverses_id})가 존재하지 않는다."
                ) from exc

            if reverses.contest_id != contest_id:
                raise CrossContestReversalError(
                    f"JournalEntry(id={reverses_id})는 contest_id={reverses.contest_id}에 "
                    f"속해 있어 다른 contest_id={contest_id}의 정정 대상이 될 수 없다."
                )

            if JournalEntry.objects.filter(reverses_id=reverses_id).exists():
                raise DuplicateReversalError(
                    f"JournalEntry(id={reverses_id})는 이미 반대 분개가 걸려 있다. "
                    "같은 분개를 두 번 정정할 수 없다."
                )

        try:
            entry = JournalEntry.objects.create(
                contest_id=contest_id, memo=memo, reverses=reverses
            )
        except IntegrityError as exc:
            # select_for_update + existence 체크를 다 통과했더라도 DB의 유니크
            # 제약이 최후의 방어선이다 — 여기 걸리면 위의 애플리케이션 레벨 체크가
            # 뚫린 것이므로 같은 도메인 예외로 바꿔서 500이 아니라 400으로 응답한다.
            raise DuplicateReversalError(
                f"JournalEntry(id={reverses_id})는 이미 반대 분개가 걸려 있다."
            ) from exc

        LedgerLine.objects.bulk_create(
            LedgerLine(entry=entry, account=line.account, side=line.side, amount=line.amount)
            for line in lines
        )

    return entry


def contest_balance(contest_id: UUID) -> dict:
    """한 Contest의 원장 감사 결과.

    `net_balance`(전체 차변 - 전체 대변)만 보는 것으로는 부족하다 — 예를 들어 어떤 분개가
    라인 하나를 잃어 그 자체로는 깨졌어도, 다른 분개의 반대 방향 오차와 우연히 상쇄되면
    전체 순합계는 0으로 보인다(append-only 우회가 실제로 이렇게 숨겨질 수 있다). 그래서
    전체 순합계와, 분개 하나하나가 스스로 균형이 맞는지(라인이 2개 이상이고 그 안에서도
    차변==대변인지)를 함께 본다. 둘 다 통과해야 `is_balanced`가 True다.

    DB에서 집계(Sum)까지 끝내고 파이썬으로는 값만 받는다 — 대규모 Contest라도 라인을
    전부 메모리에 올리지 않는다.
    """

    totals = LedgerLine.objects.filter(entry__contest_id=contest_id).aggregate(
        debit_total=Coalesce(Sum("amount", filter=Q(side=EntrySide.DEBIT)), 0),
        credit_total=Coalesce(Sum("amount", filter=Q(side=EntrySide.CREDIT)), 0),
    )
    net_balance = totals["debit_total"] - totals["credit_total"]

    has_broken_entry = _has_broken_entry(contest_id)

    return {
        "balance": net_balance,
        "is_balanced": net_balance == 0 and not has_broken_entry,
    }


def _has_broken_entry(contest_id: UUID) -> bool:
    """라인이 2개 미만이거나, 스스로 차변==대변이 아닌 분개가 하나라도 있는가.

    존재 여부만 필요하므로 DB에서 EXISTS로 끝낸다 — 분개나 라인을 파이썬으로 끌어오지
    않는다.
    """

    return (
        JournalEntry.objects.filter(contest_id=contest_id)
        .annotate(
            line_count=Count("lines", distinct=True),
            entry_debit_total=Coalesce(
                Sum("lines__amount", filter=Q(lines__side=EntrySide.DEBIT)), 0
            ),
            entry_credit_total=Coalesce(
                Sum("lines__amount", filter=Q(lines__side=EntrySide.CREDIT)), 0
            ),
        )
        .filter(Q(line_count__lt=2) | ~Q(entry_debit_total=F("entry_credit_total")))
        .exists()
    )


def contest_entries(contest_id: UUID):
    """한 Contest에 속한 분개를 등록 순서대로 돌려준다(라인 포함)."""

    return (
        JournalEntry.objects.filter(contest_id=contest_id)
        .prefetch_related("lines")
        .order_by("id")
    )


ACCOUNTS = list(Account.values)
