"""강의실 MCP 도구의 모양 (#512, #514).

`Tool`·`Preview`·`ToolInputError` 와 디스패치의 규칙은 공유층 `core.mcp_tool` 에 있다(#870).
여기에는 강의실 쓰기 기록(`ConnectedAppWrite`)이 적는 대상 — 클래스·문제 번호 — 을 더한
`WriteResult` 하나가 있다.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.mcp_tool import Preview, Tool, ToolInputError  # noqa: F401 — 강의실 도구 모듈이 이 이름으로 가져간다.
from core.mcp_tool import WriteResult as _WriteResult


@dataclass(frozen=True)
class WriteResult(_WriteResult):
    """강의실 쓰기 — 기록에 남길 클래스·문제 번호를 함께 싣는다."""

    class_id: int | None = None
    problem_id: int | None = None
