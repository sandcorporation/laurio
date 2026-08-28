from __future__ import annotations

from django.apps import AppConfig


class AwardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "awards"
    verbose_name = "Award · 선정"
