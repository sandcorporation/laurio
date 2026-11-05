"""공모전 완성도 — 마감 뒤 Score 가 생긴 제출에 Requirement 마다 0~5 와 근거를 매긴다(#884, ADR-0072).

계산·프롬프트·응답 규율은 강의실과 같은 `core.quality_review` 를 쓴다. 여기 있는 것은 공모전 몫뿐이다:

- **언제**: `SUBMISSION_QUALITY_SCAN` 이 `SUBMISSION_SCORING_SCAN` 과 나란히 돈다. 「Score 는 있고 완성도는
  없는」 제출(같은 `Contest.Status.SCOREABLE`)을 집는다. Score 흐름은 이 모듈을 모른다 — 완성도가 실패해도
  Score·Distribution·Award 는 그대로다.
- **무엇을 건너뛰나**: Score 가 「입력 없음」·「채점 실패」 자동 0%(`submissions.scoring_basis` 의 두
  model_version)면 매기지 않는다 — AI 가 소스를 읽지 않은 제출이다. Requirement 가 없는 공모전도 건너뛴다.
- **무엇을 읽나**: 소스를 다시 읽거나 저장소를 다시 clone 하지 않는다. Score 프롬프트의 「## Requirements」
  절부터 끝까지(Requirement·자가 응답·선별된 소스 — Evidence 는 #909 부터 싣지 않는다)가 곧 이 제출의 채점 근거라 그것을 제출물로
  싣는다 — Score 와 같은 것을 보고 매기고, 스토리지·GitHub 를 한 번 더 치지 않는다. 그 글은 참가자가 낸
  데이터라 `core.quality_review.build_prompt` 가 `neutralize_untrusted` 로 무력화해 경계 안에 넣는다.
- **키**: `core.llm_scoring.get_adapter()` — Score 와 같은 플랫폼 어댑터다.
- **실패**: `QualityReviewAttempt` 에 남긴다. 영구 실패(`LLMAdapterPermanentError`)가 하나라도 있거나
  `QUALITY_FAILURE_LIMIT` 번 실패하면 더 집지 않는다. 0% 같은 대체값을 지어내지 않는다 — 완성도는 상금과
  무관하니 「없음」으로 남겨도 아무것도 막지 않는다.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Subquery
from django.db.models.functions import Coalesce

from contests.models import Contest, ContestSubmission, Requirement
from core.llm_scoring import LLMAdapterError, LLMAdapterPermanentError, get_adapter
from core.quality_review import (
    BonusScore,
    QualityInput,
    QualityItemInput,
    QualityReviewAdapter,
    QualityTotal,
    build_prompt,
    checklist_fingerprint,
    competition_ranks,
    historical_columns,
    quality_total,
    records,
)
from core.scans import ScanSpec
from submissions.scoring_basis import NO_SCORING_INPUT_MODEL_VERSION, PLATFORM_FAILURE_MODEL_VERSION

from .models import QualityReviewAttempt, Score, SubmissionBonusScore, SubmissionQualityReview

logger = logging.getLogger(__name__)

#: 이 횟수만큼 실패하면 더 집지 않는다 — Score 의 실패 상한(`SCORING_FAILURE_LIMIT`)과 같은 수.
QUALITY_FAILURE_LIMIT = 5

#: AI 가 소스를 읽지 않은 자동 0% Score 들 — 완성도를 매기지 않는다.
SKIPPED_SCORE_MODEL_VERSIONS = (NO_SCORING_INPUT_MODEL_VERSION, PLATFORM_FAILURE_MODEL_VERSION)

#: 공모전엔 채점 지침 입력이 없다 — 지침 자리에 이 고정 문장을 둔다.
_CONTEST_GUIDELINE = "별도 지침 없음 — 체크리스트 문구 그대로 판단한다."

#: Score 프롬프트에서 제출물(Requirement·자가 응답·소스)이 시작되는 머리 — `scoring.services._build_prompt`.
_SUBMISSION_SECTION_HEADER = "## Requirements"


def requirement_inputs(requirements: list[Requirement]) -> list[QualityItemInput]:
    """AI 가 매기는 항목 — 가산은 사람이 매기므로 뺀다(ADR-0073)."""

    return [
        QualityItemInput(
            item_id=r.id, label=r.text, required=r.grade == Requirement.Grade.REQUIRED, points=r.points
        )
        for r in requirements
        if r.grade != Requirement.Grade.BONUS
    ]


def points_by_requirement(contest_id: int) -> dict[int, int]:
    """지금 체크리스트의 Requirement id → 배점(가산 포함) — 완성도는 읽을 때 이것으로 합한다(ADR-0073)."""

    return dict(Requirement.objects.filter(contest_id=contest_id).values_list("id", "points"))


def _submission_text(score: Score) -> str:
    """Score 프롬프트에서 고정 지시문을 떼고 제출물 몫만 돌려준다(모듈 독스트링)."""

    start = score.prompt.find(_SUBMISSION_SECTION_HEADER)
    return score.prompt[start:] if start >= 0 else score.prompt


def _pending_quality(as_of, ctx):
    del as_of, ctx
    attempts = QualityReviewAttempt.objects.filter(submission=OuterRef("pk"))
    attempt_count = attempts.order_by().values("submission").annotate(count=Count("id")).values("count")
    return (
        ContestSubmission.objects.filter(
            contest__status__in=Contest.Status.SCOREABLE.statuses,
            score__isnull=False,
            quality_review__isnull=True,
        )
        .exclude(score__model_version__in=SKIPPED_SCORE_MODEL_VERSIONS)
        .annotate(
            _has_requirement=Exists(
                Requirement.objects.filter(contest=OuterRef("contest_id")).exclude(grade=Requirement.Grade.BONUS)
            ),
            _permanent_failure=Exists(attempts.filter(permanent=True)),
            attempt_count=Coalesce(Subquery(attempt_count), 0),
        )
        .filter(_has_requirement=True, _permanent_failure=False, attempt_count__lt=QUALITY_FAILURE_LIMIT)
        .select_related("contest", "score")
    )


def review_submission_once(submission: ContestSubmission) -> dict:
    """완성도를 한 번 매긴다. 이미 있으면 그대로 돌아온다. 실패는 `QualityReviewAttempt` 로 남긴다."""

    if SubmissionQualityReview.objects.filter(submission_id=submission.id).exists():
        return {"submission_id": submission.id, "status": "already_reviewed"}
    contest = submission.contest
    items = requirement_inputs(list(Requirement.objects.filter(contest=contest).order_by("order", "id")))
    source = _submission_text(submission.score)
    prompt = build_prompt(
        title=contest.title, description="", guideline_text=_CONTEST_GUIDELINE, items=items, submission_text=source
    )
    adapter = get_adapter()
    if not isinstance(adapter, QualityReviewAdapter):
        raise LLMAdapterPermanentError("이 채점 어댑터는 완성도를 매기지 못한다.")
    output = adapter.review_quality(
        QualityInput(submission_id=submission.id, prompt=prompt, items=tuple(items), source_text=source)
    )
    scored = records(output.scores)
    total = quality_total(scored, points_by_requirement(contest.id))
    try:
        with transaction.atomic():
            SubmissionQualityReview.objects.create(
                submission_id=submission.id,
                checklist_fingerprint=checklist_fingerprint(items),
                model_version=output.model_version,
                prompt=prompt,
                items=scored,
                **historical_columns(total),
            )
    except IntegrityError:
        # 겹친 스캔이 먼저 썼다 — 하나만 남는다(OneToOne).
        return {"submission_id": submission.id, "status": "already_reviewed"}
    return {"submission_id": submission.id, "status": "reviewed", "raw_total": total.raw}


def _review_one(submission, as_of, ctx):
    del as_of, ctx
    try:
        return review_submission_once(submission)
    except Exception as exc:  # noqa: BLE001 - 한 건의 실패가 배치를 막지 않는다.
        if not isinstance(exc, LLMAdapterError):
            logger.exception("Submission(pk=%s) 완성도 채점 중 예외, 다음 건으로 계속", submission.id)
        permanent = isinstance(exc, LLMAdapterPermanentError)
        QualityReviewAttempt.objects.create(
            submission_id=submission.id, error=f"{type(exc).__name__}: {exc}"[:2000], permanent=permanent
        )
        return {
            "submission_id": submission.id,
            "status": "failed_permanently" if permanent else "failed",
            "error": str(exc),
        }


#: 무료·유료 모두 대상이라 제품 스위치(`enabled`)를 걸지 않는다 — `submission-scoring` 과 같은 공용 스캔.
#: 정렬은 Score 스캔과 같다: 덜 시도한 것이 먼저, 같으면 id.
SUBMISSION_QUALITY_SCAN = ScanSpec(
    name="submission-quality-review",
    candidates=_pending_quality,
    handle_row=_review_one,
    order_by=("attempt_count", "id"),
)


def bonus_scores(contest_id: int, submission_ids: list[int]) -> dict[int, list[BonusScore]]:
    """제출 id → 지금 가산 Requirement 마다의 개최자 점수(#905). 매기지 않은 가산은 0점·`rated=False` 로 채운다
    — 완성도 합계와 화면이 같은 목록을 본다."""

    bonus_requirements = list(
        Requirement.objects.filter(contest_id=contest_id, grade=Requirement.Grade.BONUS).order_by("order", "id")
    )
    stored = {
        (row.submission_id, row.requirement_id): row
        for row in SubmissionBonusScore.objects.filter(
            submission_id__in=submission_ids, requirement__in=bonus_requirements
        )
    }
    result: dict[int, list[BonusScore]] = {}
    for submission_id in submission_ids:
        scores = []
        for requirement in bonus_requirements:
            row = stored.get((submission_id, requirement.id))
            scores.append(
                BonusScore(item_id=requirement.id, label=requirement.text)
                if row is None
                else BonusScore(
                    item_id=requirement.id, label=requirement.text, score=row.score, memo=row.memo, rated=True
                )
            )
        result[submission_id] = scores
    return result


def review_total(
    review: SubmissionQualityReview, points: dict[int, int], bonus: list[BonusScore] | None = None
) -> QualityTotal:
    """기록의 0~5 와 가산 사람 점수를 지금 배점으로 합한다 — 저장 칸(`weighted_score` 등)은 역사값이라 읽지
    않는다(ADR-0073)."""

    return quality_total(review.items, points, bonus or ())


def ranked_reviews(
    contest_id: int, submission_ids: list[int]
) -> dict[int, tuple[SubmissionQualityReview, QualityTotal, int]]:
    """개최자 비교 화면 몫 — 제출 id → (완성도 기록, 지금 배점으로 합한 완성도, 완성도 순위). 등수는 정수
    Σ(0~5 × 배점)으로, 같으면 같은 등수(`core.quality_review.competition_ranks`). 기록이 없는 제출은 결과에 없다."""

    points = points_by_requirement(contest_id)
    reviews = list(SubmissionQualityReview.objects.filter(submission_id__in=submission_ids))
    bonus = bonus_scores(contest_id, [r.submission_id for r in reviews])
    totals = [review_total(r, points, bonus[r.submission_id]) for r in reviews]
    ranks = competition_ranks([t.raw for t in totals])
    return {r.submission_id: (r, t, rank) for r, t, rank in zip(reviews, totals, ranks, strict=True)}


__all__ = [
    "QUALITY_FAILURE_LIMIT",
    "bonus_scores",
    "SUBMISSION_QUALITY_SCAN",
    "points_by_requirement",
    "ranked_reviews",
    "review_total",
    "requirement_inputs",
    "review_submission_once",
]
