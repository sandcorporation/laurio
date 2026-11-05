"""강의실의 MCP 서버 — 도구 등록부와 안내문 (ADR-0052, #512, CONTEXT.md 「연결된 앱」).

JSON-RPC·프로토콜 두 세대·인증·호출 상한·쓰기 기록 트랜잭션의 몸은 공유층
`core.mcp_server` 에 있다(#870 — 공모전 MCP 가 같은 몸을 쓴다). 여기서는 강의실 자원
(`classroom.oauth.CLASSROOM`)과 도구들로 `SERVER` 한 대를 만든다.

**도구는 화면과 같은 서비스 함수를 부른다.** `list_my_classes` 는 강사 화면의 「내
클래스」와 같은 `classroom.services.instructor_classes` 를 쓴다 — 무엇이 보이는가를
두 표면이 따로 정하지 않는다. 읽기는 기록하지 않는다(ADR-0040·0052). 문제를 만들고 고치는
쓰기 도구는 `classroom.mcp_problem_tools` 에 있고, 디스패치가 그 성공마다 같은 트랜잭션에서
`ConnectedAppWrite` 한 줄을 남긴다(#514). 되돌릴 수 없는 도구(삭제·내보내기·템플릿 공개)는
`classroom.mcp_destructive_tools` 에 있고 두 단계다(#515, `core.mcp_confirmation`).

**호출 상한**: 강사 한 명당 분당 `CLASSROOM_MCP_CALLS_PER_MINUTE` 번. 제출 소스 열기처럼
무거운 도구는 그 위에 도구 자신의 분당 상한을 하나 더 받는다(#518,
`mcp_report_tools.TOOL_CALLS_PER_MINUTE_SETTINGS`).
"""

from __future__ import annotations

from core.mcp_server import McpServer
from core.models import ConnectedApp

from .connected_app_writes import record_write
from .gradability_hint import GRADABILITY_GUIDE
from .instructors import is_owner
from .mcp_class_tools import CLASS_TOOLS
from .mcp_problem_tools import PROBLEM_TOOLS
from .mcp_tool import Tool
from .oauth import CLASSROOM
from .services import instructor_classes
from .mcp_read_tools import READ_TOOL_SPECS
from .mcp_report_tools import REPORT_TOOL_SPECS, TOOL_CALLS_PER_MINUTE_SETTINGS
from .mcp_destructive_tools import DESTRUCTIVE_TOOLS

SERVER_NAME = "codemit-classroom"

INSTRUCTIONS = (
    "Codemit 강의실에서 내가 강사인 클래스를 다루는 도구들이다. 강사는 소유자 한 명과 공동 강사들이고, "
    "둘은 같은 일을 하되 채점 키와 클래스 삭제는 소유자만 한다. 클래스는 보관될 수 있고, "
    "문제는 열림·초안·숨김 중 하나다. 클래스에 가입한 사람은 「참여자」라고 부른다. "
    + GRADABILITY_GUIDE
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


# --- 서버 ---------------------------------------------------------------------


def _record(grant: ConnectedApp, tool: str, outcome) -> None:
    record_write(
        grant,
        tool,
        class_id=getattr(outcome, "class_id", None),
        problem_id=getattr(outcome, "problem_id", None),
        summary=outcome.summary,
    )


SERVER = McpServer(
    resource=CLASSROOM,
    server_name=SERVER_NAME,
    server_title="Codemit 강의실",
    instructions=INSTRUCTIONS,
    tools=TOOLS,
    record_write=_record,
    calls_per_minute_setting="CLASSROOM_MCP_CALLS_PER_MINUTE",
    # 처음부터 쓰던 키 머리 그대로 — 배포 중에도 같은 분의 호출을 이어 센다.
    rate_key_prefix="mcp-calls",
    tool_calls_per_minute_settings=TOOL_CALLS_PER_MINUTE_SETTINGS,
)

mcp_endpoint = SERVER.endpoint()
_call_tool = SERVER.call_tool
