"""부팅 시점 어댑터 검증 (#83, #193, ADR-0007, ADR-0027).

`GITHUB_ADAPTER_MODE`가 배포 환경에서 "fake"도 아니고 실제로 쓸 수도
없으면(임포트 실패·인스턴스화 실패·`GitHubAdapter` 계약 불충족) 부팅 자체를
거부한다. `scoring.checks.check_llm_adapter_mode`와 같은 원칙이다.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .adapters import GitHubAdapter


def check_github_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="GITHUB_ADAPTER_MODE", protocol=GitHubAdapter)
