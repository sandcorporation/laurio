"""에이전트 채점 키 프록시 `llm-proxy`(#998) — 실행 토큰을 받아 진짜 벤더 키를 붙여 넘긴다.

에이전트 컨테이너(`agent-grader`)는 진짜 키 대신 실행 토큰과 `base_url=http://llm-proxy:8002` 만 받는다.
이 프로세스(신뢰 영역)가 요청마다:

1. 토큰을 꺼낸다 — Anthropic 은 `x-api-key`(또는 `Authorization: Bearer`), OpenAI 는 `Authorization: Bearer`.
2. `core.agent_run_tokens.authorize` 로 토큰·만료·벤더·모델(토큰의 모델만)·실행 예산·하루 합계를 본다.
   거절이면 401·403·429 와 이유(JSON)를 돌려주고 벤더로는 아무것도 보내지 않는다.
3. 진짜 키(런타임 설정 `ANTHROPIC_API_KEY`·`OPEN_AI_API_KEY`)를 붙여 벤더로 보내고, 응답을 **그대로 흘려보낸다**
   (스트리밍 포함). 흘려보내면서 usage 를 읽어 끝난 뒤 그 토큰 행에 더한다.

경로는 둘뿐이다: Anthropic `POST /v1/messages`(Claude Code 의 `ANTHROPIC_BASE_URL`), OpenAI
`POST /v1/responses`(Codex 사용자 provider `wire_api="responses"`). 나머지는 404.

**키 꼴 문자열은 로그·응답에 남기지 않는다.** 이 프로세스가 만드는 로그 줄에는 토큰 행 id·상태·비용만
들어간다. 벤더의 오류 응답(2xx 가 아닌 것)은 벤더가 키 일부를 되돌려 적는 일이 있어(OpenAI 의
「Incorrect API key provided: sk-…」) 통째로 읽어 진짜 키와 키 꼴 문자열을 가린 뒤 돌려준다.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal

import aiohttp
from aiohttp import web
from asgiref.sync import sync_to_async
from django.db import close_old_connections, connection

# 클래스 키 실행(#1036)의 키는 강의실 채점 연결(`classroom.scoring_connection`)이 쥔 암호문이다 — 복호화를 그 모듈 한 곳에
# 두고, 강의실이 등록한다(#1085).
from core.agent_ports import class_vendor_key
from core.agent_run_tokens import Grant, Refusal, Usage, authorize, record_usage
from core.runtime_settings_port import ScoringVendor, setting_value

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8002
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com"

#: 요청 본문 상한 — 에이전트가 읽은 파일이 대화에 쌓이므로 넉넉히(Claude 의 1M 컨텍스트 ≈ 4MB 글자).
MAX_REQUEST_BYTES = 16 * 1024 * 1024
#: 벤더 오류 응답을 가리려고 읽는 상한.
MAX_ERROR_BYTES = 64 * 1024
#: 벤더 호출 하나의 상한 — 실행 하나의 상한(10분)과 같다.
UPSTREAM_TIMEOUT_SECONDS = 600

_KEY_SETTING: dict[ScoringVendor, str] = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPEN_AI_API_KEY"}
#: 벤더로 넘기는 요청 헤더(소문자). 인증 헤더는 넘기지 않고 프록시가 새로 붙인다.
_FORWARD_REQUEST_HEADERS = frozenset(
    {"content-type", "accept", "anthropic-version", "anthropic-beta", "openai-beta", "user-agent"}
)
#: 돌려주는 응답 헤더(소문자).
_FORWARD_RESPONSE_HEADERS = frozenset({"content-type", "cache-control", "request-id", "x-request-id"})
#: 키 꼴 문자열 — OpenAI(`sk-…`, `sk-proj-…`)·Anthropic(`sk-ant-…`)과 실행 토큰(`cmrt_…`).
_KEY_SHAPED = re.compile(r"(?:sk-[A-Za-z0-9_\-*]{6,}|cmrt_[A-Za-z0-9_\-]{6,})")
_REDACTED = "[redacted]"
_DUMPS = functools.partial(json.dumps, ensure_ascii=False)
_SESSION_KEY = web.AppKey("llm_proxy_session", aiohttp.ClientSession)


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """진짜 키와 키 꼴 문자열을 가린다."""

    for secret in secrets:
        if secret:
            text = text.replace(secret, _REDACTED)
    return _KEY_SHAPED.sub(_REDACTED, text)


@dataclass(frozen=True)
class Upstreams:
    anthropic: str = ANTHROPIC_DEFAULT_BASE_URL
    openai: str = OPENAI_DEFAULT_BASE_URL

    def base_for(self, vendor: ScoringVendor) -> str:
        return (self.anthropic if vendor == "anthropic" else self.openai).rstrip("/")


@dataclass
class UsageMeter:
    """흘려보내는 응답에서 usage 를 읽는다 — SSE(`data: {...}` 줄)와 JSON 본문 둘 다.

    - Anthropic: 스트림의 `message_start.message.usage`(입력·캐시)와 `message_delta.usage`(출력 누적),
      JSON 본문은 맨 위 `usage`.
    - OpenAI Responses: 스트림의 `response.completed`(또는 `.incomplete`·`.failed`) 의 `response.usage`,
      JSON 본문은 맨 위 `usage`.
    """

    vendor: ScoringVendor
    streaming: bool
    _pending: bytes = b""
    _body: bytearray = field(default_factory=bytearray)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seen: bool = False

    def feed(self, chunk: bytes) -> None:
        if not self.streaming:
            if len(self._body) < MAX_REQUEST_BYTES:
                self._body.extend(chunk)
            return
        self._pending += chunk
        *lines, self._pending = self._pending.split(b"\n")
        for line in lines:
            self._line(line)

    def finish(self) -> Usage | None:
        if self.streaming:
            if self._pending:
                self._line(self._pending)
                self._pending = b""
        else:
            event = _json_object(bytes(self._body))
            if event is not None:
                self._take(event.get("usage"))
        if not self.seen:
            return None
        return Usage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
        )

    def _line(self, line: bytes) -> None:
        line = line.strip()
        if not line.startswith(b"data:"):
            return
        event = _json_object(line[5:].strip())
        if event is None:
            return
        kind = event.get("type")
        if self.vendor == "anthropic":
            if kind == "message_start":
                message = event.get("message")
                if isinstance(message, dict):
                    self._take(message.get("usage"))
            elif kind == "message_delta":
                self._take(event.get("usage"))
        elif kind in {"response.completed", "response.incomplete", "response.failed"}:
            response = event.get("response")
            if isinstance(response, dict):
                self._take(response.get("usage"))

    def _take(self, usage: object) -> None:
        if not isinstance(usage, dict):
            return
        self.seen = True
        # 같은 응답 안의 값은 누적값이다(Anthropic message_delta 의 output_tokens) — 큰 쪽을 남긴다.
        self.input_tokens = max(self.input_tokens, _int(usage.get("input_tokens")))
        self.output_tokens = max(self.output_tokens, _int(usage.get("output_tokens")))
        if self.vendor == "anthropic":
            self.cache_read_tokens = max(self.cache_read_tokens, _int(usage.get("cache_read_input_tokens")))
            self.cache_write_tokens = max(self.cache_write_tokens, _int(usage.get("cache_creation_input_tokens")))
        else:
            details = usage.get("input_tokens_details")
            if isinstance(details, dict):
                self.cache_read_tokens = max(self.cache_read_tokens, _int(details.get("cached_tokens")))


def _int(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _json_object(raw: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _refusal_response(refusal: Refusal) -> web.Response:
    return web.json_response(
        {"type": "error", "error": {"type": refusal.code, "message": refusal.message}}, status=refusal.status, dumps=_DUMPS
    )


def _token_from(request: web.Request, vendor: ScoringVendor) -> str | None:
    if vendor == "anthropic":
        api_key = request.headers.get("x-api-key", "").strip()
        if api_key:
            return api_key
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _auth_headers(vendor: ScoringVendor, key: str) -> dict[str, str]:
    if vendor == "anthropic":
        return {"x-api-key": key}
    return {"authorization": f"Bearer {key}"}


def _fresh_connection() -> None:
    """오래 사는 프로세스라 끊긴·낡은 DB 연결을 요청 앞에서 버린다(Django 가 요청마다 하는 일). 트랜잭션
    안(시험)에서는 건드리지 않는다."""

    if not connection.in_atomic_block:
        close_old_connections()


def _authorize_sync(token: str | None, vendor: ScoringVendor, model: str | None) -> Grant | Refusal:
    _fresh_connection()
    return authorize(token, vendor=vendor, model=model)


def _record_sync(record_id: int, usage: Usage) -> Decimal:
    _fresh_connection()
    return record_usage(record_id, usage)


async def _authorize(token: str | None, vendor: ScoringVendor, model: str | None) -> Grant | Refusal:
    return await sync_to_async(_authorize_sync)(token, vendor, model)


def _real_key_sync(vendor: ScoringVendor, key_class_id: int | None) -> str:
    """토큰의 키 출처에 맞는 벤더 키 — 플랫폼이면 운영 설정, 클래스면 그 클래스의 채점 연결 키(#1036).
    클래스 연결이 그 벤더 키가 아니면(호환 서버로 바꿨다 등) 빈 값이다 — 플랫폼 키로 대신하지 않는다."""

    _fresh_connection()
    if key_class_id is not None:
        return class_vendor_key(key_class_id, vendor)
    return (setting_value(_KEY_SETTING[vendor]) or "").strip()


async def _real_key(vendor: ScoringVendor, key_class_id: int | None) -> str:
    return await sync_to_async(_real_key_sync)(vendor, key_class_id)


def build_app(upstreams: Upstreams | None = None) -> web.Application:
    """프록시 앱 — `manage.py llm_proxy` 가 띄우고 시험이 그대로 쓴다."""

    targets = upstreams or Upstreams()
    app = web.Application(client_max_size=MAX_REQUEST_BYTES)

    async def open_session(app: web.Application) -> None:
        app[_SESSION_KEY] = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=UPSTREAM_TIMEOUT_SECONDS),
            auto_decompress=False,
        )

    async def close_session(app: web.Application) -> None:
        await app[_SESSION_KEY].close()

    app.on_startup.append(open_session)
    app.on_cleanup.append(close_session)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    def relay(vendor: ScoringVendor, path: str) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
        async def handler(request: web.Request) -> web.StreamResponse:
            return await _relay(request, vendor, targets.base_for(vendor) + path, request.app[_SESSION_KEY])

        return handler

    app.router.add_get("/health", health)
    app.router.add_post("/v1/messages", relay("anthropic", "/v1/messages"))
    app.router.add_post("/v1/responses", relay("openai", "/v1/responses"))
    return app


async def _relay(
    request: web.Request, vendor: ScoringVendor, url: str, session: aiohttp.ClientSession
) -> web.StreamResponse:
    body = await request.read()
    payload = _json_object(body)
    model = payload.get("model") if payload is not None else None
    verdict = await _authorize(_token_from(request, vendor), vendor, model if isinstance(model, str) else None)
    if isinstance(verdict, Refusal):
        logger.info("llm-proxy: refused vendor=%s code=%s", vendor, verdict.code)
        return _refusal_response(verdict)
    key = await _real_key(vendor, verdict.key_class_id)
    if not key:
        logger.warning("llm-proxy: no vendor key vendor=%s run=%s", vendor, verdict.record_id)
        return web.json_response(
            {"type": "error", "error": {"type": "vendor_key_missing", "message": "벤더 키가 설정되지 않았다"}},
            status=503,
            dumps=_DUMPS,
        )
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_REQUEST_HEADERS}
    headers.update(_auth_headers(vendor, key))
    # 압축하지 말라고 못 박는다(#1666). aiohttp 는 Accept-Encoding(gzip·deflate)을 저절로 붙이는데, 세션은
    # `auto_decompress=False`(본문을 그대로 흘려 보내며 미터가 읽는다)이고 Content-Encoding 은 넘기지 않는다 —
    # 벤더가 gzip 으로 답하면 CLI 는 압축 바이트를 JSON 으로 읽다 죽고(`Unrecognized token \x1f`) 미터도 usage 를 못 읽는다.
    headers["accept-encoding"] = "identity"
    target = url + (f"?{request.query_string}" if request.query_string else "")
    meter: UsageMeter | None = None
    settled = False

    async def settle(status: int) -> None:
        # 응답을 끝내기(EOF) **전에** 기록한다 — 끝낸 뒤면 클라이언트가 다음 요청을 보내는 사이에 아직 안 더해져
        # 예산 검사가 앞 응답을 못 본다. 클라이언트가 중간에 끊어도(예외) finally 에서 한 번은 기록한다.
        nonlocal settled
        if settled or meter is None:
            return
        settled = True
        usage = meter.finish()
        if usage is None:
            logger.warning("llm-proxy: no usage in response vendor=%s run=%s status=%s", vendor, verdict.record_id, status)
            return
        cost = await sync_to_async(_record_sync)(verdict.record_id, usage)
        logger.info("llm-proxy: relayed vendor=%s run=%s status=%s cost_usd=%s", vendor, verdict.record_id, status, cost)

    status = 0
    try:
        async with session.post(target, data=body, headers=headers) as upstream:
            status = upstream.status
            if not 200 <= upstream.status < 300:
                raw = await upstream.content.read(MAX_ERROR_BYTES)
                text = redact(raw.decode("utf-8", errors="replace"), (key,))
                logger.info("llm-proxy: vendor error vendor=%s run=%s status=%s", vendor, verdict.record_id, status)
                return web.Response(
                    status=upstream.status,
                    text=text,
                    content_type=upstream.content_type or "application/json",
                )
            streaming = upstream.content_type == "text/event-stream"
            meter = UsageMeter(vendor=vendor, streaming=streaming)
            response = web.StreamResponse(status=upstream.status)
            for name, value in upstream.headers.items():
                if name.lower() in _FORWARD_RESPONSE_HEADERS:
                    response.headers[name] = value
            await response.prepare(request)
            try:
                async for chunk in upstream.content.iter_any():
                    meter.feed(chunk)
                    await response.write(chunk)
                await settle(status)
                await response.write_eof()
            except ConnectionResetError:
                transport = request.transport
                if transport is not None and not transport.is_closing():
                    raise  # 벤더 쪽 끊김이다 — 아래 upstream failed 로
                # 끊은 쪽은 벤더가 아니라 CLI 다 — Codex 는 `response.completed` 를 받으면 남은 본문을 기다리지
                # 않고 연결을 닫는다(#1681). 실패로 적지 않는다. 비용은 finally 의 settle 이 기록한다.
                logger.info("llm-proxy: client closed vendor=%s run=%s status=%s", vendor, verdict.record_id, status)
            return response
    except (aiohttp.ClientError, TimeoutError) as error:
        logger.warning("llm-proxy: upstream failed vendor=%s run=%s error=%s", vendor, verdict.record_id, type(error).__name__)
        if meter is None:
            return web.json_response(
                {"type": "error", "error": {"type": "upstream_unreachable", "message": "벤더에 닿지 못했다"}},
                status=502,
                dumps=_DUMPS,
            )
        raise
    finally:
        await settle(status)
