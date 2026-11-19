"""보류된 공모전 채점을 푼다(#986) — 앱 코드가 모델 컨텍스트에 다 들어가지 않아 멈춘 제출을,
사람이 보고 「실린 만큼으로 채점하라」고 정했을 때 쓴다.

    python manage.py release_scoring_hold 617 866

보류 기록(`SourceOverBudgetHold:`)의 머리를 `SourceOverBudgetReleased:` 로 바꾼다 — 기록은
지우지 않는다. 다음 `submission-scoring` 스캔이 그 제출을 다시 고르고, 이번에는 보류하지 않는다.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Value
from django.db.models.functions import Concat, Substr

from scoring.models import ScoringAttempt
from scoring.services import SCORING_HOLD_ERROR_PREFIX, SCORING_HOLD_RELEASED_ERROR_PREFIX


class Command(BaseCommand):
    help = "보류된 공모전 채점(앱 코드가 컨텍스트를 넘은 제출)을 풀어 실린 만큼으로 채점하게 한다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("submission_ids", nargs="+", type=int)

    def handle(self, *args, submission_ids: list[int], **options) -> None:
        released = ScoringAttempt.objects.filter(
            submission_id__in=submission_ids, error__startswith=SCORING_HOLD_ERROR_PREFIX
        ).update(
            error=Concat(
                Value(SCORING_HOLD_RELEASED_ERROR_PREFIX),
                Substr("error", len(SCORING_HOLD_ERROR_PREFIX) + 1),
            )
        )
        self.stdout.write(f"보류 기록 {released}건을 풀었다(submission_ids={submission_ids}).")
