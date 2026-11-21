from django.apps import AppConfig


class FeedbackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "feedback"
    verbose_name = "Feedback · 건의·버그 제보"

    def ready(self) -> None:
        from core.scans import register_scan

        from .retention import FEEDBACK_SCREENSHOT_RETENTION_SCAN

        register_scan(FEEDBACK_SCREENSHOT_RETENTION_SCAN)
