from django.apps import AppConfig


class ScoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scoring"
    verbose_name = "Score · AI 채점"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_llm_adapter_mode)
