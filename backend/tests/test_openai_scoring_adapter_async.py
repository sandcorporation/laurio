"""OpenAI 채점 어댑터의 비동기 판 `score_async` (#584, ADR-0059).

grader 가 강의실 채점에 쓴다. 요청 모양·응답 분류는 동기 `score` 와 같은 함수를 쓰므로 여기서는
**길만** 본다: 같은 요청이 나가고, 같은 갈래로 분류되고, 네트워크 실패는 실패 시도(`LLMAdapterError`)
이며 호환 서버가 못 닿으면 「연결 불가」다. OpenAI 로 나가는 기본 길(`_aiohttp_request`)은 127.0.0.1
의 로컬 서버로 본다 — 실제 OpenAI 로 나가지 않는다.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import json as jsonlib
import threading

import aiohttp
import pytest

from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    LLMAdapterUnreachableError,
    OpenAIScoringAdapter,
    RequirementInput,
    ScoringInput,
)
from core.safe_outbound import AsyncResponse, OutboundReason, OutboundRefused
from tests.classroom_scenarios import openai_verdicts_body

INPUT = ScoringInput(
    submission_id=7,
    contest_id=1,
    prompt="채점 프롬프트",
    source_files=[],
    requirements=[RequirementInput(requirement_id=11, text="README 가 있다", grade="required", self_reported_met=False, evidence=[])],
)
VERDICTS = [{"requirement_id": 11, "is_met": True, "reasoning": "있다"}]


def _adapter(transport, **kwargs) -> OpenAIScoringAdapter:
    return OpenAIScoringAdapter(
        api_key="sk-test", model="gpt-4o-mini", base_url="https://api.example.test/v1", async_transport=transport, **kwargs
    )


def _respond(status: int, body) -> object:
    async def transport(method, url, *, headers, timeout, json=None):
        transport.seen = {"method": method, "url": url, "headers": headers, "timeout": timeout, "json": json}
        return AsyncResponse(status, body if isinstance(body, bytes) else jsonlib.dumps(body).encode())

    return transport


def _score(adapter):
    return asyncio.run(adapter.score_async(INPUT))


def test_a_success_response_becomes_the_same_output_as_the_sync_path():
    transport = _respond(200, openai_verdicts_body(VERDICTS, total_tokens=321))

    output = _score(_adapter(transport, timeout=180))

    assert [(v.requirement_id, v.is_met) for v in output.verdicts] == [(11, True)]
    assert output.total_tokens == 321
    seen = transport.seen
    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["timeout"] == 180
    assert seen["json"]["model"] == "gpt-4o-mini" and seen["json"]["temperature"] == 0


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {"error": {"type": "invalid_request_error", "code": "invalid_api_key"}}, LLMAdapterAuthError),
        (429, {"error": {"type": "insufficient_quota", "code": "insufficient_quota"}}, LLMAdapterQuotaExhaustedError),
        (429, {"error": {"type": "requests", "code": "rate_limit_exceeded"}}, LLMAdapterRateLimitedError),
        (500, {"error": {}}, LLMAdapterError),
    ],
)
def test_error_responses_are_classified_like_the_sync_path(status, body, error):
    with pytest.raises(error):
        _score(_adapter(_respond(status, body)))


def test_a_body_that_is_not_json_is_a_failed_attempt():
    with pytest.raises(LLMAdapterError):
        _score(_adapter(_respond(200, b"<html>")))


def test_a_transport_that_cannot_reach_the_server_is_unreachable_but_a_late_answer_is_a_failure():
    def refusing(reason):
        async def transport(*args, **kwargs):
            raise OutboundRefused(reason)

        return transport

    with pytest.raises(LLMAdapterUnreachableError):
        _score(_adapter(refusing(OutboundReason.DNS_FAILED)))
    with pytest.raises(LLMAdapterError) as late:
        _score(_adapter(refusing(OutboundReason.RESPONSE_FAILED)))
    assert not isinstance(late.value, LLMAdapterUnreachableError)


def test_a_network_error_in_the_default_path_is_a_failed_attempt_not_an_escape():
    async def broken(*args, **kwargs):
        raise aiohttp.ClientConnectionError("boom")

    with pytest.raises(LLMAdapterError):
        _score(_adapter(broken))


# --- OpenAI 로 나가는 기본 길 — 로컬 서버로 ------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        self.server.requests.append({"path": self.path, "auth": self.headers["Authorization"], "json": request})
        payload = json.dumps(openai_verdicts_body(VERDICTS, total_tokens=5)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_the_default_path_posts_json_with_the_bearer_header():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        adapter = OpenAIScoringAdapter(
            api_key="sk-local", model="gpt-4o-mini", base_url=f"http://127.0.0.1:{server.server_address[1]}/v1"
        )
        output = asyncio.run(adapter.score_async(INPUT))
    finally:
        server.shutdown()

    assert output.total_tokens == 5
    [request] = server.requests
    assert request["path"] == "/v1/chat/completions"
    assert request["auth"] == "Bearer sk-local"
    assert request["json"]["messages"][1]["content"] == "채점 프롬프트"
