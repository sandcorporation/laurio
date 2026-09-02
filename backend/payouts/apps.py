from __future__ import annotations

from django.apps import AppConfig


class PayoutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payouts"
    verbose_name = "Payout · 지급 실행"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_payout_adapter_mode)
        register(checks.check_seller_adapter_mode)
