"""보류된 공모전 채점을 푼다(#986) — 앱 코드가 모델 컨텍스트에 다 들어가지 않아 멈춘 제출을,
사람이 보고 「실린 만큼으로 채점하라」고 정했을 때 쓴다.

    python manage.py release_scoring_hold 617 866

보류 기록(`SourceOverBudgetHold:`)의 머리를 `SourceOverBudgetReleased:` 로 바꾼다 — 기록은
지우지 않는다. 다음 `submission-scoring` 스캔이 그 제출을 다시 고르고, 이번에는 보류하지 않는다.

에이전트 채점 보류(`AgentScoringHold:`, #1000)도 같이 푼다 — `AgentScoringReleased:` 로 바뀌고, 다음 스캔이
에이전트를 다시 부른다(받아들이는 조건을 낮추지는 않는다. 다시 어긋나면 또 보류다).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Value
from django.db.models.functions import Concat, Substr

from scoring.models import ScoringAttempt
from scoring.services import (
    AGENT_SCORING_HOLD_ERROR_PREFIX,
    AGENT_SCORING_HOLD_RELEASED_ERROR_PREFIX,
    SCORING_HOLD_ERROR_PREFIX,
    SCORING_HOLD_RELEASED_ERROR_PREFIX,
)


class Command(BaseCommand):
    help = "보류된 공모전 채점(소스가 컨텍스트를 넘은 제출·에이전트 판정이 어긋난 제출)을 풀어 다시 채점하게 한다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("submission_ids", nargs="+", type=int)

    def handle(self, *args, submission_ids: list[int], **options) -> None:
        released = 0
        for held, freed in (
            (SCORING_HOLD_ERROR_PREFIX, SCORING_HOLD_RELEASED_ERROR_PREFIX),
            (AGENT_SCORING_HOLD_ERROR_PREFIX, AGENT_SCORING_HOLD_RELEASED_ERROR_PREFIX),
        ):
            released += ScoringAttempt.objects.filter(
                submission_id__in=submission_ids, error__startswith=held
            ).update(error=Concat(Value(freed), Substr("error", len(held) + 1)))
        self.stdout.write(f"보류 기록 {released}건을 풀었다(submission_ids={submission_ids}).")
