from __future__ import annotations

from django.apps import AppConfig


class ClassroomConfig(AppConfig):
    name = "classroom"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # 강의실 채점 스캔(#287) — 등록부에 올라 beat가 주기적으로 돌린다.
        # `scoring.apps.ScoringConfig.ready()`와 같은 패턴이다.
        from core.scans import register_scan

        from .scoring import CLASSROOM_SUBMISSION_SCORING_SCAN

        register_scan(CLASSROOM_SUBMISSION_SCORING_SCAN)
