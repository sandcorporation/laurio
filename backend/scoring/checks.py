"""부팅 시점 어댑터 검증 (#83, ADR-0006/0007/0014).

`LLM_ADAPTER_MODE`가 배포 환경에서 "fake"도 아니고 실제로 쓸 수도
없으면(임포트 실패·인스턴스화 실패·`LLMScoringAdapter` 계약 불충족) 부팅
자체를 거부한다. `storage.checks.check_storage_backend_is_importable`과 같은
원칙 — Score가 실제 채점 없이 만들어지면 Distribution 대상 판정이 통째로
무효가 되므로, 이 어댑터는 첫 채점 시도가 아니라 부팅 시점에 확인해야 한다.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .adapters import LLMScoringAdapter


def check_llm_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="LLM_ADAPTER_MODE", protocol=LLMScoringAdapter)
