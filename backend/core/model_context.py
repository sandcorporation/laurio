"""모델별 컨텍스트 창(토큰)과, 그 안에 싣을 수 있는 소스 바이트(#986).

**공유층(`core`)에 산다.** 표는 원래 강의실 모델 카탈로그(`classroom.scoring_models`)에
있었다 — 공모전 채점(`scoring`)이 「이 모델에 소스가 다 들어가는가」를 판정하려면 같은 표가
필요한데, 공모전 가족은 `classroom` 을 부를 수 없다(`tests/test_app_boundaries.py`).
강의실 카탈로그는 이 표를 다시 노출한다.
"""

from __future__ import annotations

#: 아는 모델의 컨텍스트 윈도(#285가 이미 확인한 네 값 + GPT-5 계열).
#: GPT-5 계열의 400,000은 OpenAI 문서가 밝힌 값이나 실제 벤더 호출로 재확인
#: 하지 않았다 — staging 키로 `/v1/models`를 조회해도 컨텍스트 크기는 내려오지
#: 않는다(#401 Problem Statement). 표에 없는 모델은 `context_window=None`으로
#: 내려 「크기 미확인」이 뜨고, 소스 판정은 `DEFAULT_CONTEXT_WINDOW_TOKENS` 로 보수적으로 본다.
KNOWN_OPENAI_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "gpt-5": 400_000,
    "gpt-5.1": 400_000,
    "gpt-5.2": 400_000,
    "gpt-5.4": 400_000,
    "gpt-5.5": 400_000,
    "gpt-5-mini": 400_000,
    "gpt-5-nano": 400_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4-nano": 400_000,
}

#: 문서(2026-10-28, https://platform.claude.com/docs/en/about-claude/models/overview)의 컨텍스트 크기.
KNOWN_CLAUDE_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-haiku-5-5": 1_000_000,
    "claude-sonnet-5-5": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,  # 같은 문서(2026-11-22 확인) — 「All models」 표에 1M, 베타·조건 표시 없음.
}

#: 표에 없는 모델을 볼 때의 컨텍스트 — 지금 공모전 기본 모델(`gpt-4o-mini`)과 같다.
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000

#: 응답 몫으로 비워 두는 토큰 — gpt-4o-mini 의 출력 상한(16,384)이다.
OUTPUT_RESERVE_TOKENS = 16_384

#: 소스 바이트 ↔ 토큰 환산(보수적). 공모전 3에서 300KB 로 잘린 입력이 약 8.3만 토큰이었다
#: (≈3.6바이트/토큰, ops_metrics_llmminute). 한글 주석이 많은 소스는 토큰이 더 촘촘하므로 3으로 낮춰 잡는다.
BYTES_PER_TOKEN = 3


def context_window_tokens(model: str) -> int:
    """`model` 의 컨텍스트 창. 모르면 `DEFAULT_CONTEXT_WINDOW_TOKENS`."""

    return (
        KNOWN_OPENAI_CONTEXT_WINDOWS.get(model)
        or KNOWN_CLAUDE_CONTEXT_WINDOWS.get(model)
        or DEFAULT_CONTEXT_WINDOW_TOKENS
    )


def is_known_model(model: str) -> bool:
    """표에 컨텍스트가 있는 모델인가 — 없으면 `context_window_tokens` 는 기본값으로 본다."""

    return model in KNOWN_OPENAI_CONTEXT_WINDOWS or model in KNOWN_CLAUDE_CONTEXT_WINDOWS


def input_token_limit(model: str) -> int:
    """`model` 한 번의 요청에 실을 수 있는 입력 토큰 — 컨텍스트에서 응답 몫을 뺀다(#989)."""

    return context_window_tokens(model) - OUTPUT_RESERVE_TOKENS


def request_tokens(size_bytes: int) -> int:
    """요청 바이트를 토큰으로 어림한다(#989) — 소스 예산과 같은 비율(`BYTES_PER_TOKEN`)이고 올림한다.
    바이트/3 은 문자/3 보다 언제나 크거나 같다(한글은 글자 하나가 3바이트라 글자 하나 = 토큰 하나)."""

    return -(-size_bytes // BYTES_PER_TOKEN)


def source_budget_bytes(model: str, *, instruction_bytes: int) -> int:
    """`model` 한 번의 요청에 소스로 실을 수 있는 바이트 — 컨텍스트에서 응답 몫을 빼고 바이트로
    바꾼 뒤, 소스 말고 프롬프트에 실리는 것(지시문·요구사항·자가 응답, `instruction_bytes`)을 뺀다."""

    return max((context_window_tokens(model) - OUTPUT_RESERVE_TOKENS) * BYTES_PER_TOKEN - instruction_bytes, 0)
