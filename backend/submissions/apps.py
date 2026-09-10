from __future__ import annotations

from django.apps import AppConfig


class SubmissionsConfig(AppConfig):
    name = "submissions"
    default_auto_field = "django.db.models.BigAutoField"

    # 시연 영상 파일 보존 기간 만료 스캔(#262, ADR-0035)은 공모전 전용이라
    # `contests.apps.ContestsConfig.ready`로 옮겼다(#270, ADR-0039) — 이 앱은
    # 이제 공유층이라 어느 제품 스캔도 스스로 등록하지 않는다.
