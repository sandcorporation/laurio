"""공모전 판정이 묻는 이의 사실 — `appeals.apps` 가 `contests.ports` 에 올린다(#1102)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Appeal

if TYPE_CHECKING:
    from contests.models import ContestSubmission
    from contests.ports import AppealState

#: 「다음 행동」·점수 화면이 당길 관계
RELATIONS = ("appeal",)


def appeal_state(submission: ContestSubmission) -> AppealState:
    appeal = getattr(submission, "appeal", None)
    if appeal is None:
        return "none"
    return "pending" if appeal.status == Appeal.Status.PENDING else "ruled"
