"""부팅 시점 LLM 채점·GitHub 저장소 어댑터 검증 (#83, #193, #274, #287,
ADR-0006/0007/0014/0027).

`LLM_ADAPTER_MODE`·`GITHUB_ADAPTER_MODE`가 배포 환경에서 "fake"도 아니고
실제로 쓸 수도 없으면(임포트 실패·인스턴스화 실패·계약 불충족) 부팅 자체를
거부한다. `storage.checks.check_storage_backend_is_importable`과 같은 원칙 —
Score가 실제 채점 없이 만들어지면 Distribution 대상 판정이 통째로 무효가
되므로, 이 어댑터들은 첫 채점 시도가 아니라 부팅 시점에 확인해야 한다.

원래 각각 `scoring.checks`·`repositories.checks`였다 — 검사 대상 어댑터가
공유층으로 옮겨오면서(`core.llm_scoring` #274, `core.repository_adapters`
#287) 검사도 함께 옮겨졌다. 옛 모듈은 재노출만 남아 있다(#274/#287 AC —
기존 임포트 경로를 깨지 않는다).
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .llm_scoring import LLMScoringAdapter
from .repository_adapters import GitHubAdapter


def check_llm_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="LLM_ADAPTER_MODE", protocol=LLMScoringAdapter)


def check_github_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="GITHUB_ADAPTER_MODE", protocol=GitHubAdapter)
