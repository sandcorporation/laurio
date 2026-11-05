"""Claude(Anthropic) 채점 어댑터 (#795, ADR-0066).

`tests/test_openai_scoring_adapter.py` 와 같은 예외 — 이 파일은 HTTP API 를 거치지 않는다. 어댑터는
Codemit 의 API 가 아니라 벤더 연동의 요청 모양·응답 검증·오류 분류다. 실제 Anthropic 을 부르지 않는다:
`requests` 를 몽키패치하고, 응답은 공식 문서의 예시 응답 모양(2026-10-28 에 읽었다)으로 만든 녹화본이다.

- 구조화 출력: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- 오류 모양: https://platform.claude.com/docs/en/api/errors · https://platform.claude.com/docs/en/api/rate-limits
- 모델 목록: https://platform.claude.com/docs/en/api/models/list
"""

from __future__ import annotations

import asyncio
import json

import pytest
import requests

from core import llm_scoring_anthropic as anthropic
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterModelRejectedError,
    LLMAdapterPermanentError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    LLMAdapterTimeoutError,
    LLMKeyCheckStatus,
    RequirementInput,
    ScoringInput,
)
from core.safe_outbound import AsyncResponse

SECRET = "__CODEMIT_SECRET_SOURCE__"
INPUT = ScoringInput(
    submission_id=7,
    contest_id=1,
    prompt=f"채점 프롬프트 — {SECRET}",
    source_files=[],
    requirements=[
        RequirementInput(requirement_id=11, text="README", grade="required", self_reported_met=False),
        RequirementInput(requirement_id=12, text="테스트", grade="optional", self_reported_met=False),
    ],
)
VERDICTS = [
    {"requirement_id": 11, "is_met": True, "reasoning": "README 가 있다."},
    {"requirement_id": 12, "is_met": False, "reasoning": "테스트가 없다."},
]


class _Response:
    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def messages_body(verdicts=VERDICTS, *, stop_reason="end_turn", usage=None, thinking=True) -> dict:
    """Messages API 응답의 녹화본 — 사고 블록(display 기본값 omitted 라 비어 있다) 뒤에 text 블록."""

    content = [{"type": "thinking", "thinking": "", "signature": "sig"}] if thinking else []
    content.append({"type": "text", "text": json.dumps({"verdicts": verdicts}, ensure_ascii=False)})
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "usage": usage or {"input_tokens": 1200, "output_tokens": 340},
    }


def error_body(error_type: str, message: str = "", **error) -> dict:
    return {"type": "error", "error": {"type": error_type, "message": message, **error}, "request_id": "req_1"}


def _adapter(**kwargs) -> anthropic.AnthropicScoringAdapter:
    return anthropic.AnthropicScoringAdapter(api_key="sk-ant-test", model="claude-haiku-5-5", **kwargs)


def _post(monkeypatch, status: int, body, calls: list | None = None) -> None:
    def handler(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        return _Response(status, body)

    monkeypatch.setattr(requests, "post", handler)


def test_the_request_asks_for_the_verdict_schema_with_the_native_messages_api(monkeypatch):
    calls: list = []
    _post(monkeypatch, 200, messages_body(), calls)

    _adapter(reasoning_effort="low").score(INPUT)

    [call] = calls
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-ant-test"
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in call["headers"]
    body = call["json"]
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == anthropic.SCORING_MAX_TOKENS
    assert body["messages"] == [{"role": "user", "content": INPUT.prompt}]
    assert body["output_config"]["effort"] == "low"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    item = fmt["schema"]["properties"]["verdicts"]["items"]
    assert item["required"] == ["requirement_id", "is_met", "reasoning"]
    assert item["additionalProperties"] is False and fmt["schema"]["additionalProperties"] is False
    # 구조화 출력은 GA 라 베타 헤더도, 폐기 예정 필드도 싣지 않는다. temperature 는 사고와 함께 쓰지 않는다.
    assert "anthropic-beta" not in call["headers"]
    assert "output_format" not in body and "temperature" not in body and "thinking" not in body


def test_without_an_effort_the_request_carries_no_effort(monkeypatch):
    calls: list = []
    _post(monkeypatch, 200, messages_body(), calls)

    _adapter().score(INPUT)

    assert "effort" not in calls[0]["json"]["output_config"]


def test_the_verdicts_come_from_the_text_block_after_the_thinking_block_with_usage(monkeypatch):
    usage = {"input_tokens": 1000, "cache_read_input_tokens": 50, "output_tokens": 300}
    _post(monkeypatch, 200, messages_body(usage=usage))

    output = _adapter().score(INPUT)

    assert [(v.requirement_id, v.is_met) for v in output.verdicts] == [(11, True), (12, False)]
    assert output.model_version == "claude-haiku-5-5"
    assert (output.input_tokens, output.output_tokens, output.total_tokens) == (1050, 300, 1350)


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal", "model_context_window_exceeded"])
def test_a_cut_or_refused_answer_is_never_a_score(monkeypatch, stop_reason):
    _post(monkeypatch, 200, messages_body(stop_reason=stop_reason))

    with pytest.raises(LLMAdapterPermanentError):
        _adapter().score(INPUT)


def test_a_missing_verdict_fails_the_attempt_without_leaking_the_source(monkeypatch):
    _post(monkeypatch, 200, messages_body(verdicts=VERDICTS[:1]))

    with pytest.raises(LLMAdapterError) as exc:
        _adapter().score(INPUT)
    assert SECRET not in str(exc.value)
    assert "Anthropic" in str(exc.value)


def test_an_answer_without_a_text_block_is_a_failed_attempt(monkeypatch):
    body = messages_body()
    body["content"] = [block for block in body["content"] if block["type"] != "text"]
    _post(monkeypatch, 200, body)

    with pytest.raises(LLMAdapterError):
        _adapter().score(INPUT)


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, error_body("authentication_error", "invalid x-api-key"), LLMAdapterAuthError),
        (403, error_body("permission_error"), LLMAdapterAuthError),
        (404, error_body("not_found_error", "model: claude-x"), LLMAdapterModelRejectedError),
        (402, error_body("billing_error"), LLMAdapterQuotaExhaustedError),
        (
            400,
            error_body("invalid_request_error", "Your credit balance is too low to access the Anthropic API."),
            LLMAdapterQuotaExhaustedError,
        ),
        (
            400,
            error_body("invalid_request_error", "You have reached your specified API usage limits. You will regain access on 2026-11-01."),
            LLMAdapterQuotaExhaustedError,
        ),
        (
            429,
            error_body("rate_limit_error", "monthly threshold", details={"error_code": "enforced_spend_limit_reached"}),
            LLMAdapterQuotaExhaustedError,
        ),
        (429, error_body("rate_limit_error", "Number of request tokens has exceeded your rate limit"), LLMAdapterRateLimitedError),
        (529, error_body("overloaded_error", "Overloaded"), LLMAdapterRateLimitedError),
        (400, error_body("invalid_request_error", "max_tokens: too large"), LLMAdapterPermanentError),
        (500, error_body("api_error"), LLMAdapterError),
    ],
)
def test_error_responses_fall_into_the_existing_classes(monkeypatch, status, body, error):
    _post(monkeypatch, status, body)

    with pytest.raises(error) as exc:
        _adapter().score(INPUT)
    assert type(exc.value) is error
    # 벤더의 자유 텍스트는 예외 메시지에 싣지 않는다(ADR-0014) — 상태와 고정 라벨만.
    assert body["error"]["message"] == "" or body["error"]["message"] not in str(exc.value)
    assert f"status={status}" in str(exc.value)


def test_a_timeout_is_a_timeout_and_a_network_error_is_a_failed_attempt(monkeypatch):
    def timeout(url, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(requests, "post", timeout)
    with pytest.raises(LLMAdapterTimeoutError):
        _adapter().score(INPUT)

    def broken(url, **kwargs):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", broken)
    with pytest.raises(LLMAdapterError):
        _adapter().score(INPUT)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, LLMKeyCheckStatus.VALID), (401, LLMKeyCheckStatus.REJECTED), (403, LLMKeyCheckStatus.REJECTED), (500, LLMKeyCheckStatus.UNVERIFIED)],
)
def test_the_key_check_reads_the_models_endpoint(monkeypatch, status, expected):
    calls: list = []

    def handler(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Response(status, anthropic.FAKE_MODELS_BODY if status == 200 else error_body("x"))

    monkeypatch.setattr(requests, "get", handler)

    assert _adapter().check_key() == expected
    assert calls[0]["url"] == "https://api.anthropic.com/v1/models"
    assert calls[0]["headers"]["x-api-key"] == "sk-ant-test"


def test_the_key_check_that_cannot_reach_anthropic_is_unverified(monkeypatch):
    def broken(url, **kwargs):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", broken)

    assert _adapter().check_key() == LLMKeyCheckStatus.UNVERIFIED


def test_the_model_list_keeps_haiku_and_sonnet_that_take_the_schema_and_effort(monkeypatch):
    calls: list = []

    def handler(url, **kwargs):
        calls.append(url)
        return _Response(200, anthropic.FAKE_MODELS_BODY)

    monkeypatch.setattr(requests, "get", handler)

    ids = anthropic.list_anthropic_scoring_models("sk-ant-test")

    # Opus(비용)와 effort 를 받지 않는 Haiku 4.5 는 빠진다. 계열은 id 가 아니라 `line` 으로 본다.
    assert ids == ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-sonnet-5"]
    assert calls == ["https://api.anthropic.com/v1/models?limit=1000"]


def test_a_failed_model_list_is_none(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: _Response(401, error_body("authentication_error")))

    assert anthropic.list_anthropic_scoring_models("sk-ant-bad") is None


def test_the_async_path_sends_the_same_request_and_classifies_the_same_way():
    seen: list = []

    def respond(status, body):
        async def transport(method, url, *, headers, timeout, json=None):
            seen.append((method, url, headers, json))
            return AsyncResponse(status, (body if isinstance(body, bytes) else jsonlib_dumps(body)))

        return transport

    output = asyncio.run(_adapter(async_transport=respond(200, messages_body())).score_async(INPUT))
    assert [v.requirement_id for v in output.verdicts] == [11, 12]
    method, url, headers, body = seen[0]
    assert (method, url, headers["x-api-key"]) == ("POST", "https://api.anthropic.com/v1/messages", "sk-ant-test")
    assert body["output_config"]["format"]["type"] == "json_schema"

    with pytest.raises(LLMAdapterQuotaExhaustedError):
        asyncio.run(_adapter(async_transport=respond(402, error_body("billing_error"))).score_async(INPUT))


def jsonlib_dumps(body) -> bytes:
    return json.dumps(body).encode("utf-8")


def test_with_unverifiable_the_schema_asks_for_three_verdicts_and_reads_them(monkeypatch):
    calls: list = []
    verdicts = [
        {"requirement_id": 11, "verdict": "met", "reasoning": "README 가 있다."},
        {"requirement_id": 12, "verdict": "unverifiable", "reasoning": "실행해야 안다."},
    ]
    _post(monkeypatch, 200, messages_body(verdicts), calls)

    output = _adapter(allow_unverifiable=True).score(INPUT)

    item = calls[0]["json"]["output_config"]["format"]["schema"]["properties"]["verdicts"]["items"]
    assert item["required"] == ["requirement_id", "verdict", "reasoning"]
    assert item["properties"]["verdict"]["enum"] == ["met", "unmet", "unverifiable"]
    assert [(v.is_met, v.verdict) for v in output.verdicts] == [(True, "met"), (False, "unverifiable")]
