"""연결된 앱이 한 쓰기를 남기는 자리 (ADR-0052 「쓰기만 기록한다」, #514).

MCP 디스패치(`core.mcp_server.McpServer.call_tool`)가 쓰기 도구(`read_only=False`)가 성공한 뒤 같은
트랜잭션 안에서 이 함수를 부른다 — 도구가 스스로 부르지 않는다. 읽기 도구는 여기에 닿지
않는다(ADR-0040).
"""

from __future__ import annotations

from core.clock import Clock

from core.models import ConnectedApp

from .models import ConnectedAppWrite

_SUMMARY_MAX = ConnectedAppWrite._meta.get_field("summary").max_length


def record_write(
    grant: ConnectedApp,
    tool: str,
    *,
    class_id: int | None,
    problem_id: int | None,
    summary: str = "",
) -> ConnectedAppWrite:
    if len(summary) > _SUMMARY_MAX:
        summary = summary[: _SUMMARY_MAX - 1] + "…"
    return ConnectedAppWrite.objects.create(
        instructor_id=grant.instructor_id,
        connected_app=grant,
        tool=tool,
        target_class_id=class_id,
        target_problem_id=problem_id,
        summary=summary,
        created_at=Clock.now(),
    )
