from django.apps import AppConfig


class ScoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scoring"
    verbose_name = "Score · AI 채점"

    def ready(self) -> None:
        # 어댑터 부팅 가드(check_llm_adapter_mode)는 core.apps.CoreConfig.ready()가
        # 등록한다(#274) — 검사 대상(LLMScoringAdapter)이 core.llm_scoring으로
        # 옮겨가면서 검사도 함께 옮겨갔다. `scoring.checks`는 재노출만 남아 있다.

        # 채점 스캔(#12, #139) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .services import SUBMISSION_SCORING_SCAN

        register_scan(SUBMISSION_SCORING_SCAN)
