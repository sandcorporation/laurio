from __future__ import annotations

from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class StorageConfig(AppConfig):
    name = "storage"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_storage_backend_is_importable, BOOT_CHECK_TAG)
