"""부팅 시점 강의실 채점 어댑터 검증 (#340, ADR-0043).

`CLASSROOM_SCORING_ADAPTER_MODE`가 배포 환경에서 fake이거나(config.settings가
모듈 임포트 시점에 이미 부팅 자체를 거부한다) 실제로 쓸 수도 없으면(임포트
실패·인스턴스화 실패·`LLMScoringAdapter` 계약 불충족) 마찬가지로 부팅을
거부한다 — `core.checks.check_llm_adapter_mode`·`check_github_adapter_mode`와
같은 원칙(#83)이다.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode
from core.llm_scoring import LLMScoringAdapter


def check_classroom_scoring_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="CLASSROOM_SCORING_ADAPTER_MODE", protocol=LLMScoringAdapter)
