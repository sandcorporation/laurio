"""강의실 점수 정정(#1317) — 거는 것과 도는 것이 따로다(공모전 `scoring.corrections` 와 같은 꼴, 코드는 나누지
않는다: 강의실은 공모전 가족을 가리킬 수 없다, ADR-0037·0039).

- **거는 것** — `request_corrections` 가 클래스 소유자(강사)의 요청으로 「진행 중」 행만 만든다. 걸 수 있는지는
  `correctable` 하나가 정한다.
- **도는 것** — grader(ADR-0059)가 진행 중 행을 집어(`next_corrections`·`claim_correction`) 처음 채점과 같은 판정
  길(`scoring.prepare_correction_head` → `scoring.prepare_tail` → 벤더)로 채우고 `finish_correction` 이 결과를
  정정 행에만 쓴다. 원래 시도의 점수·시도 기록·실패 상한·시도 횟수에는 닿지 않는다.

보류·반려·오류는 정정 「실패」로 넘기고 까닭을 `error` 에 둔다. 벤더 쪽 거절(크레딧·빈도 제한·서버 불통·실행기
바쁨)만 「진행 중」으로 두고 `CORRECTION_RETRY_DELAY` 뒤에 다시 집는다 — 공모전 정정이 벤더 거절을 미루는 것과 같다.
비용은 처음 채점처럼 클래스 키의 사용량에 더한다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max, Q

from core.clock import Clock
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterInputTooLargeError,
    LLMAdapterModelRejectedError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    LLMAdapterUnreachableError,
)

from . import agent_grading, scoring
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION

from .current_score import current_of, original_score
from .events import publish_attempt_scored
from .models import ClassroomScoreCorrection, ClassroomSubmission

logger = logging.getLogger(__name__)

#: grader 가 정정 하나를 쥐는 시간 — 에이전트 실행 전체를 덮는다.
CORRECTION_LEASE = agent_grading.AGENT_LEASE
#: 벤더 쪽 거절로 미룬 정정을 다시 집기까지.
CORRECTION_RETRY_DELAY = timedelta(minutes=10)

SKIP_NOT_SCORED = "not_scored"
SKIP_NOT_LATEST = "not_latest"
SKIP_IN_PROGRESS = "in_progress"
SKIP_NOT_PLATFORM_FAILURE = "not_platform_failure"

#: 강사 화면의 「다시 채점」은 사유 칸이 없다 — 범위가 「채점 실패」 점수뿐이라 사유가 하나다.
DEFAULT_REASON = "채점 실패 다시 채점"

#: 미루는(진행 중으로 두는) 벤더 오류 — 제출 탓도 설정 탓도 아니라 기다리면 풀린다.
_DEFERRED_ERRORS = (LLMAdapterQuotaExhaustedError, LLMAdapterRateLimitedError, LLMAdapterUnreachableError)

Status = ClassroomScoreCorrection.Status


class CorrectionReasonRequired(ValueError):
    pass


@dataclass
class CorrectionRequest:
    corrections: list[ClassroomScoreCorrection] = field(default_factory=list)
    #: (시도 id, 까닭) — `SKIP_*`.
    skipped: list[tuple[int, str]] = field(default_factory=list)


def _latest_attempt_ids(submissions: Sequence[ClassroomSubmission]) -> set[int]:
    pairs = {(s.problem_id, s.member_id) for s in submissions}
    if not pairs:
        return set()
    match = Q()
    for problem_id, member_id in pairs:
        match |= Q(problem_id=problem_id, member_id=member_id)
    latest = (
        ClassroomSubmission.objects.filter(match)
        .values("problem_id", "member_id")
        .annotate(latest=Max("attempt_number"))
    )
    by_pair = {(row["problem_id"], row["member_id"]): row["latest"] for row in latest}
    return {s.id for s in submissions if by_pair.get((s.problem_id, s.member_id)) == s.attempt_number}


def correctable(submissions: Sequence[ClassroomSubmission]) -> dict[int, str | None]:
    """정정을 걸 수 있나 — 시도 id → 막는 까닭(`SKIP_*`) 또는 `None`(걸 수 있다). **범위는 이 함수 하나가 정한다.**

    범위(#1317 대표 답): 그 (문제, 학생) 짝의 **가장 최근 시도**이고 현재 점수가 **실패 상한 점수**(「채점 실패」,
    `PLATFORM_FAILURE_MODEL_VERSION`)인 것. 정상 점수는 거절한다 — 정정이 끝나 정상 점수가 되면 다시 걸 수 없다.
    진행 중 정정이 있으면 `in_progress` 다(화면이 버튼을 내린다) — 그래도 동시에 거는 두 요청은 DB 제약이 가른다
    (`request_corrections`)."""

    latest = _latest_attempt_ids(submissions)
    busy = set(
        ClassroomScoreCorrection.objects.filter(
            score__submission__in=[s.id for s in submissions], status=Status.IN_PROGRESS
        ).values_list("score__submission_id", flat=True)
    )
    verdicts: dict[int, str | None] = {}
    for submission in submissions:
        score = original_score(submission)
        if score is None:
            verdicts[submission.id] = SKIP_NOT_SCORED
        elif submission.id not in latest:
            verdicts[submission.id] = SKIP_NOT_LATEST
        elif current_of(score).model_version != PLATFORM_FAILURE_MODEL_VERSION:
            verdicts[submission.id] = SKIP_NOT_PLATFORM_FAILURE
        elif submission.id in busy:
            verdicts[submission.id] = SKIP_IN_PROGRESS
        else:
            verdicts[submission.id] = None
    return verdicts


def request_corrections(
    submissions: Iterable[ClassroomSubmission], *, requested_by, reason: str
) -> CorrectionRequest:
    """정정을 건다 — 걸 수 있는 시도마다 「진행 중」 행 하나. 권한(클래스 소유자)은 부르는 쪽이 본다."""

    reason = (reason or "").strip()
    if not reason:
        raise CorrectionReasonRequired("사유를 적어야 한다.")
    submissions = list(submissions)
    verdicts = correctable(submissions)
    result = CorrectionRequest()
    for submission in submissions:
        blocked = verdicts[submission.id]
        if blocked is not None:
            result.skipped.append((submission.id, blocked))
            continue
        score = original_score(submission)
        assert score is not None
        try:
            with transaction.atomic():
                correction = ClassroomScoreCorrection.objects.create(
                    score=score, reason=reason, requested_by=requested_by
                )
        except IntegrityError:
            result.skipped.append((submission.id, SKIP_IN_PROGRESS))
            continue
        result.corrections.append(correction)
    return result


# --- grader 가 도는 길 ---------------------------------------------------------------------------


def _claimable(as_of: datetime) -> Q:
    return Q(status=Status.IN_PROGRESS) & (Q(lease_until__isnull=True) | Q(lease_until__lt=as_of))


def next_corrections(
    as_of: datetime, *, limit: int, exclude_ids: Iterable[int] = (), exclude_class_ids: Iterable[int] = ()
) -> list[tuple[int, int]]:
    """집을 수 있는 진행 중 정정 — (정정 id, 클래스 id), 먼저 건 것부터."""

    if limit <= 0:
        return []
    rows = (
        ClassroomScoreCorrection.objects.filter(_claimable(as_of))
        .exclude(id__in=list(exclude_ids))
        .exclude(score__submission__problem__classroom_id__in=list(exclude_class_ids))
        .order_by("id")
        .values_list("id", "score__submission__problem__classroom_id")[:limit]
    )
    return list(rows)


def claim_correction(correction_id: int, *, owner: str, as_of: datetime) -> bool:
    """조건부 UPDATE 하나로 집는다 — 둘이 동시에 불러도 한쪽만 `True`."""

    return bool(
        ClassroomScoreCorrection.objects.filter(_claimable(as_of), pk=correction_id).update(
            lease_owner=owner, lease_until=as_of + CORRECTION_LEASE
        )
    )


def prepare_correction(correction_id: int, *, owner: str) -> scoring._Head | dict:
    """준비 앞 절반(DB) — 채점할 수 없으면 정정을 실패로 넘긴 결과(dict)를 돌려준다."""

    submission_id = ClassroomScoreCorrection.objects.values_list("score__submission_id", flat=True).get(pk=correction_id)
    submission = ClassroomSubmission.objects.select_related("problem__classroom", "member").get(pk=submission_id)
    head = scoring.prepare_correction_head(submission, owner=owner)
    if isinstance(head, str):
        return fail_correction(correction_id, owner=owner, error=head)
    return head


def _mine(correction_id: int, owner: str) -> ClassroomScoreCorrection | None:
    return (
        ClassroomScoreCorrection.objects.select_for_update()
        .filter(pk=correction_id, status=Status.IN_PROGRESS, lease_owner=owner)
        .first()
    )


def fail_correction(correction_id: int, *, owner: str, error: str) -> dict:
    with transaction.atomic():
        correction = _mine(correction_id, owner)
        if correction is None:
            return {"correction_id": correction_id, "status": "lease_lost"}
        correction.status = Status.FAILED
        correction.error = error[:4000]
        correction.finished_at = Clock.now()
        correction.lease_owner = ""
        correction.lease_until = None
        correction.save()
    logger.info("강의실 정정 %s 실패: %s", correction_id, error)
    return {"correction_id": correction_id, "status": "failed", "error": error}


def _defer(correction_id: int, *, owner: str, error: str) -> dict:
    with transaction.atomic():
        correction = _mine(correction_id, owner)
        if correction is None:
            return {"correction_id": correction_id, "status": "lease_lost"}
        correction.lease_owner = ""
        correction.lease_until = Clock.now() + CORRECTION_RETRY_DELAY
        correction.save(update_fields=["lease_owner", "lease_until"])
    logger.warning("강의실 정정 %s 미룸: %s", correction_id, error)
    return {"correction_id": correction_id, "status": "deferred", "error": error}


def _error_text(exc: Exception) -> str:
    if isinstance(exc, LLMAdapterAuthError):
        return f"클래스 채점 키가 거부됐다: {exc}"
    if isinstance(exc, LLMAdapterModelRejectedError):
        return f"클래스 키가 이 채점 모델을 거부했다: {exc}"
    if isinstance(exc, LLMAdapterInputTooLargeError):
        return f"반려 — 요청이 모델 컨텍스트를 넘었다: {exc}"
    return f"{type(exc).__name__}: {exc}"


def finish_correction(
    correction_id: int,
    prepared: scoring.PreparedScoring | scoring.Concluded,
    outcome: scoring.VendorOutcome | None,
    *,
    owner: str,
) -> dict:
    """결과를 정정 행에만 쓴다(DB) — 준비가 벤더 없이 끝났으면(`Concluded`) 그 까닭으로 실패다."""

    if isinstance(prepared, scoring.Concluded):
        return fail_correction(correction_id, owner=owner, error=prepared.reason or "채점 준비에서 끝났다")
    assert outcome is not None
    if outcome.error is not None:
        if isinstance(outcome.error, _DEFERRED_ERRORS):
            return _defer(correction_id, owner=owner, error=str(outcome.error))
        return fail_correction(correction_id, owner=owner, error=_error_text(outcome.error))
    if isinstance(outcome.agent, agent_grading.AgentHeld):
        return fail_correction(correction_id, owner=owner, error=f"보류 — {agent_grading.held_message(outcome.agent)}")
    output = outcome.output
    assert output is not None
    if outcome.second_step is not None:
        prepared = outcome.second_step
    with transaction.atomic():
        correction = _mine(correction_id, owner)
        if correction is None:
            return {"correction_id": correction_id, "status": "lease_lost"}
        scoring._charge_vendor_usage(prepared, outcome, output)
        correction.status = Status.DONE
        correction.model_version = output.model_version
        correction.prompt = prepared.prompt
        correction.reasoning = scoring.outcome_reasoning(prepared, output)
        correction.syntax_check_result = prepared.syntax_check.resolve(output.verdicts)
        correction.unseen_files = prepared.unseen_files
        correction.finished_at = Clock.now()
        correction.lease_owner = ""
        correction.lease_until = None
        correction.save()
        # 처음 채점과 같은 신호 — 강사 「최근 제출」·「제출」 화면과 학생 결과가 새로고침 없이 다시 읽는다(커밋 뒤 발행).
        publish_attempt_scored(correction.score.submission)
    return {"correction_id": correction_id, "status": "done"}


def run_correction_inline(correction_id: int) -> dict | None:
    """한 정정을 이 자리에서 동기로 돈다(수동 점검·시험) — grader 의 걸음과 같은 함수, 벤더만 동기 길이다."""

    owner = f"inline-{correction_id}"
    if not claim_correction(correction_id, owner=owner, as_of=Clock.now()):
        return None
    try:
        head = prepare_correction(correction_id, owner=owner)
        if isinstance(head, dict):
            return head
        prepared = scoring.prepare_tail(head)
        outcome = None if isinstance(prepared, scoring.Concluded) else scoring.call_vendor_sync(prepared, reuse=False)
        return finish_correction(correction_id, prepared, outcome, owner=owner)
    except Exception as exc:  # noqa: BLE001 - 정정 하나의 실패가 grader 를 막으면 안 된다.
        logger.exception("강의실 정정 %s 예외", correction_id)
        return fail_correction(correction_id, owner=owner, error=f"{type(exc).__name__}: {exc}")
