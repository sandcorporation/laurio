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

        # 신원 파기 스캔 둘(#102, #138, ADR-0025) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .dormancy import IDENTITY_DORMANCY_PURGE_SCAN, RETAINED_IDENTITY_PURGE_SCAN

        register_scan(IDENTITY_DORMANCY_PURGE_SCAN)
        register_scan(RETAINED_IDENTITY_PURGE_SCAN)

        # 탈퇴의 신원 파기(#470, #1086) — `accounts.ports`
        from accounts.ports import PURGE_IDENTITY

        from .purge import purge_identity

        PURGE_IDENTITY.register(purge_identity)
