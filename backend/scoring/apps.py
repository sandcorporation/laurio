from django.apps import AppConfig


class ScoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scoring"
    verbose_name = "Score · AI 채점"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_llm_adapter_mode)

        # 채점 스캔(#12, #139) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .services import SUBMISSION_SCORING_SCAN

        register_scan(SUBMISSION_SCORING_SCAN)
