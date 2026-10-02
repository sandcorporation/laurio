"""「공모전에도 내기」의 강의실 쪽 (#549, 스펙 #546, ADR-0054, CONTEXT.md 「공모전에도 내기」).

참여자가 공모전 문제에 시도를 내면서 스위치를 켜면, 그 시도가 그 공모전의 내 제출이 된다.
강의실은 공모전 앱을 임포트하지 못하므로(ADR-0037) 공유층 `core.contest_catalog` 로만 건넌다.

1. **시도를 만들기 전** — `prepare_contest_entry` 가 거른다: 강사 자신의 시도·공모전 문제가
   아님·받지 않는 공모전은 여기서, 동의·근거 모양·선택 자료는 카탈로그의 `check_entry`
   로(직접 제출과 같은 문장) 422. 이미 낸 제출이 있는데 「이 시도로 바뀝니다」를 확인하지 않았으면 409.
2. **시도가 커밋된 뒤** — `contest_entry_requested` 를 보낸다. 시도는 「내는 중」으로 남는다.
3. **결과** — 공모전 쪽이 `contest_entry_resolved` 로 답하면 `on_contest_entry_resolved` 가
   그 시도에 「냈다」/「내지 못했다(사유)」를 남기고, 받지 못했으면 낸 사람에게 알린다.
   클래스 시도·판정은 어느 쪽이든 그대로다.

끄고 낸 시도는 아무것도 보내지 않는다 — 공모전 제출을 건드리지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from django.db import transaction
from ninja.errors import HttpError

from core.clock import Clock
from core.contest_catalog import (
    ContestEntry,
    EntryAsset,
    EntryEvidence,
    EntryResponse,
    contest_catalog,
    contest_entry_requested,
)
from notifications.models import NotificationType
from notifications.services import notify_safely

from .contest_problems import is_contest_problem
from .models import ClassroomSubmission, Problem
from .schemas import (
    ContestEntryAssetOut,
    ContestEntryEvidenceOut,
    ContestEntryFormOut,
    ContestEntryIn,
    ContestEntryRequirementOut,
    ContestEntryResponseOut,
)

logger = logging.getLogger(__name__)

INSTRUCTOR_ENTRY_MESSAGE = "강사 자신의 시도는 공모전에 낼 수 없습니다."
NOT_CONTEST_PROBLEM_MESSAGE = "공모전 문제가 아니라 공모전에 낼 수 없습니다."
NOT_ACCEPTING_MESSAGE = "이 공모전은 지금 출품을 받지 않습니다 — 마감됐거나 개최자가 허용을 거뒀습니다."
REPLACE_CONFIRM_MESSAGE = (
    "이미 이 공모전에 낸 제출이 있습니다 — 이 시도로 바뀝니다. 확인한 뒤 다시 내 주세요."
)
NO_ANSWER_MESSAGE = "공모전에 내지 못했습니다 — 잠시 뒤 다시 내 주세요."


def _required(grade: str) -> bool:
    return grade == "required"


def contest_entry_form(problem: Problem, user_id: int) -> ContestEntryFormOut:
    """참여자의 「공모전에도 내기」 칸. 직전 공모전 제출이 있으면 그 응답·선택 자료를 미리
    채운다 — 요구사항이 그사이 바뀌었으면 새 항목만 빈칸이다(요구사항 번호로 짝짓는다)."""

    source = contest_catalog().get_source(problem.contest_id)
    context = (
        contest_catalog().entry_context(problem.contest_id, user_id)
        if source is not None and source.accepts_classroom_entries
        else None
    )
    if source is None or context is None:
        return ContestEntryFormOut(contest_id=problem.contest_id, accepts_entries=False)

    previous = {r.requirement_id: r for r in context.responses}
    requirements = []
    for requirement in sorted(source.requirements, key=lambda r: (r.order, r.requirement_id)):
        response = previous.get(requirement.requirement_id)
        requirements.append(
            ContestEntryRequirementOut(
                requirement_id=requirement.requirement_id,
                text=requirement.text,
                required=_required(requirement.grade),
                previous=(
                    ContestEntryResponseOut(
                        is_met=response.is_met,
                        note=response.note,
                        evidence=[
                            ContestEntryEvidenceOut(kind=e.kind, value=e.value)
                            for e in response.evidence
                        ],
                    )
                    if response is not None
                    else None
                ),
            )
        )
    return ContestEntryFormOut(
        contest_id=source.contest_id,
        accepts_entries=True,
        deadline_at=source.deadline_at,
        has_entry=context.has_entry,
        requirements=requirements,
        optional_assets=[
            ContestEntryAssetOut(
                kind=a.kind, value=a.value, label=a.label, content_type=a.content_type
            )
            for a in context.optional_assets
        ],
        upload_target_refs=dict(context.upload_target_refs),
    )


def prepare_contest_entry(
    *,
    problem: Problem,
    user_id: int,
    entry_in: ContestEntryIn | None,
    scoring_asset: EntryAsset,
    as_instructor: bool,
) -> ContestEntry | None:
    """시도를 만들기 전에 내기를 거른다. 끄고 낸 시도면 None. `attempt_id` 는 아직 0 이다 —
    시도가 생긴 뒤 `request_contest_entry` 가 채운다."""

    if entry_in is None:
        return None
    if as_instructor:
        raise HttpError(422, INSTRUCTOR_ENTRY_MESSAGE)
    if not is_contest_problem(problem):
        raise HttpError(422, NOT_CONTEST_PROBLEM_MESSAGE)
    source = contest_catalog().get_source(problem.contest_id)
    if source is None or not source.accepts_classroom_entries:
        raise HttpError(422, NOT_ACCEPTING_MESSAGE)

    entry = ContestEntry(
        contest_id=problem.contest_id,
        user_id=user_id,
        attempt_id=0,
        scoring_asset=scoring_asset,
        responses=tuple(
            EntryResponse(
                requirement_id=r.requirement_id,
                is_met=r.is_met,
                note=r.note,
                evidence=tuple(EntryEvidence(kind=e.kind, value=e.value) for e in r.evidence),
            )
            for r in entry_in.requirement_responses
        ),
        optional_assets=tuple(
            EntryAsset(kind=a.kind, value=a.value, label=a.label, content_type=a.content_type)
            for a in entry_in.optional_assets
        ),
        source_access_consent=entry_in.source_access_consent,
    )
    # 동의·근거 모양·선택 자료는 공모전 쪽이 직접 제출과 같은 문장으로 답한다.
    reason = contest_catalog().check_entry(entry)
    if reason is not None:
        raise HttpError(422, reason)

    context = contest_catalog().entry_context(problem.contest_id, user_id)
    if context is not None and context.has_entry and not entry_in.replace_existing:
        raise HttpError(409, REPLACE_CONFIRM_MESSAGE)
    return entry


def request_contest_entry(submission: ClassroomSubmission, entry: ContestEntry) -> None:
    """시도 트랜잭션 안에서 부른다 — 시도를 「내는 중」으로 두고, 커밋된 뒤 공모전에 보낸다."""

    submission.contest_entry_status = ClassroomSubmission.ContestEntryStatus.PENDING
    submission.save(update_fields=["contest_entry_status"])
    bound = replace(entry, attempt_id=submission.id)
    transaction.on_commit(lambda: _send(bound))


def _send(entry: ContestEntry) -> None:
    responses = contest_entry_requested.send_robust(sender=ClassroomSubmission, entry=entry)
    for _receiver, response in responses:
        if isinstance(response, Exception):
            logger.error(
                "공모전에도 내기 신호 처리 중 예외(attempt=%s)",
                entry.attempt_id,
                exc_info=response,
            )
    # 아무도 답하지 않았으면(공모전 앱이 없는 구성·수신자 예외) 「내지 못했다」로 닫는다 —
    # 「내는 중」으로 영원히 남기지 않는다.
    still_pending = ClassroomSubmission.objects.filter(
        pk=entry.attempt_id, contest_entry_status=ClassroomSubmission.ContestEntryStatus.PENDING
    ).exists()
    if still_pending:
        _resolve(entry.attempt_id, accepted=False, reason=NO_ANSWER_MESSAGE)


def on_contest_entry_resolved(sender, attempt_id: int, accepted: bool, reason: str = "", **kwargs) -> None:
    """공유층 결과 신호 수신자."""

    _resolve(attempt_id, accepted=accepted, reason=reason)


def _resolve(attempt_id: int, *, accepted: bool, reason: str) -> None:
    status = (
        ClassroomSubmission.ContestEntryStatus.ENTERED
        if accepted
        else ClassroomSubmission.ContestEntryStatus.REJECTED
    )
    updated = ClassroomSubmission.objects.filter(
        pk=attempt_id, contest_entry_status=ClassroomSubmission.ContestEntryStatus.PENDING
    ).update(
        contest_entry_status=status,
        contest_entry_reason="" if accepted else reason[:300],
        contest_entry_resolved_at=Clock.now(),
    )
    if not updated or accepted:
        return
    submission = (
        ClassroomSubmission.objects.select_related("problem__classroom", "member__user")
        .filter(pk=attempt_id)
        .first()
    )
    if submission is None:
        return
    problem = submission.problem
    notify_safely(
        recipient=submission.member.user,
        notification_type=NotificationType.CLASSROOM_CONTEST_ENTRY_REJECTED,
        context={
            "class_id": problem.classroom.id,
            "class_name": problem.classroom.name,
            "problem_id": problem.id,
            "problem_title": problem.title,
            "submission_id": submission.id,
            "attempt_number": submission.attempt_number,
            "reason": reason[:300],
        },
    )


def contest_entry_out(submission: ClassroomSubmission) -> dict | None:
    if not submission.contest_entry_status:
        return None
    return {"status": submission.contest_entry_status, "reason": submission.contest_entry_reason}
