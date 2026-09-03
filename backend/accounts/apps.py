from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Authentication · 계정"

    def ready(self) -> None:
        # 신원 파기 스캔 둘(#102, #138, ADR-0025) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .dormancy import IDENTITY_DORMANCY_PURGE_SCAN, RETAINED_IDENTITY_PURGE_SCAN

        register_scan(IDENTITY_DORMANCY_PURGE_SCAN)
        register_scan(RETAINED_IDENTITY_PURGE_SCAN)
