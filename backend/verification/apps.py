from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class VerificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "verification"
    verbose_name = "Verification · 본인확인"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_verification_adapter_mode, BOOT_CHECK_TAG)
