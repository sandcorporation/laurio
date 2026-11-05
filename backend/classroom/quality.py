"""강의실 완성도 채점(#883, ADR-0072) — 대상 시도·재사용·비용·큐·순위.

계산과 프롬프트 틀은 `core.quality_review` 가 들고 있고(공모전과 같은 함수), 여기는 강의실의 몫이다:

- **대상**: 문제마다 참여자(강사·공동 강사·내보낸 사람 제외 — 달성률과 같은 명단)별 **가장 최근 통과
  시도** 하나. 통과는 `Problem.is_score_passed` 를 지금 체크리스트로 다시 센다.
- **재사용**: 대상 시도에 같은 체크리스트 지문의 기록이 있으면 그것을 쓴다. 시도가 바뀌었거나
  체크리스트를 고쳤으면 다시 매긴다.
- **큐**: 판정 채점과 같은 grader(ADR-0059)가 임대로 집는다. 큐 칸은 `ClassroomQualityJob` 에 따로 둔다.
  실패하면 그 시도만 「완성도 채점 실패」로 남고, 강사가 다시 누를 때 큐에 다시 들어간다.
- **비용·모델·사용량**은 그 클래스의 채점 연결(강사 키)을 탄다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from django.conf import settings
from django.db import OperationalError, models, transaction

from core.clock import Clock
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterModelRejectedError,
    LLMAdapterPermanentError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterUnreachableError,
)
from core.observability import tag_error_scope
from core.quality_review import (
    QUALITY_SCORE_MAX,
    QUALITY_SCORE_MIN,
    BonusScore,
    QualityInput,
    QualityItemInput,
    QualityItemView,
    QualityOutput,
    QualityReviewAdapter,
    build_prompt,
    checklist_fingerprint,
    competition_ranks,
    historical_columns,
    quality_total,
    quality_view,
    records,
)
from submissions.models import SubmissionAsset

from . import pending_scoring, scoring, scoring_cost
from .grading_guidelines import effective_grading_guideline_text
from .instructors import active_participant_q
from .models import (
    ChecklistGrade,
    ChecklistItem,
    Class,
    ClassMember,
    ClassroomBonusScore,
    ClassroomQualityJob,
    ClassroomQualityReview,
    ClassroomSubmission,
    Problem,
)
from .scoring_connection import ScoringConnection, connection_for, mark_verified

logger = logging.getLogger(__name__)

#: 판정 채점과 같은 임대 길이(벤더 180초 + 여유 60초).
QUALITY_LEASE = scoring.SCORING_LEASE

#: 큐에서 꺼냈지만 채점할 수 없을 때 남기는 문구 — 버튼 단계와 같은 말이다.
BLOCKED_MESSAGES = {
    pending_scoring.NO_API_KEY: "채점 연결이 없거나 키를 쓸 수 없어 채점할 수 없습니다.",
    pending_scoring.MODEL_REJECTED: "이 문제의 채점 모델을 그 키로 쓸 수 없어 채점할 수 없습니다.",
}


# --- 대상과 재사용 -------------------------------------------------------------------------


def checklist_inputs(items: list[ChecklistItem]) -> list[QualityItemInput]:
    """AI 가 매기는 항목 — 가산은 강사가 매기므로 뺀다(ADR-0073). 지문도 이것으로 센다."""

    return [
        QualityItemInput(item_id=i.id, label=i.label, required=i.required, points=i.points)
        for i in items
        if i.grade != ChecklistGrade.BONUS
    ]


def points_of(items: list[ChecklistItem]) -> dict[int, int]:
    """지금 체크리스트의 항목 id → 배점(가산 포함) — 완성도는 읽을 때 이것으로 합한다(ADR-0073)."""

    return {i.id: i.points for i in items}


@dataclass(frozen=True)
class TargetState:
    submission: ClassroomSubmission
    #: 지금의 기록(같은 시도 + 같은 지문). 없으면 아직 매기지 않았다.
    review: ClassroomQualityReview | None
    queued: bool
    failed: bool


@dataclass(frozen=True)
class Board:
    problem: Problem
    items: list[ChecklistItem]
    fingerprint: str
    targets: list[TargetState]
    #: 대상 시도 id → 지금 가산 항목마다의 강사 점수(#905). 매기지 않은 가산은 0점·`rated=False`.
    bonus: dict[int, list[BonusScore]]
    #: 「가산 다시 매김 필요」 — 지난 대상 시도에 가산 점수가 있었는데 지금 대상 시도에는 하나도 없는 시도 id.
    rerate_needed: frozenset[int]

    @property
    def new_targets(self) -> list[TargetState]:
        """버튼을 누르면 새로 큐에 들어갈 시도 — 지금의 기록이 없고 큐에도 없는 것."""

        return [t for t in self.targets if t.review is None and not t.queued]

    @property
    def reviewed(self) -> list[TargetState]:
        return [t for t in self.targets if t.review is not None]


def _target_submissions(problem: Problem, items: list[ChecklistItem]) -> list[ClassroomSubmission]:
    attempts = (
        ClassroomSubmission.objects.filter(problem=problem)
        .filter(active_participant_q(member="member", classroom="problem__classroom"))
        .select_related("classroom_score", "member")
        .order_by("member_id", "-attempt_number")
    )
    latest_passed: dict[int, ClassroomSubmission] = {}
    for attempt in attempts:
        if attempt.member_id in latest_passed:
            continue
        if problem.is_score_passed(getattr(attempt, "classroom_score", None), checklist_items=items):
            latest_passed[attempt.member_id] = attempt
    return list(latest_passed.values())


def board(problem: Problem) -> Board:
    items = list(problem.checklist_items.all())
    fingerprint = checklist_fingerprint(checklist_inputs(items))
    submissions = _target_submissions(problem, items) if items else []
    ids = [s.id for s in submissions]
    reviews: dict[int, ClassroomQualityReview] = {}
    for review in ClassroomQualityReview.objects.filter(
        submission_id__in=ids, checklist_fingerprint=fingerprint
    ).order_by("-created_at", "-id"):
        reviews.setdefault(review.submission_id, review)
    jobs = {j.submission_id: j for j in ClassroomQualityJob.objects.filter(submission_id__in=ids)}
    targets = []
    for s in submissions:
        job = jobs.get(s.id)
        review = reviews.get(s.id)
        targets.append(
            TargetState(
                submission=s,
                review=review,
                queued=job is not None and job.queued_at is not None,
                failed=review is None and job is not None and job.queued_at is None and job.failed_at is not None,
            )
        )
    bonus, rerate_needed = _bonus_state(problem, items, submissions)
    return Board(
        problem=problem,
        items=items,
        fingerprint=fingerprint,
        targets=targets,
        bonus=bonus,
        rerate_needed=rerate_needed,
    )


def _bonus_state(
    problem: Problem, items: list[ChecklistItem], submissions: list[ClassroomSubmission]
) -> tuple[dict[int, list[BonusScore]], frozenset[int]]:
    """대상 시도마다 지금 가산 항목의 점수, 그리고 「가산 다시 매김 필요」 시도(#905, ADR-0073).

    가산 점수는 시도에 붙는다. 강사는 대상 시도에만 매기므로(`save_bonus_score`) 다른 시도에 남은 점수는 곧
    「지난 대상 시도의 점수」다 — 그런 점수가 있는데 지금 대상 시도엔 하나도 없으면 다시 매겨야 한다."""

    bonus_items = [i for i in items if i.grade == ChecklistGrade.BONUS]
    if not bonus_items or not submissions:
        return {s.id: [BonusScore(item_id=i.id, label=i.label) for i in bonus_items] for s in submissions}, frozenset()
    target_ids = {s.id for s in submissions}
    rows = list(
        ClassroomBonusScore.objects.filter(
            item__in=bonus_items, submission__member_id__in=[s.member_id for s in submissions]
        ).values_list("submission_id", "submission__member_id", "item_id", "score", "memo")
    )
    stored = {(sid, item_id): (score, memo) for sid, _member, item_id, score, memo in rows if sid in target_ids}
    members_with_past = {member for sid, member, *_ in rows if sid not in target_ids}
    rated_targets = {sid for sid, *_ in rows if sid in target_ids}
    bonus: dict[int, list[BonusScore]] = {}
    for s in submissions:
        scores = []
        for i in bonus_items:
            found = stored.get((s.id, i.id))
            scores.append(
                BonusScore(item_id=i.id, label=i.label)
                if found is None
                else BonusScore(item_id=i.id, label=i.label, score=found[0], memo=found[1], rated=True)
            )
        bonus[s.id] = scores
    rerate = frozenset(s.id for s in submissions if s.member_id in members_with_past and s.id not in rated_targets)
    return bonus, rerate


class BonusTargetError(ValueError):
    """가산을 매길 수 없는 자리 — 가산 항목이 아니거나 지금 완성도 대상 시도가 아니다."""


def save_bonus_score(
    problem: Problem, *, submission_id: int, item_id: int, score: int, memo: str, rated_by_id: int
) -> ClassroomBonusScore:
    """강사·공동 강사가 가산 하나를 매긴다(#905) — **그 참여자의 지금 완성도 대상 시도**에만. 덮어쓰기다."""

    if not QUALITY_SCORE_MIN <= score <= QUALITY_SCORE_MAX:
        raise BonusTargetError("가산은 0~5 로 매깁니다.")
    item = problem.checklist_items.filter(id=item_id, grade=ChecklistGrade.BONUS).first()
    if item is None:
        raise BonusTargetError("가산 항목을 찾을 수 없습니다.")
    items = list(problem.checklist_items.all())
    if submission_id not in {s.id for s in _target_submissions(problem, items)}:
        raise BonusTargetError("완성도 대상 시도에만 가산을 매길 수 있습니다.")
    row, _ = ClassroomBonusScore.objects.update_or_create(
        submission_id=submission_id,
        item=item,
        defaults={"score": score, "memo": memo.strip(), "rated_by_id": rated_by_id, "rated_at": Clock.now()},
    )
    return row


# --- 비용 ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Estimate:
    new_count: int
    reuse_count: int
    #: 단가표에 없는 모델이면 `None`(「단가 모름」).
    cost_krw: float | None
    blocked_reason: str | None


def _effort(connection: ScoringConnection | None, problem: Problem) -> str | None:
    model = problem.effective_model()
    if connection is None:
        return None
    if not connection.sends_reasoning_effort(model, marked_reasoning=problem.effective_model_marked_reasoning()):
        return None
    return problem.effective_reasoning_effort()


def _base_prompt(problem: Problem, items: list[ChecklistItem]) -> str:
    return build_prompt(
        title=problem.title,
        description=problem.description,
        guideline_text=effective_grading_guideline_text(problem.grading_strictness, problem.grading_guideline_text),
        items=checklist_inputs(items),
        submission_text="",
    )


def estimate(problem: Problem) -> Estimate:
    """「새로 채점할 n명 · 예상 비용」. 비용은 `scoring_cost.attempt_cost` 를 쓰되 완성도 프롬프트 길이로
    센다 — 소스를 다시 읽지 않으려고 소스 몫은 그 시도의 판정 프롬프트 길이(같은 소스가 실렸다)로
    어림한다(약간 크게 나온다)."""

    current = board(problem)
    new = current.new_targets
    class_obj = problem.classroom
    connection = connection_for(class_obj)
    model = problem.effective_model()
    effort = _effort(connection, problem)
    base_chars = len(_base_prompt(problem, current.items))
    total = 0.0
    priced = True
    for target in new:
        score = getattr(target.submission, "classroom_score", None)
        chars = base_chars + (len(score.prompt) if score is not None else 0)
        cost = scoring_cost.attempt_cost(model, effort, prompt_chars=chars)
        if cost is None:
            priced = False
            break
        total += cost.usd * scoring_cost.KRW_PER_USD
    return Estimate(
        new_count=len(new),
        reuse_count=len(current.reviewed),
        cost_krw=total if priced else None,
        blocked_reason=pending_scoring.blocking_reason(class_obj, problem),
    )


def enqueue(problem: Problem, *, as_of) -> int:
    """새로 매길 시도를 큐에 넣는다. 넣은 건수를 돌려준다. 이미 큐에 있는 것은 건드리지 않는다."""

    queued_ids: list[int] = []
    for target in board(problem).new_targets:
        sid = target.submission.id
        ClassroomQualityJob.objects.get_or_create(submission_id=sid)
        if ClassroomQualityJob.objects.filter(submission_id=sid, queued_at__isnull=True).update(
            queued_at=as_of, failed_at=None, error=""
        ):
            queued_ids.append(sid)
    if settings.CLASSROOM_GRADER_INLINE:
        for sid in queued_ids:
            grade_inline(sid)
    return len(queued_ids)


# --- 순위 ---------------------------------------------------------------------------------


class RankRow(TypedDict):
    rank: int
    member_id: int
    display_name: str
    submission_id: int
    attempt_number: int
    total: float
    max_total: int
    raw_total: int
    completeness: float
    weighted_score: int
    max_weighted_score: int
    items: list[QualityItemView]
    #: 「가산 다시 매김 필요」(#905) — 강사 화면 몫. 참여자 응답에는 싣지 않는다.
    bonus_needs_rerate: bool


def ranking(current: Board) -> list[RankRow]:
    """지금의 기록이 있는 대상만 — 지금 배점으로 합한 정수 Σ(0~5 × 배점)으로 줄 세우고 같으면 같은
    등수(1, 2, 2, 4). 저장 칸(`weighted_score` 등)은 역사값이라 읽지 않는다(ADR-0073)."""

    points = points_of(current.items)
    reviewed = [
        (t.submission, quality_view(t.review.items, points, current.bonus.get(t.submission.id, ())))
        for t in current.reviewed
        if t.review is not None
    ]
    ranks = competition_ranks([view["raw_total"] for _, view in reviewed])
    rows = [
        RankRow(
            rank=rank,
            member_id=s.member_id,
            display_name=s.member.display_name,
            submission_id=s.id,
            attempt_number=s.attempt_number,
            bonus_needs_rerate=s.id in current.rerate_needed,
            **view,
        )
        for rank, (s, view) in zip(ranks, reviewed, strict=True)
    ]
    rows.sort(key=lambda row: (row["rank"], row["display_name"], row["submission_id"]))
    return rows


def my_row(current: Board, member: ClassMember) -> tuple[RankRow, int] | None:
    """참여자 본인의 줄과 순위에 든 사람 수 — 다른 사람의 이름·점수는 돌려주지 않는다."""

    rows = ranking(current)
    mine = next((row for row in rows if row["member_id"] == member.id), None)
    if mine is None:
        return None
    return mine, len(rows)


# --- 큐와 임대 -----------------------------------------------------------------------------


def next_candidates(
    as_of, *, limit: int, exclude_class_ids: list[int] | None = None, exclude_ids: set[int] | None = None
) -> list[tuple[int, int]]:
    """grader 가 지금 집을 수 있는 완성도 작업 `(시도 id, 클래스 id)` — 큐에 넣은 순서."""

    if limit <= 0:
        return []
    rows = (
        ClassroomQualityJob.objects.filter(queued_at__isnull=False)
        .filter(models.Q(lease_until__isnull=True) | models.Q(lease_until__lte=as_of))
        .exclude(submission__problem__classroom_id__in=exclude_class_ids or [])
        .exclude(submission_id__in=exclude_ids or ())
        .order_by("queued_at", "id")
        .values_list("submission_id", "submission__problem__classroom_id")[:limit]
    )
    return list(rows)


def claim(submission_id: int, *, owner: str, as_of) -> bool:
    """임대를 찍는다 — 판정의 `scoring.claim_attempt` 와 같은 모양(잠긴 행은 건너뛴다)."""

    with transaction.atomic():
        row = (
            ClassroomQualityJob.objects.select_for_update(skip_locked=True)
            .filter(submission_id=submission_id, queued_at__isnull=False)
            .filter(models.Q(lease_until__isnull=True) | models.Q(lease_until__lte=as_of))
            .values_list("pk", flat=True)
            .first()
        )
        if row is None:
            return False
        ClassroomQualityJob.objects.filter(pk=row).update(lease_owner=owner, lease_until=as_of + QUALITY_LEASE)
    return True


def extend_lease(submission_id: int, *, owner: str, as_of) -> bool:
    try:
        with transaction.atomic():
            scoring._short_lock_timeout()
            return (
                ClassroomQualityJob.objects.filter(submission_id=submission_id, lease_owner=owner).update(
                    lease_until=as_of + QUALITY_LEASE
                )
                == 1
            )
    except OperationalError as exc:
        if scoring.is_lock_timeout(exc):
            return False
        raise


@dataclass(frozen=True)
class QualityConcluded:
    """벤더를 부를 일 없이 끝난 작업 — `apply` 가 임대를 확인한 트랜잭션 안에서 결과를 쓴다."""

    apply: Callable[[], dict]


@dataclass(frozen=True)
class QualityHead:
    submission: ClassroomSubmission
    owner: str
    class_obj: Class
    problem: Problem
    items: list[ChecklistItem]
    fingerprint: str
    connection: ScoringConnection
    asset: SubmissionAsset


@dataclass(frozen=True)
class PreparedQuality:
    submission: ClassroomSubmission
    owner: str
    class_obj: Class
    problem: Problem
    fingerprint: str
    connection: ScoringConnection
    model: str
    reasoning_effort: str | None
    prompt: str
    quality_input: QualityInput


@dataclass(frozen=True)
class QualityOutcome:
    output: QualityOutput | None = None
    error: LLMAdapterError | None = None


def _fail(submission_id: int, message: str) -> Callable[[], dict]:
    def _apply() -> dict:
        ClassroomQualityJob.objects.filter(submission_id=submission_id).update(
            failed_at=Clock.now(), error=message[:2000]
        )
        return {"submission_id": submission_id, "status": "quality_failed", "error": message}

    return _apply


def prepare_head(submission_id: int, *, owner: str, as_of) -> QualityHead | QualityConcluded:
    """벤더 전 일 앞 절반(DB). 대상에서 빠졌거나(통과가 아니게 됐다·내보냈다) 이미 지금의 기록이
    있으면 조용히 끝낸다. 채점할 수 없으면(키·모델) 실패로 남긴다."""

    del as_of
    tag_error_scope("classroom_quality", submission_id=submission_id)
    submission = (
        ClassroomSubmission.objects.select_related("problem__classroom", "classroom_score", "member")
        .filter(pk=submission_id)
        .first()
    )
    if submission is None:  # pragma: no cover - 시도는 지워지지 않는다(PROTECT).
        return QualityConcluded(apply=lambda: {"submission_id": submission_id, "status": "not_a_target"})
    problem = submission.problem
    class_obj = problem.classroom
    current = board(problem)
    target = next((t for t in current.targets if t.submission.id == submission_id), None)
    if target is None:
        return QualityConcluded(apply=lambda: {"submission_id": submission_id, "status": "not_a_target"})
    if target.review is not None:
        return QualityConcluded(apply=lambda: {"submission_id": submission_id, "status": "already_reviewed"})
    reason = pending_scoring.blocking_reason(class_obj, problem)
    connection = connection_for(class_obj)
    if reason is not None or connection is None:
        return QualityConcluded(apply=_fail(submission_id, BLOCKED_MESSAGES[reason or pending_scoring.NO_API_KEY]))
    return QualityHead(
        submission=submission,
        owner=owner,
        class_obj=class_obj,
        problem=problem,
        items=current.items,
        fingerprint=current.fingerprint,
        connection=connection,
        asset=submission.assets.get(),
    )


def prepare_tail(head: QualityHead) -> PreparedQuality | QualityConcluded:
    """뒤 절반 — 소스 읽기와 프롬프트. **DB 를 쓰지 않는다**(grader 의 소스 풀에서 돈다)."""

    sid = head.submission.id
    source = scoring._read_scoring_source(head.submission, head.asset)
    if not source.ready or source.text is None:
        return QualityConcluded(apply=_fail(sid, f"소스를 읽지 못했다({source.failure_status})."))
    problem = head.problem
    model = problem.effective_model()
    if not head.connection.accepts_model_name(model):
        return QualityConcluded(apply=_fail(sid, f"알 수 없는 채점 모델: {model!r}"))
    items = checklist_inputs(head.items)
    prompt = build_prompt(
        title=problem.title,
        description=problem.description,
        guideline_text=effective_grading_guideline_text(problem.grading_strictness, problem.grading_guideline_text),
        items=items,
        submission_text=source.text,
    )
    return PreparedQuality(
        submission=head.submission,
        owner=head.owner,
        class_obj=head.class_obj,
        problem=problem,
        fingerprint=head.fingerprint,
        connection=head.connection,
        model=model,
        reasoning_effort=_effort(head.connection, problem),
        prompt=prompt,
        quality_input=QualityInput(submission_id=sid, prompt=prompt, items=tuple(items), source_text=source.text),
    )


def _adapter(prepared: PreparedQuality, *, asynchronous: bool) -> QualityReviewAdapter:
    adapter = scoring._scoring_adapter(
        connection=prepared.connection,
        model=prepared.model,
        reasoning_effort=prepared.reasoning_effort,
        asynchronous=asynchronous,
        log_context={"class_id": prepared.class_obj.id, "problem_id": prepared.problem.id},
    )
    if not isinstance(adapter, QualityReviewAdapter):
        raise LLMAdapterPermanentError("이 채점 어댑터는 완성도를 매기지 못한다.")
    return adapter


def call_vendor_sync(prepared: PreparedQuality) -> QualityOutcome:
    try:
        return QualityOutcome(output=_adapter(prepared, asynchronous=False).review_quality(prepared.quality_input))
    except LLMAdapterError as exc:
        return QualityOutcome(error=exc)


async def call_vendor_async(prepared: PreparedQuality) -> QualityOutcome:
    try:
        adapter = _adapter(prepared, asynchronous=True)
        return QualityOutcome(output=await adapter.review_quality_async(prepared.quality_input))
    except LLMAdapterError as exc:
        return QualityOutcome(error=exc)


def _apply_outcome(prepared: PreparedQuality, outcome: QualityOutcome) -> dict:
    sid, class_obj = prepared.submission.id, prepared.class_obj
    exc = outcome.error
    if exc is not None:
        # 계정·모델·크레딧·서버 문제는 판정 채점과 같은 자리로 옮긴다 — 다음 판정 채점·버튼이 같은 사유로 막힌다.
        if isinstance(exc, LLMAdapterAuthError):
            scoring._mark_scoring_key_rejected(class_obj)
        elif isinstance(exc, LLMAdapterModelRejectedError):
            scoring._mark_scoring_model_rejected(prepared.problem)
        elif isinstance(exc, LLMAdapterQuotaExhaustedError):
            scoring._mark_scoring_paused(class_obj, scoring.QUOTA_EXHAUSTED_AT)
        elif isinstance(exc, LLMAdapterUnreachableError):
            scoring._mark_scoring_paused(class_obj, scoring.SERVER_UNREACHABLE_AT)
        return _fail(sid, str(exc))()

    output = outcome.output
    assert output is not None
    used_tokens, estimated = output.total_tokens, False
    if used_tokens <= 0 and prepared.connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        used_tokens, estimated = scoring_cost.estimated_usage_tokens(prepared.prompt, prepared.reasoning_effort), True
    scoring._record_token_usage(class_obj, used_tokens, estimated=estimated)
    mark_verified(class_obj.pk, prepared.connection)
    scored = records(output.scores)
    points = dict(ChecklistItem.objects.filter(problem=prepared.problem).values_list("id", "points"))
    review = ClassroomQualityReview.objects.create(
        submission_id=sid,
        checklist_fingerprint=prepared.fingerprint,
        model_version=output.model_version,
        prompt=prepared.prompt,
        items=scored,
        **historical_columns(quality_total(scored, points)),
    )
    ClassroomQualityJob.objects.filter(submission_id=sid).update(failed_at=None, error="")
    return {"submission_id": sid, "status": "quality_reviewed", "review_id": review.id}


def conclude(submission_id: int, *, owner: str, apply: Callable[[], dict]) -> dict:
    """결과를 쓰고 임대를 놓는다 — 짧은 트랜잭션 하나, 임대가 아직 내 것일 때만(`scoring.conclude_scoring`
    과 같은 규율)."""

    try:
        with transaction.atomic():
            scoring._short_lock_timeout()
            locked = (
                ClassroomQualityJob.objects.select_for_update()
                .filter(submission_id=submission_id, lease_owner=owner)
                .first()
            )
            if locked is None:
                return {"submission_id": submission_id, "status": "lease_lost"}
            result = apply()
            ClassroomQualityJob.objects.filter(submission_id=submission_id).update(
                queued_at=None, lease_owner="", lease_until=None
            )
        return result
    except OperationalError as exc:
        if scoring.is_lock_timeout(exc):
            return {"submission_id": submission_id, "status": "lock_busy"}
        raise


def finish(prepared: PreparedQuality, outcome: QualityOutcome) -> dict:
    return conclude(prepared.submission.id, owner=prepared.owner, apply=lambda: _apply_outcome(prepared, outcome))


def record_unexpected_failure(submission_id: int, *, owner: str, exc: Exception) -> dict:
    logger.exception("완성도 채점 처리 중 예외(submission=%s), 다음 건으로 계속", submission_id)
    return conclude(submission_id, owner=owner, apply=_fail(submission_id, f"{type(exc).__name__}: {exc}"))


def grade_inline(submission_id: int) -> dict | None:
    """pytest 의 `CLASSROOM_GRADER_INLINE` — 같은 세 걸음(임대·준비·결과)을 동기로."""

    from .grader import new_owner

    owner = new_owner()
    as_of = Clock.now()
    if not claim(submission_id, owner=owner, as_of=as_of):
        return None
    try:
        head = prepare_head(submission_id, owner=owner, as_of=as_of)
        prepared = head if isinstance(head, QualityConcluded) else prepare_tail(head)
        if isinstance(prepared, QualityConcluded):
            return conclude(submission_id, owner=owner, apply=prepared.apply)
        return finish(prepared, call_vendor_sync(prepared))
    except Exception as exc:  # noqa: BLE001 - grader 와 같은 규율.
        return record_unexpected_failure(submission_id, owner=owner, exc=exc)
