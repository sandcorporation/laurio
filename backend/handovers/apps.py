from __future__ import annotations

from django.apps import AppConfig


class HandoversConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "handovers"
    verbose_name = "Handover · 소스 접근 개방 · Escrow 해제"
