"""부팅 시점 어댑터 검증 (#83, ADR-0007).

`VERIFICATION_ADAPTER_MODE`가 배포 환경에서 "fake"도 아니고 실제로 쓸 수도
없으면(임포트 실패·인스턴스화 실패·`VerificationAdapter` 계약 불충족) 부팅
자체를 거부한다. `storage.checks.check_storage_backend_is_importable`과 같은
원칙 — `manage.py check`(CI가 이미 돌린다)와 `migrate`/`runserver` 기동 시 이
검사가 먼저 돌아 배포 자체를 막는다.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .adapters import VerificationAdapter


def check_verification_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="VERIFICATION_ADAPTER_MODE", protocol=VerificationAdapter)
