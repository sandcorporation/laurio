from __future__ import annotations

from django.apps import AppConfig


class PayoutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payouts"
    verbose_name = "Payout · 지급 실행"
