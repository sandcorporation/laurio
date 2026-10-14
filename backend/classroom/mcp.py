"""연결된 앱이 부르는 MCP 엔드포인트 (ADR-0052, #512, CONTEXT.md 「연결된 앱」).

**상태 없는 Streamable HTTP 다.** 요청 하나가 POST 하나이고 응답은 언제나
`application/json` 하나다 — 세션(`Mcp-Session-Id`)을 만들지 않고, SSE 스트림을 열지
않으며, GET·DELETE 는 405 다. 그래서 동기 gunicorn 워커로 그대로 돈다.

**두 세대의 클라이언트를 함께 받는다.** MCP 2026-07-28 은 `initialize` 를 없애고 요청마다
`params._meta` 에 프로토콜 버전을 싣는다(「modern」). 그 전 판(2025-03-26 ~ 2025-11-25)은
`initialize` 로 시작한다(「legacy」). 이 서버는 세션이 없으므로 두 쪽 다 같은 처리기로
받는다 — `_meta` 에 버전이 있으면 modern 규칙(헤더와 본문 대조, `server/discover`)을,
없으면 legacy 규칙을 따른다(규격 「Versioning: Backward Compatibility」의 dual-era 서버).

**도구는 화면과 같은 서비스 함수를 부른다.** `list_my_classes` 는 강사 화면의 「내
클래스」와 같은 `classroom.services.instructor_classes` 를 쓴다 — 무엇이 보이는가를
두 표면이 따로 정하지 않는다. 읽기는 기록하지 않는다(ADR-0040·0052). 문제를 만들고 고치는
쓰기 도구는 `classroom.mcp_problem_tools` 에 있고, 디스패치가 그 성공마다 같은 트랜잭션에서
`ConnectedAppWrite` 한 줄을 남긴다(#514, `classroom.mcp_tool` docstring). 되돌릴 수 없는 도구
(삭제·내보내기·템플릿 공개)는 `classroom.mcp_destructive_tools` 에 있고 두 단계다 — 확인 표
없이 불리면 미리보기(`Preview`)만 돌려주고 기록하지 않는다(#515).

**호출 상한**: 강사 한 명당 분당 `CLASSROOM_MCP_CALLS_PER_MINUTE` 번. 넘으면 JSON-RPC
오류로 몇 초 뒤에 다시 하라고 알린다(`Retry-After` 도 함께). 분은 `Clock.now()` 로
가른다 — 시험이 시계를 다음 분으로 옮겨 풀리는 것을 본다. 제출 소스 열기처럼 무거운 도구는
그 위에 도구 자신의 분당 상한을 하나 더 받는다(#518, `mcp_report_tools.TOOL_CALLS_PER_MINUTE_SETTINGS`).
"""

from __future__ import annotations

import base64
import json

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from ninja.errors import HttpError

from core.clock import Clock

from .connected_app_writes import record_write
from .instructors import is_owner
from .mcp_class_tools import CLASS_TOOLS
from .mcp_problem_tools import PROBLEM_TOOLS
from .mcp_tool import Preview, Tool, ToolInputError, WriteResult
from .models import ConnectedApp
from .oauth import SCOPE, authenticate_access_token, protected_resource_metadata_url, public_origin
from .services import instructor_classes
from .mcp_read_tools import READ_TOOL_SPECS
from .mcp_report_tools import REPORT_TOOL_SPECS, TOOL_CALLS_PER_MINUTE_SETTINGS
from .mcp_destructive_tools import DESTRUCTIVE_TOOLS

SERVER_NAME = "codemit-classroom"
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
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

INSTRUCTIONS = (
    "Codemit 강의실에서 내가 강사인 클래스를 다루는 도구들이다. 강사는 소유자 한 명과 공동 강사들이고, "
    "둘은 같은 일을 하되 채점 키와 클래스 삭제는 소유자만 한다. 클래스는 보관될 수 있고, "
    "문제는 열림·초안·숨김 중 하나다. 클래스에 가입한 사람은 「참여자」라고 부른다."
)


# --- 도구 ---------------------------------------------------------------------


def _list_my_classes(grant: ConnectedApp, arguments: dict) -> dict:
    classes = instructor_classes(grant.instructor_id)
    return {
        "classes": [
            {
                "id": c.id,
                "name": c.name,
                "archived": c.archived_at is not None,
                "role": "owner" if is_owner(c, grant.instructor_id) else "co_instructor",
                "participant_count": c.participant_count,
                "problem_count": c.open_problem_count + c.draft_problem_count + c.hidden_problem_count,
                "problem_counts": {
                    "open": c.open_problem_count,
                    "draft": c.draft_problem_count,
                    "hidden": c.hidden_problem_count,
                },
                "created_at": c.created_at.isoformat(),
            }
            for c in classes
        ]
    }


_COUNT = {"type": "integer", "minimum": 0}
_ROLE = {
    "type": "string",
    "enum": ["owner", "co_instructor"],
    "description": "이 클래스에서 내 역할 — owner 소유자, co_instructor 공동 강사. 채점 키·클래스 삭제는 소유자만 한다.",
}

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            name="list_my_classes",
            title="내 클래스 목록",
            description=(
                "내가 강사(소유자 또는 공동 강사)인 클래스를 최근에 만든 순서로 돌려준다. 클래스마다 이름, "
                "내 역할(owner 소유자·co_instructor 공동 강사), 보관 여부, 참여자 수(강사와 내보낸 참여자는 "
                "세지 않는다), 문제 수(열림·초안·숨김별)를 담는다. 참여자 이름이나 제출물은 담지 않는다."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "classes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer", "description": "클래스 번호"},
                                "name": {"type": "string", "description": "클래스 이름"},
                                "archived": {"type": "boolean", "description": "보관된 클래스인가"},
                                "role": _ROLE,
                                "participant_count": {**_COUNT, "description": "참여자 수"},
                                "problem_count": {**_COUNT, "description": "문제 수(모든 상태)"},
                                "problem_counts": {
                                    "type": "object",
                                    "description": "상태별 문제 수",
                                    "properties": {
                                        "open": {**_COUNT, "description": "열림"},
                                        "draft": {**_COUNT, "description": "초안"},
                                        "hidden": {**_COUNT, "description": "숨김"},
                                    },
                                    "required": ["open", "draft", "hidden"],
                                },
                                "created_at": {"type": "string", "description": "만든 시각(ISO 8601)"},
                            },
                            "required": [
                                "id",
                                "name",
                                "archived",
                                "role",
                                "participant_count",
                                "problem_count",
                                "problem_counts",
                                "created_at",
                            ],
                        },
                    }
                },
                "required": ["classes"],
            },
            read_only=True,
            handler=_list_my_classes,
        ),
        *PROBLEM_TOOLS,
    ]
}

# 읽기 도구(#513) — 처리기와 명세는 `mcp_read_tools` 에 산다. 등록부 끝에 덧붙인다.
for _spec in READ_TOOL_SPECS:
    TOOLS[_spec["name"]] = Tool(**_spec, read_only=True)

# 참여자 리포트·제출 소스 열기(#518) — 처리기와 명세는 `mcp_report_tools` 에 산다.
for _spec in REPORT_TOOL_SPECS:
    TOOLS[_spec["name"]] = Tool(**_spec, read_only=True)

# 되돌릴 수 없는 도구(#515) — 두 단계 확인. 처리기는 `mcp_destructive_tools` 에 산다.
for _tool in DESTRUCTIVE_TOOLS:
    TOOLS[_tool.name] = _tool

# 클래스를 다루는 쓰기 도구(#516) — `mcp_class_tools` 에 산다. 등록부 끝에 덧붙인다.
for _tool in CLASS_TOOLS:
    TOOLS[_tool.name] = _tool


# --- JSON-RPC 바탕 -------------------------------------------------------------


class RpcError(Exception):
    def __init__(self, code: int, message: str, *, http_status: int = 200, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data


def _error_response(request_id, error: RpcError, headers: dict | None = None) -> JsonResponse:
    body: dict = {"jsonrpc": "2.0", "id": request_id, "error": {"code": error.code, "message": error.message}}
    if error.data is not None:
        body["error"]["data"] = error.data
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


def _server_info() -> dict:
    return {"name": SERVER_NAME, "title": "Codemit 강의실", "version": SERVER_VERSION}


def _call_tool(grant: ConnectedApp, params: dict) -> dict:
    name = params.get("name")
    tool = TOOLS.get(name) if isinstance(name, str) else None
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
            # 기록이 실패하면 쓰기도 되돌아간다(`classroom.mcp_tool` docstring).
            with transaction.atomic():
                outcome = tool.handler(grant, arguments)
                if tool.destructive and isinstance(outcome, Preview):
                    # 두 단계의 첫 단계 — 실행된 것이 없으므로 기록하지 않는다(#515).
                    pass
                elif not isinstance(outcome, WriteResult):
                    raise TypeError(f"쓰기 도구 {tool.name} 는 WriteResult 를 돌려줘야 합니다.")
                else:
                    record_write(
                        grant,
                        tool.name,
                        class_id=outcome.class_id,
                        problem_id=outcome.problem_id,
                        summary=outcome.summary,
                    )
            structured = outcome.structured
    except (HttpError, ToolInputError) as exc:
        # 화면 API 가 4xx 로 거절할 자리(남의 클래스 404, 잘못된 입력 422, 보관 잠금 …)와
        # 인자 모양이 틀린 것은 도구 오류로 돌려준다 — 프로토콜 오류가 아니라 모델이 읽고
        # 고쳐 부를 수 있는 결과다(MCP 「Tool Execution Errors」). 문장은 화면이 받는 것과 같다.
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    return {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
        "structuredContent": structured,
        "isError": False,
    }


def _dispatch(grant: ConnectedApp, method: str, params: dict, *, modern: bool) -> dict:
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [tool.describe() for tool in TOOLS.values()]}
    if method == "tools/call":
        return _call_tool(grant, params)
    if method == "initialize" and not modern:
        requested = params.get("protocolVersion")
        version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": _capabilities(),
            "serverInfo": _server_info(),
            "instructions": INSTRUCTIONS,
        }
    if method == "server/discover" and modern:
        return {
            "supportedVersions": [*MODERN_VERSIONS, *LEGACY_VERSIONS],
            "capabilities": _capabilities(),
            "_meta": {"io.modelcontextprotocol/serverInfo": _server_info()},
            "instructions": INSTRUCTIONS,
        }
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}", http_status=404 if modern else 200)


# --- 호출 상한 -----------------------------------------------------------------


def _rate_limited(instructor_id: int, *, bucket: str | None = None, limit: int | None = None) -> int | None:
    """상한을 넘었으면 다음 분까지 남은 초를, 아니면 None 을. `bucket` 을 주면 그 도구
    하나의 상한(`limit`)을 따로 센다(#518 — 제출 소스 열기는 더 낮은 상한을 받는다)."""

    now = Clock.now()
    minute = int(now.timestamp()) // 60
    key = f"mcp-calls:{instructor_id}:{minute}" if bucket is None else f"mcp-calls:{instructor_id}:{bucket}:{minute}"
    cache = caches["rate_limits"]
    cache.add(key, 0, timeout=120)
    try:
        count = cache.incr(key)
    except ValueError:  # 사이에 만료됐다 — 이 분의 첫 호출로 센다.
        cache.set(key, 1, timeout=120)
        count = 1
    if count > (settings.CLASSROOM_MCP_CALLS_PER_MINUTE if limit is None else limit):
        return 60 - int(now.timestamp()) % 60
    return None


def _tool_rate_limited(instructor_id: int, method: str, params: dict) -> int | None:
    """도구 자신의 분당 상한(`TOOL_CALLS_PER_MINUTE_SETTINGS`)이 있는 도구 호출이면 그것도 센다."""

    name = params.get("name")
    if method != "tools/call" or not isinstance(name, str):
        return None
    setting_name = TOOL_CALLS_PER_MINUTE_SETTINGS.get(name)
    if setting_name is None:
        return None
    return _rate_limited(instructor_id, bucket=name, limit=getattr(settings, setting_name))


# --- 뷰 -----------------------------------------------------------------------


def _unauthorized(origin: str, *, invalid_token: bool) -> HttpResponse:
    params = [f'resource_metadata="{protected_resource_metadata_url(origin)}"', f'scope="{SCOPE}"']
    if invalid_token:
        params.insert(0, 'error="invalid_token"')
    response = JsonResponse(
        {"error": "invalid_token" if invalid_token else "unauthorized", "error_description": "연결된 앱의 토큰이 필요합니다."},
        status=401,
        json_dumps_params={"ensure_ascii": False},
    )
    response["WWW-Authenticate"] = "Bearer " + ", ".join(params)
    return response


@csrf_exempt
def mcp_endpoint(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response

    origin = public_origin(request)
    # 규격 「Security & Endpoint」 — DNS 리바인딩을 막는다. 서버끼리 부르는 커넥터는
    # Origin 을 싣지 않고, 실으면 우리 강의실 오리진이어야 한다.
    request_origin = request.META.get("HTTP_ORIGIN")
    if request_origin and request_origin.rstrip("/") != origin:
        return JsonResponse({"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Origin 이 올바르지 않습니다."}}, status=403)

    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Bearer "):
        return _unauthorized(origin, invalid_token=False)
    grant = authenticate_access_token(header[len("Bearer ") :].strip(), origin)
    if grant is None:
        return _unauthorized(origin, invalid_token=True)

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

    retry_after = _rate_limited(grant.instructor_id)
    if retry_after is None:
        retry_after = _tool_rate_limited(grant.instructor_id, method, params)
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
        result = _dispatch(grant, method, params, modern=modern)
    except RpcError as error:
        return _error_response(request_id, error)

    if modern:
        result = {"resultType": "complete", **result}
    return JsonResponse({"jsonrpc": "2.0", "id": request_id, "result": result}, json_dumps_params={"ensure_ascii": False})
