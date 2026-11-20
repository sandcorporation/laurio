"""에이전트 채점 키 프록시 `llm-proxy`(#998) — 실행 토큰·모델 제한·실행 예산·하루 상한·키 가리기·스트리밍.

시임은 프록시의 HTTP 경계다: 가짜 벤더 서버(aiohttp)를 띄우고 프록시 앱을 그 앞에 세워 에이전트가 하듯
요청을 보낸다. 토큰은 채점기가 쓸 공개 함수(`issue_run_token`)로 발급한다.

비동기 본문은 `async_to_sync` 로 돌린다 — 그래야 프록시 안의 `sync_to_async` 가 시험 스레드(같은 DB
연결·같은 시험 트랜잭션)에서 돈다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from asgiref.sync import async_to_sync

from core.agent_run_tokens import (
    DEFAULT_RUN_BUDGET_USD,
    RunTokenRefused,
    issue_run_token,
    run_usage,
    spent_today_usd,
)
from core.clock import Clock
from core.llm_proxy import Upstreams, build_app
from core.models import AgentRunToken, ClockOverride
from policies.runtime_settings import agent_scoring_daily_limit_usd

pytestmark = pytest.mark.django_db

ANTHROPIC_KEY = "sk-ant-real-proxy-key-0000000000000000abcd"  # leak-guard:allow — 가짜 키
OPENAI_KEY = "sk-real-proxy-openai-key-00000000000000wxyz"  # leak-guard:allow — 가짜 키
SONNET = "claude-sonnet-5-5"
GPT = "gpt-5-mini"


@pytest.fixture(autouse=True)
def _env(monkeypatch, settings):
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("OPEN_AI_API_KEY", OPENAI_KEY)
    monkeypatch.delenv("AGENT_SCORING_DAILY_LIMIT_USD", raising=False)
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = date(2000, 1, 1)


# --- 가짜 벤더 -------------------------------------------------------------------------------------


@dataclass
class FakeVendor:
    """Anthropic `/v1/messages`·OpenAI `/v1/responses` 흉내. 실제 벤더처럼 `stream: true` 일 때만 SSE 로,
    아니면 JSON 으로 답하고, 둘 다 usage 를 준다. `fail_status` 면 키를 되돌려 적은 오류를 낸다."""

    requests: list[tuple[str, dict[str, str], dict[str, object]]] = field(default_factory=list)
    usage_input: int = 1000
    usage_output: int = 200
    fail_status: int | None = None

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/v1/messages", self._anthropic)
        app.router.add_post("/v1/responses", self._openai)
        return app

    async def _record(self, request: web.Request) -> dict[str, object]:
        body = await request.json()
        self.requests.append((request.path_qs, dict(request.headers), body))
        return body

    def _fail(self, key: str) -> web.Response:
        assert self.fail_status is not None
        return web.json_response(
            {"error": {"message": f"Incorrect API key provided: {key}. sk-proj-abcdefgh1234****wxyz"}},
            status=self.fail_status,
        )

    async def _anthropic(self, request: web.Request) -> web.StreamResponse:
        body = await self._record(request)
        if self.fail_status:
            return self._fail(request.headers.get("x-api-key", ""))
        usage = {
            "input_tokens": self.usage_input,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 5000,
            "output_tokens": 1,
        }
        if not body.get("stream"):
            plain = web.json_response({"type": "message", "usage": {**usage, "output_tokens": self.usage_output}})
            plain.enable_compression()  # 실제 벤더처럼 Accept-Encoding 이 허락하면 gzip 으로 답한다(#1666)
            return plain
        response = web.StreamResponse(headers={"content-type": "text/event-stream"})
        response.enable_compression()
        await response.prepare(request)
        events = [
            {"type": "message_start", "message": {"model": body.get("model"), "usage": usage}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "안녕"}},
            {"type": "message_delta", "usage": {"output_tokens": self.usage_output}},
            {"type": "message_stop"},
        ]
        for event in events:
            await response.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
        await response.write_eof()
        return response

    async def _openai(self, request: web.Request) -> web.StreamResponse:
        body = await self._record(request)
        if self.fail_status:
            return self._fail(request.headers.get("authorization", ""))
        usage = {
            "input_tokens": self.usage_input,
            "input_tokens_details": {"cached_tokens": 100},
            "output_tokens": self.usage_output,
        }
        if not body.get("stream"):
            plain = web.json_response({"object": "response", "usage": usage})
            plain.enable_compression()
            return plain
        response = web.StreamResponse(headers={"content-type": "text/event-stream"})
        response.enable_compression()
        await response.prepare(request)
        events = [
            {"type": "response.created", "response": {"usage": None}},
            {"type": "response.output_text.delta", "delta": "hi"},
            {"type": "response.completed", "response": {"usage": usage}},
        ]
        for event in events:
            await response.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
        await response.write_eof()
        return response


@asynccontextmanager
async def _stack(vendor: FakeVendor) -> AsyncIterator[TestClient]:
    async with TestServer(vendor.app()) as fake:
        base = str(fake.make_url("")).rstrip("/")
        async with TestClient(TestServer(build_app(Upstreams(anthropic=base, openai=base)))) as client:
            yield client


def _run(vendor: FakeVendor, body: Callable[[TestClient], Awaitable[None]]) -> None:
    async def main() -> None:
        async with _stack(vendor) as client:
            await body(client)

    async_to_sync(main)()


def _claude(token: str | None, *, model: str = SONNET, stream: bool = True) -> dict[str, object]:
    headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    if token is not None:
        headers["x-api-key"] = token
    return {"headers": headers, "json": {"model": model, "stream": stream, "messages": []}}


def _codex(token: str | None, *, model: str = GPT, stream: bool = True) -> dict[str, object]:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return {"headers": headers, "json": {"model": model, "stream": stream, "input": []}}


def _issue(vendor: str = "anthropic", model: str = SONNET, budget: Decimal = DEFAULT_RUN_BUDGET_USD):
    return issue_run_token(submission_id=7, purpose="scoring", vendor=vendor, model=model, budget_usd=budget)


# --- 거절 ------------------------------------------------------------------------------------------


def test_without_issued_tokens_nothing_reaches_the_vendor():
    """기본 설정(토큰을 발급하는 쪽이 없음)으로 떠 있어도 어떤 요청도 벤더로 나가지 않는다."""

    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        statuses = [
            (await client.post("/v1/messages", **_claude(None))).status,
            (await client.post("/v1/messages", **_claude("cmrt_guess"))).status,
            (await client.post("/v1/messages", **_claude(ANTHROPIC_KEY))).status,
            (await client.post("/v1/responses", **_codex(None))).status,
            (await client.post("/v1/responses", **_codex(OPENAI_KEY))).status,
            (await client.post("/v1/chat/completions", **_codex("x"))).status,
        ]
        assert statuses == [401, 401, 401, 401, 401, 404]

    _run(vendor, body)
    assert vendor.requests == []


def test_expired_token_is_refused():
    issued = _issue()
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": Clock.now() + timedelta(minutes=16)})
    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        response = await client.post("/v1/messages", **_claude(issued.token))
        assert response.status == 401
        assert (await response.json())["error"]["type"] == "expired"

    _run(vendor, body)
    assert vendor.requests == []


def test_other_model_and_other_vendor_are_refused():
    issued = _issue()
    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        other_model = await client.post("/v1/messages", **_claude(issued.token, model="claude-haiku-5-5"))
        assert other_model.status == 403
        assert (await other_model.json())["error"]["type"] == "wrong_model"
        other_vendor = await client.post("/v1/responses", **_codex(issued.token, model=SONNET))
        assert other_vendor.status == 403
        assert (await other_vendor.json())["error"]["type"] == "wrong_vendor"

    _run(vendor, body)
    assert vendor.requests == []


def test_run_budget_exceeded_is_refused_with_429():
    # 입력 100만 토큰 = $2(sonnet 5.5) — 예산 $1 을 첫 응답으로 넘는다.
    issued = _issue(budget=Decimal("1"))
    vendor = FakeVendor(usage_input=1_000_000)

    async def body(client: TestClient) -> None:
        assert (await client.post("/v1/messages", **_claude(issued.token))).status == 200
        second = await client.post("/v1/messages", **_claude(issued.token))
        assert second.status == 429
        assert (await second.json())["error"]["type"] == "run_budget"

    _run(vendor, body)
    assert len(vendor.requests) == 1


def test_daily_limit_is_refused_with_429(monkeypatch):
    monkeypatch.setenv("AGENT_SCORING_DAILY_LIMIT_USD", "0.5")
    first = _issue(vendor="openai", model=GPT)
    second = _issue(vendor="openai", model=GPT)
    # 입력 100만 토큰 = $0.25 + 출력 20만 = $0.4(gpt-5-mini) — 첫 실행이 하루 상한 $0.5 를 넘는다.
    vendor = FakeVendor(usage_input=1_000_000, usage_output=200_000)

    async def body(client: TestClient) -> None:
        assert (await client.post("/v1/responses", **_codex(first.token))).status == 200
        refused = await client.post("/v1/responses", **_codex(second.token))
        assert refused.status == 429
        assert (await refused.json())["error"]["type"] == "daily_limit"

    _run(vendor, body)
    assert len(vendor.requests) == 1


def test_class_key_runs_are_neither_counted_in_nor_stopped_by_the_platform_daily_limit(monkeypatch):
    """#1036: 클래스 키 실행은 그 클래스 소유자의 돈이다 — 플랫폼 하루 합계에 들지 않고 그 상한에 막히지 않는다."""

    monkeypatch.setenv("AGENT_SCORING_DAILY_LIMIT_USD", "0.5")
    # 이 클래스는 없다 — 프록시는 키를 못 찾아 503 이지만, 상한 검사는 그 앞에서 끝난다.
    over = issue_run_token(submission_id=7, purpose="scoring", vendor="openai", model=GPT, key_class_id=987654)
    AgentRunToken.objects.filter(pk=over.record_id).update(spent_usd=Decimal("0.9"))
    platform = _issue(vendor="openai", model=GPT)

    assert spent_today_usd() == 0
    assert spent_today_usd(key_class_id=987654) == Decimal("0.9")
    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        assert (await client.post("/v1/responses", **_codex(platform.token))).status == 200

    _run(vendor, body)
    assert len(vendor.requests) == 1


def test_a_class_token_never_falls_back_to_the_platform_key():
    """#1036: 클래스 키를 못 풀면(없는 클래스·다른 벤더 연결) 503 이다 — 플랫폼 키로 대신 나가지 않는다."""

    issued = issue_run_token(submission_id=7, purpose="scoring", vendor="anthropic", model=SONNET, key_class_id=987654)
    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        response = await client.post("/v1/messages", **_claude(issued.token))
        assert response.status == 503
        assert (await response.json())["error"]["type"] == "vendor_key_missing"

    _run(vendor, body)
    assert vendor.requests == []


# --- 키 ------------------------------------------------------------------------------------------


def test_real_key_goes_only_to_the_vendor_never_back(caplog):
    caplog.set_level(logging.DEBUG)
    issued = _issue()
    vendor = FakeVendor(fail_status=401)
    seen: dict[str, str] = {}

    async def body(client: TestClient) -> None:
        response = await client.post("/v1/messages", **_claude(issued.token))
        seen["status"] = str(response.status)
        seen["body"] = await response.text()
        seen["headers"] = json.dumps(dict(response.headers))

    _run(vendor, body)
    assert seen["status"] == "401"
    (_path, headers, _body), = vendor.requests
    assert headers["x-api-key"] == ANTHROPIC_KEY
    assert issued.token not in json.dumps(headers)
    for text in (seen["body"], seen["headers"], caplog.text):
        assert ANTHROPIC_KEY not in text
        assert "sk-proj-abcdefgh" not in text
        assert issued.token not in text
    assert "[redacted]" in seen["body"]


def test_codex_key_is_bearer_to_the_vendor():
    issued = _issue(vendor="openai", model=GPT)
    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        assert (await client.post("/v1/responses?x=1", **_codex(issued.token, stream=False))).status == 200

    _run(vendor, body)
    (path, headers, _body), = vendor.requests
    assert path == "/v1/responses?x=1"
    assert headers["Authorization"] == f"Bearer {OPENAI_KEY}"


# --- 스트리밍·사용량 ------------------------------------------------------------------------------


def test_claude_stream_passes_through_and_usage_is_recorded():
    issued = _issue()
    vendor = FakeVendor(usage_input=1000, usage_output=200)
    got: dict[str, str] = {}

    async def body(client: TestClient) -> None:
        response = await client.post("/v1/messages?beta=true", **_claude(issued.token))
        assert response.status == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        got["text"] = await response.text()

    _run(vendor, body)
    assert got["text"].count("data: ") == 4
    assert '"message_stop"' in got["text"]
    assert vendor.requests[0][0] == "/v1/messages?beta=true"
    usage = run_usage(issued.record_id)
    assert (usage.request_count, usage.usage.input_tokens, usage.usage.output_tokens) == (1, 1000, 200)
    assert usage.usage.cache_read_tokens == 5000
    # 1000×$2 + 200×$10 + 5000×$2×0.1 (/100만) = 0.002 + 0.002 + 0.001
    assert usage.spent_usd == Decimal("0.005")


@pytest.mark.parametrize("stream", [True, False])
def test_vendor_is_asked_for_identity_so_the_cli_gets_plain_bytes(stream):
    """#1666 — 압축된 답을 Content-Encoding 없이 넘기면 CLI 가 `\x1f` 를 JSON 으로 읽다 죽는다."""
    issued = _issue()
    vendor = FakeVendor(usage_input=1000, usage_output=200)
    got: dict[str, bytes] = {}

    async def body(client: TestClient) -> None:
        response = await client.post("/v1/messages", **_claude(issued.token, stream=stream))
        assert response.status == 200
        got["raw"] = await response.read()
        got["encoding"] = response.headers.get("content-encoding", "").encode()

    _run(vendor, body)
    assert vendor.requests[0][1]["Accept-Encoding"] == "identity"
    assert not got["raw"].startswith(b"\x1f")
    assert got["encoding"] == b""
    assert b"usage" in got["raw"]
    assert run_usage(issued.record_id).usage.output_tokens == 200


def test_codex_stream_usage_is_recorded_and_summed():
    issued = _issue(vendor="openai", model=GPT)
    vendor = FakeVendor(usage_input=4000, usage_output=1000)

    async def body(client: TestClient) -> None:
        for _ in range(2):
            response = await client.post("/v1/responses", **_codex(issued.token))
            assert response.status == 200
            assert "response.completed" in await response.text()

    _run(vendor, body)
    usage = run_usage(issued.record_id)
    assert (usage.request_count, usage.usage.input_tokens, usage.usage.output_tokens) == (2, 8000, 2000)
    # 2 × (4000×$0.25 + 1000×$2) / 100만
    assert usage.spent_usd == Decimal("0.006")


# --- 발급 ----------------------------------------------------------------------------------------


def test_anthropic_token_is_issued_whatever_the_policy_date(settings):
    """대표 결정(2026-11-20): 방침 시행일로 막지 않는다."""
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = None
    assert _issue().token.startswith("cmrt_")


def test_unknown_price_model_is_not_issued():
    with pytest.raises(RunTokenRefused):
        _issue(vendor="openai", model="gpt-unknown-model")


def test_daily_limit_defaults_to_20_usd(monkeypatch):
    assert agent_scoring_daily_limit_usd() == Decimal("20")
    monkeypatch.setenv("AGENT_SCORING_DAILY_LIMIT_USD", "nope")
    assert agent_scoring_daily_limit_usd() == Decimal("20")
    monkeypatch.setenv("AGENT_SCORING_DAILY_LIMIT_USD", "3.5")
    assert agent_scoring_daily_limit_usd() == Decimal("3.5")


# --- 운영 설정 ------------------------------------------------------------------------------------

OPERATOR_URL = "/api/operator/runtime-settings"
OPERATOR_PW = "operator-pw-llm-proxy-998-zzz"


def test_operator_sets_the_daily_limit_and_the_proxy_follows_it(monkeypatch, django_capture_on_commit_callbacks):
    from django.core.management import call_command
    from django.test import Client

    origin = "http://testserver"
    call_command("create_operator", "proxy_super", password=OPERATOR_PW, superuser=True)
    su = Client()
    login = su.post(
        "/api/operator/login",
        data={"username": "proxy_super", "password": OPERATOR_PW},
        content_type="application/json",
        HTTP_ORIGIN=origin,
    )
    assert login.status_code == 200
    views = {s["key"]: s for s in su.get(OPERATOR_URL, HTTP_ORIGIN=origin).json()["settings"]}
    row = views["AGENT_SCORING_DAILY_LIMIT_USD"]
    assert (row["kind"], row["default"], row["source"]) == ("float", "20", "none")

    with django_capture_on_commit_callbacks(execute=True):
        saved = su.post(
            f"{OPERATOR_URL}/AGENT_SCORING_DAILY_LIMIT_USD",
            data={"value": "0"},
            content_type="application/json",
            HTTP_ORIGIN=origin,
        )
    assert saved.status_code == 200
    assert agent_scoring_daily_limit_usd() == Decimal("0")

    issued = _issue(vendor="openai", model=GPT)
    vendor = FakeVendor()

    async def body(client: TestClient) -> None:
        refused = await client.post("/v1/responses", **_codex(issued.token))
        assert refused.status == 429
        assert (await refused.json())["error"]["type"] == "daily_limit"

    _run(vendor, body)
    assert vendor.requests == []
