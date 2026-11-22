"""강의실 「현재 점수」를 읽는 유일한 자리(#1317, ADR-0006 개정 절).

원래 `ClassroomScore` 는 지우지도 고치지도 않는다. 플랫폼 오류로 틀린 점수는 `ClassroomScoreCorrection` 을 덧대
바로잡고, **끝난 정정 중 가장 나중 것**이 현재 점수가 된다 — 없으면 원래 점수다. 판정(통과·완벽·달성률·근거·
리포트·가격 대조)은 모두 이것을 읽는다. 구조 시험 `tests/test_classroom_current_score_reads.py` 가 이 모듈 밖에서
원래 점수를 직접 읽는 것을 막는다.

「채점이 한 번 돌았나」(채점 대기·보류·반려)는 원래 `ClassroomScore` 유무 그대로다 — 정정은 원래 점수가 있어야
생기므로 이 물음의 답이 바뀌지 않는다.

두 벌이다:

- 한 건 — `current_score(submission)`, `current_of(score)`.
- 쿼리 — `with_current_score(submissions)` 가 끝난 정정을 미리 불러 두면 `current_score` 가 다시 묻지 않는다.
  집계는 `scores_with_current_fields()` 가 현재 값을 `current_*` 이름으로 붙인 원래 점수 쿼리셋을 준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F, IntegerField, OuterRef, Prefetch, QuerySet, Subquery
from django.db.models.functions import Coalesce, Length

from .models import ClassroomScore, ClassroomScoreCorrection, ClassroomSubmission

#: `with_current_score` 가 원래 점수 위에 붙이는 끝난 정정 목록(최신 먼저)의 이름.
_PREFETCHED = "done_corrections"

M = TypeVar("M", ClassroomSubmission, ClassroomScore)


@dataclass(frozen=True)
class CurrentClassroomScore:
    """지금 판정으로 읽는 점수 하나 — 판정 필드는 `ClassroomScore` 와 같은 이름이다(`Problem.is_score_passed` 등이
    그대로 받는다)."""

    original: ClassroomScore
    correction: ClassroomScoreCorrection | None
    model_version: str
    reasoning: list[dict]
    syntax_check_result: dict | None
    unseen_files: int
    #: 이 판정이 난 때 — 정정이면 정정이 끝난 때다.
    created_at: datetime

    @property
    def corrected(self) -> bool:
        return self.correction is not None

    @property
    def prompt(self) -> str:
        """이 판정이 본 프롬프트 — 크니 필요한 자리만 읽는다(목록 쿼리는 미뤄 둔다)."""

        return self.correction.prompt if self.correction is not None else self.original.prompt


def _latest_done(score: ClassroomScore) -> ClassroomScoreCorrection | None:
    prefetched = getattr(score, _PREFETCHED, None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None
    return (
        ClassroomScoreCorrection.objects.filter(score=score, status=ClassroomScoreCorrection.Status.DONE)
        .order_by("-id")
        .first()
    )


def current_of(score: ClassroomScore) -> CurrentClassroomScore:
    """원래 점수 하나의 현재 판정."""

    correction = _latest_done(score)
    if correction is None:
        return CurrentClassroomScore(
            original=score,
            correction=None,
            model_version=score.model_version,
            reasoning=score.reasoning,
            syntax_check_result=score.syntax_check_result,
            unseen_files=score.unseen_files,
            created_at=score.created_at,
        )
    assert correction.finished_at is not None  # 끝난 정정은 끝난 때가 있다(제약)
    return CurrentClassroomScore(
        original=score,
        correction=correction,
        model_version=correction.model_version,
        reasoning=correction.reasoning,
        syntax_check_result=correction.syntax_check_result,
        unseen_files=correction.unseen_files,
        created_at=correction.finished_at,
    )


def original_score(submission: ClassroomSubmission) -> ClassroomScore | None:
    """원래 점수 행 — 「채점이 한 번 돌았나」와 정정을 거는 자리만 쓴다. 판정은 `current_score` 로 읽는다."""

    try:
        return submission.classroom_score
    except ObjectDoesNotExist:
        return None


def current_score(submission: ClassroomSubmission | None) -> CurrentClassroomScore | None:
    """시도 하나의 현재 점수 — 아직 채점되지 않았으면 `None`."""

    if submission is None:
        return None
    score = original_score(submission)
    return None if score is None else current_of(score)


def _done_corrections() -> QuerySet[ClassroomScoreCorrection]:
    return (
        ClassroomScoreCorrection.objects.filter(status=ClassroomScoreCorrection.Status.DONE)
        .defer("prompt")
        .order_by("-id")
    )


def current_score_prefetch(*, path: str = "") -> Prefetch:
    """끝난 정정을 미리 부르는 `Prefetch` — 쿼리 사슬 가운데 `.prefetch_related(current_score_prefetch())` 로 끼운다.
    원래 점수(`classroom_score`)는 부르는 쪽이 `select_related` 로 함께 부른다."""

    return Prefetch(f"{path}classroom_score__corrections", queryset=_done_corrections(), to_attr=_PREFETCHED)


def with_current_score(queryset: QuerySet[M], *, path: str = "") -> QuerySet[M]:
    """시도(`ClassroomSubmission`) 쿼리셋에 원래 점수와 끝난 정정을 미리 불러 둔다 — 목록에서 `current_score` 가
    시도마다 다시 묻지 않게. `path` 는 시도까지 가는 관계(`"submission__"` 등)다."""

    return queryset.select_related(f"{path}classroom_score").prefetch_related(current_score_prefetch(path=path))


def scores_with_current_fields() -> QuerySet[ClassroomScore]:
    """원래 점수 전부에 현재 값을 붙인 쿼리셋 — 집계(가격 대조·실측 평균)가 SQL 안에서 현재 값을 쓰게. 붙는 이름은
    `current_model_version`, `current_prompt_length`, `current_created_at` 이다. 거르기·집계는 이 이름으로만 한다."""

    latest = ClassroomScoreCorrection.objects.filter(
        score=OuterRef("pk"), status=ClassroomScoreCorrection.Status.DONE
    ).order_by("-id")
    return ClassroomScore.objects.annotate(
        current_model_version=Coalesce(Subquery(latest.values("model_version")[:1]), F("model_version")),
        current_prompt_length=Coalesce(
            Subquery(latest.annotate(n=Length("prompt")).values("n")[:1], output_field=IntegerField()),
            Length("prompt"),
        ),
        current_created_at=Coalesce(Subquery(latest.values("finished_at")[:1]), F("created_at")),
    )
