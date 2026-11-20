"""공모전 판정이 묻는 채점 사실 — `scoring.apps` 가 `contests.ports` 와 `repositories.ports` 에 올린다(#1102).

관계 이름(`score`·`quality_review`·`scoring_attempts`)은 이 앱의 모델이 연 역관계라 여기서만 적는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from contests.models import ContestSubmission
    from submissions.models import SubmissionAsset

#: 「다음 행동」이 당길 관계
NEXT_ACTION_RELATIONS = ("score",)
#: 점수 화면이 당길 관계
OWN_SCORE_RELATIONS = ("score", "quality_review")


def is_scored(submission: ContestSubmission) -> bool:
    return hasattr(submission, "score")


def still_to_score(assets: QuerySet[SubmissionAsset]) -> QuerySet[SubmissionAsset]:
    """아직 Score 가 없고 영구 실패로 접지 않은 제출의 자산만 — 저장소 공개 확인 스캔의 후보."""

    return assets.filter(submission__score__isnull=True).exclude(submission__scoring_attempts__permanent=True)
