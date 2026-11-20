from __future__ import annotations

from django.apps import AppConfig


class HandoversConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "handovers"
    verbose_name = "Handover · 소스 접근 개방 · Escrow 해제"

    def ready(self) -> None:
        from core.scans import register_scan

        from .scans import HANDOVER_RELEASE_SCAN

        register_scan(HANDOVER_RELEASE_SCAN)
        # 빌드 자산의 content-type(#241) — 공유층 `submissions.resolvers` 가 handovers 를 import 하지 않게 여기서 올린다(#1085).
        from submissions.resolvers import BUILD_ASSET_CONTENT_TYPE

        from .services import build_asset_content_type

        BUILD_ASSET_CONTENT_TYPE.register(build_asset_content_type)

        # 선정과 함께 인수인계를 연다(#14, #1086) — `awards.ports`
        from awards.ports import OPEN_HANDOVER

        from .services import open_handover

        OPEN_HANDOVER.register(open_handover)
