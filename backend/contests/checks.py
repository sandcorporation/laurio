"""부팅 시점 어댑터 검증 (#83, ADR-0007).

`LLM_REQUIREMENT_CHAT_ADAPTER_MODE`·`SEARCH_ADAPTER_MODE`(#451)가 배포
환경에서 "fake"도 아니고 실제로 쓸 수도 없으면(임포트 실패·인스턴스화 실패·
계약 불충족) 부팅 자체를 거부한다. `storage.checks.
check_storage_backend_is_importable`과 같은 원칙.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .requirement_chat import RequirementChatAdapter
from .search import ContestSearchAdapter


def check_llm_requirement_chat_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="LLM_REQUIREMENT_CHAT_ADAPTER_MODE", protocol=RequirementChatAdapter
    )


def check_search_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    """검색 어댑터 부팅 가드 (#451) — `LLM_REQUIREMENT_CHAT_ADAPTER_MODE`와 같은
    원칙. `config/settings.py`가 값 자체가 "fake"인 것은 모듈 임포트 시점에
    이미 막는다 — 이 검사는 dotted path가 **가리키는 값**이 깨졌을 때(임포트
    실패·인스턴스화 실패·`ContestSearchAdapter` 계약 불충족)를 잡는다."""

    return check_adapter_mode(setting_name="SEARCH_ADAPTER_MODE", protocol=ContestSearchAdapter)
