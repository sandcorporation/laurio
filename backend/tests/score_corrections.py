"""시험이 정정 행을 덧대는 도우미(#1179) — 정정을 거는 API(#1180)가 생기기 전까지 ORM 으로 만든다."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from scoring.models import Score, ScoreCorrection


def correct(
    submission_id: int,
    percentage: str,
    *,
    model_version: str = "fake-llm-v1",
    status: str = ScoreCorrection.Status.DONE,
    reason: str = "플랫폼 오류로 다시 채점했다",
    prompt: str = "정정 채점 프롬프트",
) -> ScoreCorrection:
    operator, _ = get_user_model().objects.get_or_create(username="correction-operator")
    score = Score.objects.get(submission_id=submission_id)
    done = status == ScoreCorrection.Status.DONE
    return ScoreCorrection.objects.create(
        score=score,
        status=status,
        percentage=Decimal(percentage) if done else None,
        model_version=model_version if done else "",
        prompt=prompt if done else "",
        reasoning=[{"requirement_id": 0, "is_met": True, "reasoning": "정정 판정"}] if done else [],
        reason=reason,
        operator=operator,
        finished_at=timezone.now() if status != ScoreCorrection.Status.IN_PROGRESS else None,
    )
