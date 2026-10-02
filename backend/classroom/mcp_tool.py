"""MCP 도구 하나의 모양 — 등록부(`classroom.mcp.TOOLS`)와 도구 모듈들이 함께 쓴다
(#512, #514).

**쓰기 도구는 `read_only=False` 로 표시하고 `WriteResult` 를 돌려준다.** 디스패치
(`classroom.mcp._call_tool`)가 그 표시를 보고 도구를 기록과 한 트랜잭션 안에서 부른다
— 도구가 성공하면 `ConnectedAppWrite` 한 줄이 남고, 거절하면 쓰기도 기록도 함께
되돌아간다(ADR-0052 「쓰기만 기록한다」). 도구가 스스로 기록을 부르지 않으므로 새
쓰기 도구가 기록을 빠뜨릴 길이 없다. 읽기 도구(`read_only=True`)는 결과 dict 를
그대로 돌려주고 아무것도 남기지 않는다(ADR-0040).

**도구가 거절하는 길은 둘이다.** 화면과 같은 서비스 함수가 던지는 `HttpError` 와,
인자 모양이 틀렸을 때 도구가 던지는 `ToolInputError`. 디스패치는 둘 다 JSON-RPC
오류가 아니라 `isError: true` 인 도구 결과로 돌려준다 — MCP 규격이 「모델이 읽고 고쳐
다시 부를 수 있는 실패」를 그렇게 싣게 한다. 문구는 화면이 받는 것과 같은 문장이다.

이 모듈이 `classroom.mcp` 밖에 있는 이유는 순환 import 를 피하기 위해서다 — 도구
모듈이 `Tool` 을 가져가고, `classroom.mcp` 가 도구 모듈의 목록을 가져간다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .models import ConnectedApp


class ToolInputError(Exception):
    """인자의 모양이 틀렸다 — 도구 결과의 `isError: true` 로 그대로 돌아간다."""


@dataclass(frozen=True)
class WriteResult:
    """쓰기 도구가 돌려주는 것 — 응답에 실을 결과와 기록에 남길 대상."""

    structured: dict
    class_id: int | None = None
    problem_id: int | None = None
    summary: str = ""


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict
    output_schema: dict
    read_only: bool
    handler: Callable[[ConnectedApp, dict], dict | WriteResult]
    #: 되돌릴 수 없는 쓰기인가 — MCP `destructiveHint`. 문제를 만들고 고치는 것처럼
    #: 다시 고쳐 되돌릴 수 있는 쓰기는 거짓이다.
    destructive: bool = False
    #: 같은 인자로 두 번 불러도 결과가 같은가 — MCP `idempotentHint`. 읽기는 언제나 참이다.
    idempotent: bool = field(default=False)

    def describe(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.read_only or self.idempotent,
                "openWorldHint": False,
            },
        }
