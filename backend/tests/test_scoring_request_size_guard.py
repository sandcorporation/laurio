"""#989: 채점 요청 크기 가드 — 어댑터가 보낼 요청을 그대로 재고, 모델 컨텍스트를 넘으면 벤더를 부르지 않는다.

잰 입력과 보낸 입력이 같아야 한다 — 재는 코드가 따로 있으면 둘이 어긋난다(강의실 문법 검사 덧붙임이 예산 밖에서
붙던 것처럼). 그래서 시험은 「판정에 쓴 페이로드」와 「`requests.post` 에 실린 페이로드」가 같은 객체인지 본다.
벤더가 컨텍스트 초과로 거절해도(400) 같은 「크기 초과」다 — 영구 실패가 아니다.
"""

from __future__ import annotations

import pytest
import requests

from core import llm_scoring
from core import llm_scoring_anthropic as anthropic
from core.llm_scoring import (
    LLMAdapterInputTooLargeError,
    LLMAdapterPermanentError,
    OpenAIScoringAdapter,
    RequirementInput,
    ScoringInput,
    request_size_bytes,
)
from core.model_context import input_token_limit, request_tokens
from tests.classroom_scenarios import FakeVendorResponse, openai_verdicts_body


def _input(prompt: str) -> ScoringInput:
    return ScoringInput(
        submission_id=1,
        contest_id=1,
        prompt=prompt,
        source_files=[],
        requirements=[
            RequirementInput(requirement_id=10, text="로그인", grade="required", self_reported_met=False)
        ],
    )


def _over_limit_prompt(model: str) -> str:
    # 한글 한 글자 = 3바이트 = 토큰 하나로 어림한다 — 한도보다 한 글자 많게.
    return "가" * (input_token_limit(model) + 1)


def _spy_measure(monkeypatch) -> list[object]:
    measured: list[object] = []
    real = llm_scoring.ensure_request_fits

    def spy(model, payload, **kwargs):
        measured.append(payload)
        return real(model, payload, **kwargs)

    monkeypatch.setattr(llm_scoring, "ensure_request_fits", spy)
    monkeypatch.setattr(anthropic, "ensure_request_fits", spy)
    return measured


def test_the_measured_request_is_the_request_that_is_sent(monkeypatch):
    measured = _spy_measure(monkeypatch)
    sent: list[object] = []

    def post(url, **kwargs):
        sent.append(kwargs["json"])
        return FakeVendorResponse(200, openai_verdicts_body([{"requirement_id": 10, "is_met": True, "reasoning": "ok"}]))

    monkeypatch.setattr(requests, "post", post)

    OpenAIScoringAdapter(api_key="sk-test", model="gpt-4o-mini").score(_input("소스 " * 100))

    assert len(measured) == 1 and len(sent) == 1
    assert measured[0] is sent[0]
    assert request_size_bytes(measured[0]) == request_size_bytes(sent[0])


def test_the_anthropic_measured_request_is_the_request_that_is_sent(monkeypatch):
    measured = _spy_measure(monkeypatch)
    sent: list[object] = []

    def post(url, **kwargs):
        sent.append(kwargs["json"])
        return FakeVendorResponse(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "x"}})

    monkeypatch.setattr(requests, "post", post)

    with pytest.raises(LLMAdapterPermanentError):
        anthropic.AnthropicScoringAdapter(api_key="sk-ant-test", model="claude-haiku-5-5").score(_input("소스"))

    assert len(measured) == 1 and measured[0] is sent[0]


def test_the_measure_counts_the_system_prompt_and_the_response_schema():
    adapter = OpenAIScoringAdapter(api_key="sk-test", model="gpt-4o-mini")
    scoring_input = _input("프롬프트")

    assert adapter.request_bytes(scoring_input) > len("프롬프트".encode("utf-8")) + len(
        llm_scoring._OPENAI_SYSTEM_PROMPT.encode("utf-8")
    )


def test_a_request_over_the_model_context_is_not_sent(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("넘치는 요청을 보냈다"))

    with pytest.raises(LLMAdapterInputTooLargeError) as raised:
        OpenAIScoringAdapter(api_key="sk-test", model="gpt-4o-mini").score(_input(_over_limit_prompt("gpt-4o-mini")))

    assert raised.value.limit_tokens == input_token_limit("gpt-4o-mini")
    assert raised.value.request_tokens > raised.value.limit_tokens
    assert not isinstance(raised.value, LLMAdapterPermanentError)


def test_an_anthropic_request_over_the_model_context_is_not_sent(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("넘치는 요청을 보냈다"))
    monkeypatch.setattr("core.model_context.input_token_limit", lambda model: 1_000)

    with pytest.raises(LLMAdapterInputTooLargeError):
        anthropic.AnthropicScoringAdapter(api_key="sk-ant-test", model="claude-haiku-5-5").score(
            _input("가" * 2_000)
        )


def test_the_estimate_is_at_least_characters_over_three():
    for text in ("abc" * 100, "가나다" * 100, "def f():\n    return '한글'\n" * 50):
        assert request_tokens(len(text.encode("utf-8"))) >= len(text) / 3


def test_a_custom_server_with_an_unknown_model_is_not_measured(monkeypatch):
    """호환 서버의 표에 없는 모델은 한도를 모른다 — 기본 128K 로 막지 않는다."""

    sent: list[object] = []

    def transport(method, url, **kwargs):
        sent.append(kwargs["json"])
        return FakeVendorResponse(200, openai_verdicts_body([{"requirement_id": 10, "is_met": True, "reasoning": "ok"}]))

    adapter = OpenAIScoringAdapter(
        api_key="", model="my-local-model", base_url="http://llm.example", transport=transport
    )
    adapter.score(_input(_over_limit_prompt("my-local-model")))

    assert len(sent) == 1


def test_openai_context_length_exceeded_is_input_too_large(monkeypatch):
    body = {"error": {"message": "context length exceeded", "type": "invalid_request_error", "code": "context_length_exceeded"}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeVendorResponse(400, body))

    with pytest.raises(LLMAdapterInputTooLargeError) as raised:
        OpenAIScoringAdapter(api_key="sk-test", model="gpt-4o-mini").score(_input("소스"))

    assert not isinstance(raised.value, LLMAdapterPermanentError)


def test_anthropic_prompt_too_long_is_input_too_large(monkeypatch):
    body = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "prompt is too long: 1200000 tokens > 1000000 maximum"},
    }
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeVendorResponse(400, body))

    with pytest.raises(LLMAdapterInputTooLargeError) as raised:
        anthropic.AnthropicScoringAdapter(api_key="sk-ant-test", model="claude-haiku-5-5").score(_input("소스"))

    assert not isinstance(raised.value, LLMAdapterPermanentError)
