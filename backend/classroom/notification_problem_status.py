"""강의실 알림 목록에 싣는 「그 문제의 지금 상태」(#1405) — `notifications.ports` 에 올린다.

통과는 참여자의 문제 목록(`list_my_problems`)과 같은 뜻이다: 시도 어느 하나라도 **지금의** 체크리스트
기준으로 통과면 통과다. 받는 사람 자신의 시도만 읽는다 — 알림의 `context` 가 어떤 문제를 가리키든
자기가 낸 적 없는 문제는 답하지 않는다.
"""

from __future__ import annotations

from collections.abc import Collection

from notifications.ports import ProblemStatus

from .current_score import current_score, with_current_score, without_score_prompt
from core.clock import Clock

from .models import ClassroomSubmission, OwnershipTransfer


def problem_statuses_for(user_id: int, problem_ids: Collection[int]) -> dict[int, ProblemStatus]:
    """문제 수와 무관하게 질의 수가 같다."""

    if not problem_ids:
        return {}
    own_submissions = ClassroomSubmission.objects.filter(member__user_id=user_id, problem_id__in=problem_ids)
    submissions = without_score_prompt(with_current_score(own_submissions)).select_related(
        "problem"
    ).prefetch_related("problem__checklist_items")
    by_problem: dict[int, list[ClassroomSubmission]] = {}
    for submission in submissions:
        by_problem.setdefault(submission.problem_id, []).append(submission)
    return {
        problem_id: ProblemStatus(
            passed=any(s.problem.is_score_passed(current_score(s)) for s in own),
            attempt_count=len(own),
        )
        for problem_id, own in by_problem.items()
    }


def transfer_states_for(user_id: int, transfer_ids: Collection[int]) -> dict[int, str]:
    """이 사람 앞으로 온 소유권 이전 요청들의 지금 상태 — 질의 한 번(#1441)."""

    if not transfer_ids:
        return {}
    now = Clock.now()
    return {
        transfer.id: transfer.status_at(now)
        for transfer in OwnershipTransfer.objects.filter(recipient_id=user_id, id__in=transfer_ids)
    }


def classes_with_pending_transfer_for(user_id: int, class_ids: Collection[int]) -> set[int]:
    """이 사람 앞으로 지금 대기 중인 소유권 이전 요청이 있는 클래스들 — 질의 한 번(#1459 ①)."""

    if not class_ids:
        return set()
    now = Clock.now()
    return {
        transfer.classroom_id
        for transfer in OwnershipTransfer.objects.filter(recipient_id=user_id, classroom_id__in=class_ids)
        if transfer.status_at(now) == OwnershipTransfer.Status.PENDING
    }
