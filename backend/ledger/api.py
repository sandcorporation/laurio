"""운영자 전용 원장 API.

이 티켓의 유일한 사용자 대면 표면이다. 아직 `Contest` 모델(#8)도 인증(#5)도 없으므로:

- `contest_id`는 불투명 UUID로만 받는다. #8이 실제 FK로 바꾼다.
- 운영자 여부는 `request.user.is_staff`로만 확인한다. #5가 이 자리를 대체할 것이므로
  더 정교한 권한 체계를 여기서 만들지 않는다.
"""

from __future__ import annotations

from uuid import UUID

from ninja import Router
from ninja.utils import check_csrf

from ledger.models import JournalEntry
from ledger.schemas import (
    ContestBalanceOut,
    ErrorOut,
    JournalEntryIn,
    JournalEntryOut,
)
from ledger.services import (
    CrossContestReversalError,
    DuplicateReversalError,
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


def _csrf_rejected(request) -> tuple[int, dict] | None:
    """세션 쿠키로 인증된 쓰기 요청에 CSRF 토큰을 강제한다.

    django-ninja는 자신이 마운트하는 모든 뷰를 Django 미들웨어 레벨에서
    `csrf_exempt`로 표시한다(`ninja.operation.PathView.get_view`) — 즉 CSRF 방어는
    `django_auth` 계열의 쿠키 인증을 쓸 때만 알아서 켜지고, `request.user.is_staff`로
    직접 게이트하는 이 라우터에서는 아무 데서도 CSRF를 검사하지 않는다. 그 상태로는
    운영자가 /admin에 로그인해 있는 동안 악성 페이지를 열기만 해도 세션 쿠키가 자동
    전송되어 분개가 위조될 수 있다 — append-only 원장에 영구히 남는다. 그래서 쓰기
    엔드포인트에서 직접 `ninja.utils.check_csrf`로 검증한다(안전 메서드 GET은
    CsrfViewMiddleware도 애초에 검사하지 않으므로 대상이 아니다).
    """

    error = check_csrf(request)
    if error is not None:
        return 403, {"detail": "CSRF 검증에 실패했다."}
    return None


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

    csrf_error = _csrf_rejected(request)
    if csrf_error is not None:
        return csrf_error

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
    except CrossContestReversalError as exc:
        return 400, {"detail": str(exc)}
    except DuplicateReversalError as exc:
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

    result = contest_balance(contest_id)
    return 200, {
        "contest_id": contest_id,
        "balance": result["balance"],
        "is_balanced": result["is_balanced"],
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
