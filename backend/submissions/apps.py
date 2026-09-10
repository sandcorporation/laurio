from __future__ import annotations

from django.apps import AppConfig


class SubmissionsConfig(AppConfig):
    name = "submissions"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # 시연 영상 파일 보존 기간 만료 스캔(#262, ADR-0035) — 등록부에 올라
        # beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .retention import DEMO_VIDEO_RETENTION_PURGE_SCAN

        register_scan(DEMO_VIDEO_RETENTION_PURGE_SCAN)
