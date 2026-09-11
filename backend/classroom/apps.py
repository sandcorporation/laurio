from __future__ import annotations

from django.apps import AppConfig


class ClassroomConfig(AppConfig):
    name = "classroom"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # 강의실 채점 스캔(#287) — 등록부에 올라 beat가 주기적으로 돌린다.
        # `scoring.apps.ScoringConfig.ready()`와 같은 패턴이다.
        from django.core.checks import register

        from core.scans import register_scan

        from . import checks
        from .scoring import CLASSROOM_SUBMISSION_SCORING_SCAN

        register_scan(CLASSROOM_SUBMISSION_SCORING_SCAN)
        # 어댑터 모드 부팅 가드(#340, ADR-0043) — `core.apps.CoreConfig.ready()`와
        # 같은 이유로 여기서 등록한다(django.setup() 이후에만 평가돼야 한다).
        register(checks.check_classroom_scoring_adapter_mode)
