"""현재 점수를 읽는 유일한 자리(#1179, 스펙 #1178, ADR-0006 개정 절).

원래 `Score` 는 그대로 두고 `ScoreCorrection` 을 덧댄다. 「현재 점수」는 끝난 정정 중 가장 나중에 걸린 것(id 가
가장 큰 것), 없으면 원래 `Score` 다. 진행 중·실패한 정정은 현재 점수를 바꾸지 않는다.

두 벌이다:

- `current_score(submission)` — 한 제출. `CurrentScore`(같은 필드 모양) 또는 채점 전이면 None.
- `with_current_score(queryset, path=...)` — 쿼리. 유효 `current_percentage`·`current_model_version` 을 붙인다
  (컷라인·완성도 대상 거르기처럼 여럿을 한 번에 거르는 자리).

「채점이 한 번 돌았나」(채점 대기·보류·이의 신청 가능)는 원래 `Score` 유무를 그대로 묻는다 — 정정은 원래 Score
가 있어야 생기기 때문이다. 이 모듈 밖에서 판정 필드를 직접 읽는 것은 `tests/test_current_score_reads.py` 가 막는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from django.db.models import F, OuterRef, Subquery
from django.db.models.functions import Coalesce

from submissions.current_score import CurrentScore

from .models import ScoreCorrection

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from submissions.models import Submission

    from .models import Score

M = TypeVar("M", bound="Model")

#: `current_score` 가 걷는 관계 — 목록에서 행마다 조회하지 않게 `select_related` 로 당긴다
CURRENT_SCORE_RELATIONS = ("score",)


def latest_done_correction(score: Score) -> ScoreCorrection | None:
    return (
        ScoreCorrection.objects.filter(score_id=score.pk, status=ScoreCorrection.Status.DONE).order_by("-id").first()
    )


def current_score(submission: Submission) -> CurrentScore | None:
    score: Score | None = getattr(submission, "score", None)
    if score is None:
        return None
    correction = latest_done_correction(score)
    if correction is None or correction.percentage is None:
        return CurrentScore(
            submission=score.submission,
            percentage=score.percentage,
            model_version=score.model_version,
            prompt=score.prompt,
            reasoning=score.reasoning,
            scored_assets=score.scored_assets,
            repository_reachability_check=score.repository_reachability_check,
            created_at=score.created_at,
        )
    return CurrentScore(
        submission=score.submission,
        percentage=correction.percentage,
        model_version=correction.model_version,
        prompt=correction.prompt,
        reasoning=correction.reasoning,
        scored_assets=correction.scored_assets,
        repository_reachability_check=correction.repository_reachability_check,
        created_at=score.created_at,
        corrected=True,
        original_percentage=score.percentage,
        original_model_version=score.model_version,
        correction_reason=correction.reason,
    )


def with_current_score(queryset: QuerySet[M], *, path: str = "") -> QuerySet[M]:
    """`queryset` 의 행에 유효 `current_percentage`·`current_model_version` 을 붙인다.

    `path` 는 행에서 제출까지의 ORM 경로다(제출 자신이면 빈 문자열, 이의면 `"submission__"`). 채점 전 제출은
    둘 다 None 이다.
    """

    score = f"{path}score"
    latest = ScoreCorrection.objects.filter(score=OuterRef(f"{score}__pk"), status=ScoreCorrection.Status.DONE).order_by(
        "-id"
    )
    return queryset.annotate(
        current_percentage=Coalesce(Subquery(latest.values("percentage")[:1]), F(f"{score}__percentage")),
        current_model_version=Coalesce(Subquery(latest.values("model_version")[:1]), F(f"{score}__model_version")),
    )
