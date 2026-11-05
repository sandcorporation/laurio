"""MCP 도구의 실제 응답이 자기 `outputSchema` 를 만족하는가 (#579).

`tests.test_classroom_connected_apps._rpc` 가 성공한 `tools/call` 마다 이것을 부른다 — 그래서
MCP 시험이 부르는 모든 도구 호출이 저절로 검사된다. 스키마는 `tools/list` 가 내놓는 것과 같은
값(`Tool.describe()["outputSchema"]`)을 등록부에서 읽는다 — `tools/list` 를 다시 부르면 호출
상한 시험이 흔들린다.

jsonschema 패키지는 의존성에 없다. 도구 스키마가 쓰는 낱말(type·properties·required·items·
enum·additionalProperties·minimum·maximum·minLength·maxLength·minItems)만 읽는 작은 검사기다 —
모르는 낱말을 만나면 조용히 넘기지 않고 실패한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.mcp_tool import Tool

_KNOWN = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "additionalProperties",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "description",
    "default",
}

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def schema_errors(value, schema: dict, path: str = "$") -> list[str]:
    unknown = set(schema) - _KNOWN
    if unknown:
        return [f"{path}: 검사기가 모르는 스키마 낱말 {sorted(unknown)}"]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            return [f"{path}: {types} 이어야 하는데 {value!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {schema['enum']} 중 하나여야 하는데 {value!r}"]
    errors: list[str] = []
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [f"{path}: {key} 가 없다" for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: 스키마에 없는 {key}" for key in value if key not in properties]
        for key, sub in properties.items():
            if key in value:
                errors += schema_errors(value[key], sub, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: 항목이 {schema['minItems']}개보다 적다")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += schema_errors(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            errors.append(f"{path}: 길이 {len(value)} 가 범위 밖")
    if _TYPES["number"](value):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.append(f"{path}: {value} 가 범위 밖")
    return errors


def assert_matches_output_schema(tool_name: str, structured: dict, tools: Mapping[str, Tool] | None = None) -> None:
    """`tools` 를 주지 않으면 강의실 등록부를 본다 — 공모전 MCP 시험은 `contests.mcp.TOOLS` 를 넘긴다."""

    if tools is None:
        from classroom.mcp import TOOLS as tools

    schema = tools[tool_name].describe()["outputSchema"]
    errors = schema_errors(structured, schema)
    assert not errors, f"{tool_name} 의 응답이 outputSchema 와 어긋난다: {errors}"
