"""`core.llm_scoring`의 재노출 (#274).

**원본은 `core.llm_scoring`에 있다.** LLM 채점 어댑터는 `core.adapters` 하나만
아는 완전 범용 코드였는데 `scoring`은 공모전 가족이라(`tests/
test_app_boundaries.py`, ADR-0037) 강의실이 채점하려면 이 모듈이 공유층에
있어야 했다 — 그래서 옮겼다.

이 파일이 계속 남아 있는 이유는 재노출이다: `LLM_ADAPTER_MODE`가 가리키는
dotted path(`scoring.adapters.OpenAIScoringAdapter`)와 `docker/*.env.example`을
이 이동 때문에 고치지 않기 위해서다(#274 AC) — `scoring.services.
NO_SCORING_INPUT_MODEL_VERSION`(#246)이 `submissions.scoring_basis`를 재노출하는
것과 같은 패턴이다. 새 호출자(강의실 포함)는 여기가 아니라 `core.llm_scoring`을
직접 부른다.

`requests`도 함께 재노출한다 — 기존 테스트(`tests/test_openai_scoring_adapter.py`)가
`monkeypatch.setattr("scoring.adapters.requests.post", ...)`로 이 이름 아래의
`requests` 모듈을 패치한다. `requests`는 프로세스에 하나뿐인 모듈이라(싱글톤),
이 이름으로 접근해 패치해도 `core.llm_scoring`의 호출이 그대로 그 패치를 본다.
"""

from __future__ import annotations

import requests

from core.llm_scoring import (
    FakeLLMScoringAdapter,
    LLMAdapterError,
    LLMAdapterPermanentError,
    LLMScoringAdapter,
    OpenAIScoringAdapter,
    RequirementInput,
    RequirementVerdict,
    ScoringInput,
    ScoringOutput,
    SourceFile,
    _describe_openai_http_error,
    _openai_verdict_response_schema,
    _parse_openai_scoring_response,
    get_adapter,
)

__all__ = [
    "requests",
    "FakeLLMScoringAdapter",
    "LLMAdapterError",
    "LLMAdapterPermanentError",
    "LLMScoringAdapter",
    "OpenAIScoringAdapter",
    "RequirementInput",
    "RequirementVerdict",
    "ScoringInput",
    "ScoringOutput",
    "SourceFile",
    "get_adapter",
]
