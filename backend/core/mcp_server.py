"""연결된 앱이 부르는 MCP 엔드포인트의 몸 — 강의실과 공모전이 함께 쓴다 (ADR-0052, #512, #870).

**상태 없는 Streamable HTTP 다.** 요청 하나가 POST 하나이고 응답은 언제나
`application/json` 하나다 — 세션(`Mcp-Session-Id`)을 만들지 않고, SSE 스트림을 열지
않으며, GET·DELETE 는 405 다. 그래서 동기 gunicorn 워커로 그대로 돈다.

**두 세대의 클라이언트를 함께 받는다.** MCP 2026-07-28 은 `initialize` 를 없애고 요청마다
`params._meta` 에 프로토콜 버전을 싣는다(「modern」). 그 전 판(2025-03-26 ~ 2025-11-25)은
`initialize` 로 시작한다(「legacy」). 이 서버는 세션이 없으므로 두 쪽 다 같은 처리기로
받는다 — `_meta` 에 버전이 있으면 modern 규칙(헤더와 본문 대조, `server/discover`)을,
없으면 legacy 규칙을 따른다(규격 「Versioning: Backward Compatibility」의 dual-era 서버).

**자원마다 한 대.** 무엇이 다른가 — 도구 등록부, 서버 이름·안내문, OAuth 자원(범위·공개
오리진), 쓰기 기록을 남기는 함수, 호출 상한 설정, 그리고 매 호출 앞의 입장 검사(`admit`) —
는 `McpServer` 한 값에 모인다. 강의실은 `classroom.mcp.SERVER`, 공모전은 `contests.mcp.SERVER`.

**쓰기는 기록과 한 트랜잭션이다.** 쓰기 도구(`read_only=False`)가 `WriteResult` 를 돌려주면
같은 트랜잭션에서 `record_write` 가 한 줄을 남기고, 도구가 거절하면 둘 다 되돌아간다.
되돌릴 수 없는 도구가 확인 표 없이 불려 `Preview` 를 돌려주면 기록하지 않는다(#515).

**호출 상한**: 계정 한 명당 분당 `calls_per_minute_setting` 번(자원마다 따로 센다). 넘으면
JSON-RPC 오류로 몇 초 뒤에 다시 하라고 알린다(`Retry-After` 도 함께). 분은 `Clock.now()` 로
가른다 — 시험이 시계를 다음 분으로 옮겨 풀리는 것을 본다. 무거운 도구는 그 위에 도구 자신의
분당 상한을 하나 더 받는다(`tool_calls_per_minute_settings`).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from ninja.errors import HttpError

from .clock import Clock
from .mcp_tool import Preview, Tool, ToolInputError, WriteResult
from .models import ConnectedApp
from .oauth import OAuthResource, authenticate_access_token, protected_resource_metadata_url

SERVER_VERSION = "1.0.0"
MODERN_VERSIONS = ("2026-07-28",)
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
#: 규격 「Protocol Version Header」 — 헤더 없는 legacy 요청은 이 판으로 본다.
LEGACY_DEFAULT_VERSION = "2025-03-26"
_META_VERSION = "io.modelcontextprotocol/protocolVersion"

# JSON-RPC 오류 코드
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
RATE_LIMITED = -32000
FORBIDDEN = -32001
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

#: 쓰기 도구가 성공했을 때 기록 한 줄을 남기는 함수 — (허락, 도구 이름, 결과).
RecordWrite = Callable[[ConnectedApp, str, WriteResult], object]
#: 매 호출 앞의 입장 검사 — 통과면 None, 거절이면 사람이 읽을 이유.
Admit = Callable[[ConnectedApp], str | None]


class RpcError(Exception):
    def __init__(self, code: int, message: str, *, http_status: int = 200, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data


def _error_response(request_id: object, error: RpcError, headers: dict[str, str] | None = None) -> JsonResponse:
    body: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message, **({"data": error.data} if error.data is not None else {})},
    }
    response = JsonResponse(body, status=error.http_status, json_dumps_params={"ensure_ascii": False})
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def _decode_header_value(value: str) -> str:
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[len("=?base64?") : -2]).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RpcError(HEADER_MISMATCH, "Mcp-Name 헤더를 해석할 수 없습니다.", http_status=400) from exc
    return value


def _check_modern_headers(request: HttpRequest, version: str, method: str, params: dict) -> None:
    """규격 「Server Validation」 — 헤더와 본문이 어긋나면 400 + HeaderMismatch."""

    if version not in MODERN_VERSIONS:
        raise RpcError(
            UNSUPPORTED_PROTOCOL_VERSION,
            "Unsupported protocol version",
            http_status=400,
            data={"supported": [*MODERN_VERSIONS, *LEGACY_VERSIONS], "requested": version},
        )
    header_version = request.META.get("HTTP_MCP_PROTOCOL_VERSION")
    if header_version != version:
        raise RpcError(HEADER_MISMATCH, "MCP-Protocol-Version 헤더가 본문과 다릅니다.", http_status=400)
    if request.META.get("HTTP_MCP_METHOD") != method:
        raise RpcError(HEADER_MISMATCH, "Mcp-Method 헤더가 본문과 다릅니다.", http_status=400)
    if method == "tools/call":
        header_name = request.META.get("HTTP_MCP_NAME")
        if header_name is None or _decode_header_value(header_name) != params.get("name"):
            raise RpcError(HEADER_MISMATCH, "Mcp-Name 헤더가 본문과 다릅니다.", http_status=400)


def _check_legacy_header(request: HttpRequest) -> None:
    header_version = request.META.get("HTTP_MCP_PROTOCOL_VERSION")
    if header_version is not None and header_version not in LEGACY_VERSIONS + MODERN_VERSIONS:
        raise RpcError(
            INVALID_REQUEST,
            f"지원하지 않는 프로토콜 버전입니다: {header_version}",
            http_status=400,
            data={"supported": [*MODERN_VERSIONS, *LEGACY_VERSIONS], "requested": header_version},
        )


def _capabilities() -> dict:
    return {"tools": {"listChanged": False}}


@dataclass(frozen=True)
class McpServer:
    resource: OAuthResource
    server_name: str
    server_title: str
    instructions: str
    tools: Mapping[str, Tool]
    record_write: RecordWrite
    #: 계정 한 명당 분당 상한을 담은 settings 이름.
    calls_per_minute_setting: str
    #: 상한을 세는 캐시 키의 머리 — 자원마다 따로 센다.
    rate_key_prefix: str
    #: 도구 이름 → 그 도구 하나의 분당 상한을 담은 settings 이름.
    tool_calls_per_minute_settings: Mapping[str, str] = field(default_factory=dict)
    admit: Admit | None = None

    # --- 도구 ---------------------------------------------------------------

    def server_info(self) -> dict:
        return {"name": self.server_name, "title": self.server_title, "version": SERVER_VERSION}

    def call_tool(self, grant: ConnectedApp, params: dict) -> dict:
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"알 수 없는 도구입니다: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments 는 객체여야 합니다.")
        try:
            if tool.read_only:
                structured = tool.handler(grant, arguments)
            else:
                # 쓰기와 그 기록은 한 트랜잭션이다 — 도구가 거절하면 기록도 남지 않고,
                # 기록이 실패하면 쓰기도 되돌아간다(`core.mcp_tool` docstring).
                with transaction.atomic():
                    outcome = tool.handler(grant, arguments)
                    if tool.destructive and isinstance(outcome, Preview):
                        # 두 단계의 첫 단계 — 실행된 것이 없으므로 기록하지 않는다(#515).
                        pass
                    elif not isinstance(outcome, WriteResult):
                        raise TypeError(f"쓰기 도구 {tool.name} 는 WriteResult 를 돌려줘야 합니다.")
                    else:
                        self.record_write(grant, tool.name, outcome)
                structured = outcome.structured
        except (HttpError, ToolInputError) as exc:
            # 화면 API 가 4xx 로 거절할 자리(남의 것 404, 잘못된 입력 422, 잠금 409 …)와
            # 인자 모양이 틀린 것은 도구 오류로 돌려준다 — 프로토콜 오류가 아니라 모델이 읽고
            # 고쳐 부를 수 있는 결과다(MCP 「Tool Execution Errors」). 문장은 화면이 받는 것과 같다.
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
            "structuredContent": structured,
            "isError": False,
        }

    def dispatch(self, grant: ConnectedApp, method: str, params: dict, *, modern: bool) -> dict:
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.describe() for tool in self.tools.values()]}
        if method == "tools/call":
            return self.call_tool(grant, params)
        if method == "initialize" and not modern:
            requested = params.get("protocolVersion")
            version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
            return {
                "protocolVersion": version,
                "capabilities": _capabilities(),
                "serverInfo": self.server_info(),
                "instructions": self.instructions,
            }
        if method == "server/discover" and modern:
            return {
                "supportedVersions": [*MODERN_VERSIONS, *LEGACY_VERSIONS],
                "capabilities": _capabilities(),
                "_meta": {"io.modelcontextprotocol/serverInfo": self.server_info()},
                "instructions": self.instructions,
            }
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}", http_status=404 if modern else 200)

    # --- 호출 상한 ------------------------------------------------------------

    def rate_limited(self, user_id: int, *, bucket: str | None = None, limit: int | None = None) -> int | None:
        """상한을 넘었으면 다음 분까지 남은 초를, 아니면 None 을. `bucket` 을 주면 그 도구
        하나의 상한(`limit`)을 따로 센다."""

        now = Clock.now()
        minute = int(now.timestamp()) // 60
        prefix = f"{self.rate_key_prefix}:{user_id}"
        key = f"{prefix}:{minute}" if bucket is None else f"{prefix}:{bucket}:{minute}"
        cache = caches["rate_limits"]
        cache.add(key, 0, timeout=120)
        try:
            count = cache.incr(key)
        except ValueError:  # 사이에 만료됐다 — 이 분의 첫 호출로 센다.
            cache.set(key, 1, timeout=120)
            count = 1
        ceiling = getattr(settings, self.calls_per_minute_setting) if limit is None else limit
        if count > ceiling:
            return 60 - int(now.timestamp()) % 60
        return None

    def _tool_rate_limited(self, user_id: int, method: str, params: dict) -> int | None:
        name = params.get("name")
        if method != "tools/call" or not isinstance(name, str):
            return None
        setting_name = self.tool_calls_per_minute_settings.get(name)
        if setting_name is None:
            return None
        return self.rate_limited(user_id, bucket=name, limit=getattr(settings, setting_name))

    # --- 뷰 -------------------------------------------------------------------

    def _unauthorized(self, origin: str, *, invalid_token: bool) -> HttpResponse:
        params = [f'resource_metadata="{protected_resource_metadata_url(origin)}"', f'scope="{self.resource.scope}"']
        if invalid_token:
            params.insert(0, 'error="invalid_token"')
        response = JsonResponse(
            {
                "error": "invalid_token" if invalid_token else "unauthorized",
                "error_description": "연결된 앱의 토큰이 필요합니다.",
            },
            status=401,
            json_dumps_params={"ensure_ascii": False},
        )
        response["WWW-Authenticate"] = "Bearer " + ", ".join(params)
        return response

    def endpoint(self) -> Callable[[HttpRequest], HttpResponse]:
        @csrf_exempt
        def mcp_endpoint(request: HttpRequest) -> HttpResponse:
            return self.handle(request)

        return mcp_endpoint

    def handle(self, request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            response = HttpResponse(status=405)
            response["Allow"] = "POST"
            return response

        origin = self.resource.public_origin(request)
        # 규격 「Security & Endpoint」 — DNS 리바인딩을 막는다. 서버끼리 부르는 커넥터는
        # Origin 을 싣지 않고, 실으면 그 앱의 오리진이어야 한다.
        request_origin = request.META.get("HTTP_ORIGIN")
        if request_origin and request_origin.rstrip("/") != origin:
            return JsonResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Origin 이 올바르지 않습니다."}},
                status=403,
            )

        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return self._unauthorized(origin, invalid_token=False)
        grant = authenticate_access_token(self.resource, header[len("Bearer ") :].strip(), origin)
        if grant is None:
            return self._unauthorized(origin, invalid_token=True)

        try:
            message = json.loads(request.body or b"")
        except (ValueError, UnicodeDecodeError):
            return _error_response(None, RpcError(PARSE_ERROR, "JSON 을 읽을 수 없습니다.", http_status=400))
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error_response(None, RpcError(INVALID_REQUEST, "JSON-RPC 요청 하나여야 합니다.", http_status=400))

        request_id = message.get("id")
        method = message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error_response(request_id, RpcError(INVALID_PARAMS, "params 는 객체여야 합니다.", http_status=400))

        if self.admit is not None:
            # 토큰은 살아 있어도 지금 그 일을 할 자격이 없다(공모전 개최 권한 회수 등) — 모든
            # 메서드를 거절한다. 토큰 문제가 아니므로 401 이 아니라 403 이다.
            refusal = self.admit(grant)
            if refusal is not None:
                return _error_response(request_id, RpcError(FORBIDDEN, refusal, http_status=403))

        retry_after = self.rate_limited(grant.instructor_id)
        if retry_after is None:
            retry_after = self._tool_rate_limited(grant.instructor_id, method, params)
        if retry_after is not None:
            return _error_response(
                request_id,
                RpcError(
                    RATE_LIMITED,
                    f"호출이 너무 잦습니다. {retry_after}초 뒤에 다시 시도하세요.",
                    http_status=429,
                    data={"retryAfterSeconds": retry_after},
                ),
                headers={"Retry-After": str(retry_after)},
            )

        if "id" not in message:
            # 알림(notifications/initialized 등) — 받았다는 것만 답한다.
            return HttpResponse(status=202)

        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        modern = _META_VERSION in meta
        try:
            if modern:
                _check_modern_headers(request, str(meta[_META_VERSION]), method, params)
            else:
                _check_legacy_header(request)
            result = self.dispatch(grant, method, params, modern=modern)
        except RpcError as error:
            return _error_response(request_id, error)

        if modern:
            result = {"resultType": "complete", **result}
        return JsonResponse({"jsonrpc": "2.0", "id": request_id, "result": result}, json_dumps_params={"ensure_ascii": False})
