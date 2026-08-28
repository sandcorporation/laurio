"""운영자 전용 원장 API.

이 티켓의 유일한 사용자 대면 표면이다. 아직 `Contest` 모델(#8)도 인증(#5)도 없으므로:

- `contest_id`는 불투명 UUID로만 받는다. #8이 실제 FK로 바꾼다.
- 운영자 여부는 `request.user.is_staff`로만 확인한다. #5가 이 자리를 대체할 것이므로
  더 정교한 권한 체계를 여기서 만들지 않는다.
"""

from __future__ import annotations

from uuid import UUID

from ninja import Router

from ledger.models import JournalEntry
from ledger.schemas import (
    ContestBalanceOut,
    ErrorOut,
    JournalEntryIn,
    JournalEntryOut,
)
from ledger.services import (
    LineInput,
    UnbalancedEntryError,
    UnknownReversalTargetError,
    contest_balance,
    contest_entries,
    post_journal_entry,
)

router = Router(tags=["ledger"])


def _is_operator(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff)


def _forbidden() -> tuple[int, dict]:
    return 403, {"detail": "운영자만 접근할 수 있다."}


def _entry_to_dict(entry: JournalEntry) -> dict:
    return {
        "id": entry.id,
        "contest_id": entry.contest_id,
        "memo": entry.memo,
        "reverses_id": entry.reverses_id,
        "created_at": entry.created_at,
        "lines": [
            {"account": line.account, "side": line.side, "amount": line.amount}
            for line in entry.lines.all()
        ],
    }


@router.post("/entries", response={201: JournalEntryOut, 400: ErrorOut, 403: ErrorOut})
def create_entry(request, payload: JournalEntryIn):
    """분개 하나를 등록한다. 차변 합 != 대변 합이면 400이고 아무 것도 저장되지 않는다."""

    if not _is_operator(request):
        return _forbidden()

    lines = [
        LineInput(account=line.account.value, side=line.side.value, amount=line.amount)
        for line in payload.lines
    ]

    try:
        entry = post_journal_entry(
            contest_id=payload.contest_id,
            lines=lines,
            memo=payload.memo,
            reverses_id=payload.reverses_id,
        )
    except UnbalancedEntryError as exc:
        return 400, {"detail": str(exc)}
    except UnknownReversalTargetError as exc:
        return 400, {"detail": str(exc)}

    return 201, _entry_to_dict(entry)


@router.get(
    "/contests/{contest_id}/balance",
    response={200: ContestBalanceOut, 403: ErrorOut},
)
def get_contest_balance(request, contest_id: UUID):
    """한 Contest의 원장 합계가 0인지 운영자가 확인한다."""

    if not _is_operator(request):
        return _forbidden()

    balance = contest_balance(contest_id)
    return 200, {
        "contest_id": contest_id,
        "balance": balance,
        "is_balanced": balance == 0,
    }


@router.get(
    "/contests/{contest_id}/entries",
    response={200: list[JournalEntryOut], 403: ErrorOut},
)
def list_contest_entries(request, contest_id: UUID):
    """한 Contest에 쌓인 분개를 등록 순서대로 돌려준다 — append-only 감사용."""

    if not _is_operator(request):
        return _forbidden()

    entries = contest_entries(contest_id)
    return 200, [_entry_to_dict(entry) for entry in entries]
