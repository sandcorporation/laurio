from __future__ import annotations

from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class PayoutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payouts"
    verbose_name = "Payout · 지급 실행"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_payout_adapter_mode, BOOT_CHECK_TAG)
        register(checks.check_seller_adapter_mode, BOOT_CHECK_TAG)

        # 「지급이 당신을 기다린다」 스캔(#169) — 등록부에 올라 틱 한 바퀴에 함께 돈다.
        from core.scans import register_scan

        from .notifications import PAYOUT_NOTIFICATION_SCANS
        from .recovery import SELLER_REGISTRATION_RECOVERY_SCANS

        for spec in PAYOUT_NOTIFICATION_SCANS:
            register_scan(spec)

        # 접수되지 않은 Seller 등록의 자력 회복 스캔(#178).
        for spec in SELLER_REGISTRATION_RECOVERY_SCANS:
            register_scan(spec)
