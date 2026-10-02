"""연결된 앱이 문제를 만들고 고치는 MCP 도구들 (#514, spec #511 User Stories 2~4·18).

**화면과 규칙이 한 벌이다.** 도구마다 첫 줄에서 화면 라우트와 같은 강사 범위
(`instructor_scope.class_scope`/`problem_scope(..., write=True)`)를 열고 — 남의 클래스는
「없다」, 보관된 클래스는 화면과 같은 문장으로 거절 — 화면 라우트가 부르는 바로 그
함수(`classroom.problem_authoring`, `problem_transitions.execute_transition`,
`services.copy_problem_to_class`)를 부른다. 인자는 화면이 받는 입력 스키마(`ProblemIn`·
`ProblemPatchIn`·`ChecklistItemIn`·`ChecklistItemPatchIn`)로 똑같이 검증한다 — 그래서
금칙어 등록표(`core.banned_word_rules.RULES`)가 덮는 칸도 화면과 같다.

**전부 쓰기 도구다**(`read_only=False`) — 디스패치가 성공한 호출마다 `ConnectedAppWrite`
한 줄을 남긴다(`classroom.mcp_tool` docstring). 되돌릴 수 있는 쓰기라 `destructiveHint`
는 붙이지 않는다. 문제 삭제는 두 단계 확인 도구라 `classroom.mcp_destructive_tools` 에 있다(#515).
"""

from __future__ import annotations

import pydantic

from . import problem_authoring
from .instructor_scope import class_scope, problem_scope
from .mcp_tool import Tool, ToolInputError, WriteResult
from .models import ChecklistItem, Class, ConnectedApp, Problem
from .problem_transitions import PROBLEM_TRANSITIONS, available_transitions, execute_transition
from .schemas import ChecklistItemIn, ChecklistItemPatchIn, ProblemIn, ProblemPatchIn
from .scoring_models import REASONING_EFFORT_CHOICES
from .services import copy_problem_to_class

# --- 인자 ----------------------------------------------------------------------


def _check_arguments(arguments: dict, input_schema: dict) -> None:
    """모르는 인자와 빠진 인자를 거절한다 — 화면 스키마는 모르는 칸을 조용히 버리는데,
    모델이 칸 이름을 잘못 적으면 「고쳤다」고 믿은 채 아무것도 안 바뀌기 때문이다."""

    unknown = sorted(set(arguments) - set(input_schema["properties"]))
    if unknown:
        raise ToolInputError(f"알 수 없는 인자입니다: {', '.join(unknown)}")
    missing = [key for key in input_schema.get("required", []) if key not in arguments]
    if missing:
        raise ToolInputError(f"빠진 인자가 있습니다: {', '.join(missing)}")


def _id(arguments: dict, key: str) -> int:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} 는 정수여야 합니다.")
    return value


def _ids(arguments: dict, key: str) -> list[int]:
    values = arguments.get(key)
    if not isinstance(values, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise ToolInputError(f"{key} 는 정수 목록이어야 합니다.")
    return values


def _parse(schema_cls: type[pydantic.BaseModel], data: dict):
    try:
        return schema_cls.model_validate(data)
    except pydantic.ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "입력"
        raise ToolInputError(f"{where} 값이 올바르지 않습니다: {first['msg']}") from exc


def _without(arguments: dict, *keys: str) -> dict:
    return {key: value for key, value in arguments.items() if key not in keys}


# --- 결과 ----------------------------------------------------------------------


def _item_out(item: ChecklistItem) -> dict:
    return {"id": item.id, "label": item.label, "required": item.required, "order": item.order}


def _problem_out(problem: Problem, class_obj: Class) -> dict:
    return {
        "id": problem.id,
        "class_id": problem.classroom_id,
        "title": problem.title,
        "description": problem.description,
        "status": problem.status,
        "order": problem.order,
        "submission_formats": list(problem.submission_formats),
        "grading_strictness": problem.grading_strictness,
        "grading_guideline_text": problem.grading_guideline_text,
        "model": problem.model,
        "reasoning_effort": problem.reasoning_effort,
        "syntax_check_enabled": problem.syntax_check_enabled,
        "checklist_items": [_item_out(item) for item in problem.checklist_items.all()],
        "available_transitions": [
            {"name": t.name, "to_state": t.to_state, "blocked_reason": t.blocked_reason}
            for t in available_transitions(problem, class_obj)
        ],
    }


# --- 스키마 조각 ------------------------------------------------------------------

_CLASS_ID = {"type": "integer", "description": "클래스 번호(내 클래스 목록의 id)"}
_PROBLEM_ID = {"type": "integer", "description": "문제 번호"}
_ITEM_ID = {"type": "integer", "description": "체크리스트 항목 번호"}
_TITLE = {"type": "string", "minLength": 1, "maxLength": 200, "description": "문제 제목"}
_DESCRIPTION = {"type": "string", "description": "문제 설명(마크다운). 참여자가 그대로 읽는다."}
_SUBMISSION_FORMATS = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "enum": [v for v, _ in Problem.SubmissionFormat.choices]},
    "description": "제출 형식 — source(소스 파일·zip), repository(GitHub 저장소 주소). 하나 이상.",
}
_LABEL = {"type": "string", "minLength": 1, "maxLength": 200, "description": "체크리스트 항목 문장"}
_REQUIRED = {
    "type": "boolean",
    "description": "필수 항목인가. 필수 항목을 모두 만족해야 통과다. 열린·숨긴 문제는 필수 항목이 하나 이상 있어야 한다.",
}
_CHECKLIST_ITEM_IN = {
    "type": "object",
    "properties": {"label": _LABEL, "required": {**_REQUIRED, "default": True}},
    "required": ["label"],
    "additionalProperties": False,
}
_MODEL = {
    "type": "string",
    "description": "이 문제만의 채점 모델. 빈 문자열이면 클래스 기본값을 따른다. 클래스의 OpenAI 키로 쓸 수 있는 모델이어야 한다.",
}
_REASONING_EFFORT = {
    "type": "string",
    "enum": ["", *[v for v, _ in REASONING_EFFORT_CHOICES]],
    "description": "이 문제만의 추론 강도(low·medium·high). 빈 문자열이면 클래스 기본값을 따른다.",
}
_GRADING_STRICTNESS = {
    "type": "string",
    "enum": [v for v, _ in Problem.GradingStrictness.choices],
    "description": "채점 지침 — strict(엄격)·normal(보통)·lenient(관대)·custom(직접 입력).",
}
_GRADING_GUIDELINE_TEXT = {
    "type": "string",
    "description": "채점 지침이 custom 일 때의 문장. custom 이 아니면 저장되지 않는다.",
}
_SYNTAX_CHECK = {
    "type": "boolean",
    "description": "기본 항목 「소스에 문법 오류가 없다」를 켤 것인가.",
}

_ITEM_OUT = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "label": {"type": "string"},
        "required": {"type": "boolean"},
        "order": {"type": "integer"},
    },
    "required": ["id", "label", "required", "order"],
}
_PROBLEM_OUT = {
    "type": "object",
    "description": "문제 하나 — 화면의 문제 편집과 같은 값",
    "properties": {
        "id": {"type": "integer", "description": "문제 번호"},
        "class_id": {"type": "integer", "description": "클래스 번호"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [v for v, _ in Problem.Status.choices],
            "description": "draft(초안, 참여자에게 안 보임)·open(열림)·hidden(숨김)",
        },
        "order": {"type": "integer", "description": "클래스 안의 순서(0부터)"},
        "submission_formats": {"type": "array", "items": {"type": "string"}},
        "grading_strictness": {"type": "string"},
        "grading_guideline_text": {"type": "string"},
        "model": {"type": "string"},
        "reasoning_effort": {"type": "string"},
        "syntax_check_enabled": {"type": "boolean"},
        "checklist_items": {"type": "array", "items": _ITEM_OUT},
        "available_transitions": {
            "type": "array",
            "description": "지금 부를 수 있는 상태 바꾸기. blocked_reason 이 있으면 막혀 있다(archived·no_required_item).",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(PROBLEM_TRANSITIONS)},
                    "to_state": {"type": "string"},
                    "blocked_reason": {"type": ["string", "null"]},
                },
                "required": ["name", "to_state", "blocked_reason"],
            },
        },
    },
    "required": [
        "id",
        "class_id",
        "title",
        "description",
        "status",
        "order",
        "submission_formats",
        "grading_strictness",
        "grading_guideline_text",
        "model",
        "reasoning_effort",
        "syntax_check_enabled",
        "checklist_items",
        "available_transitions",
    ],
}


def _object(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_PROBLEM_RESULT = _object({"problem": _PROBLEM_OUT}, ["problem"])
_ITEM_RESULT = _object({"item": _ITEM_OUT, "problem": _PROBLEM_OUT}, ["item", "problem"])

# --- 문제 ----------------------------------------------------------------------

_CREATE_PROBLEM_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "title": _TITLE,
        "description": _DESCRIPTION,
        "submission_formats": _SUBMISSION_FORMATS,
        "checklist_items": {
            "type": "array",
            "items": _CHECKLIST_ITEM_IN,
            "description": "체크리스트 항목들 — 적은 순서가 그대로 순서가 된다.",
        },
        "model": _MODEL,
        "reasoning_effort": _REASONING_EFFORT,
        "grading_strictness": {**_GRADING_STRICTNESS, "default": "normal"},
        "grading_guideline_text": _GRADING_GUIDELINE_TEXT,
        "syntax_check_enabled": {**_SYNTAX_CHECK, "default": True},
        "open": {
            "type": "boolean",
            "default": False,
            "description": "참이면 만들자마자 연다. 필수 항목이 없으면 문제도 만들지 않고 거절한다. 거짓이면 초안으로 남는다.",
        },
    },
    ["class_id", "title", "submission_formats"],
)


def _create_problem(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _CREATE_PROBLEM_INPUT)
    payload = _parse(ProblemIn, _without(arguments, "class_id"))
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=True).class_obj
    problem = problem_authoring.create_problem(class_obj, payload)
    opened = " — 바로 열었다" if payload.open else ""
    return WriteResult(
        structured={"problem": _problem_out(problem, class_obj)},
        class_id=class_obj.id,
        problem_id=problem.id,
        summary=f"「{problem.title}」{opened}",
    )


_UPDATE_PROBLEM_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "problem_id": _PROBLEM_ID,
        "title": _TITLE,
        "description": _DESCRIPTION,
        "submission_formats": _SUBMISSION_FORMATS,
        "model": _MODEL,
        "reasoning_effort": _REASONING_EFFORT,
        "grading_strictness": _GRADING_STRICTNESS,
        "grading_guideline_text": _GRADING_GUIDELINE_TEXT,
        "syntax_check_enabled": _SYNTAX_CHECK,
    },
    ["class_id", "problem_id"],
)


def _update_problem(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _UPDATE_PROBLEM_INPUT)
    payload = _parse(ProblemPatchIn, _without(arguments, "class_id", "problem_id"))
    scope = problem_scope(
        _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True
    )
    problem = problem_authoring.update_problem(scope.class_obj, scope.problem, payload)
    changed = ", ".join(sorted(payload.model_fields_set)) or "없음"
    return WriteResult(
        structured={"problem": _problem_out(problem, scope.class_obj)},
        class_id=scope.class_obj.id,
        problem_id=problem.id,
        summary=f"「{problem.title}」 — 고친 칸: {changed}",
    )


_PROBLEM_REF_INPUT = _object({"class_id": _CLASS_ID, "problem_id": _PROBLEM_ID}, ["class_id", "problem_id"])


def _transition_handler(name: str):
    def handler(grant: ConnectedApp, arguments: dict) -> WriteResult:
        _check_arguments(arguments, _PROBLEM_REF_INPUT)
        scope = problem_scope(
            _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True
        )
        problem = execute_transition(name, scope.problem)
        return WriteResult(
            structured={"problem": _problem_out(problem, scope.class_obj)},
            class_id=scope.class_obj.id,
            problem_id=problem.id,
            summary=f"「{problem.title}」",
        )

    return handler


_REORDER_PROBLEMS_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "problem_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "이 클래스의 문제 번호 전부를 원하는 순서대로. 하나라도 빠지거나 다른 클래스의 번호가 섞이면 거절한다.",
        },
    },
    ["class_id", "problem_ids"],
)


def _reorder_problems(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _REORDER_PROBLEMS_INPUT)
    problem_ids = _ids(arguments, "problem_ids")
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=True).class_obj
    ordered = problem_authoring.reorder_problems(class_obj, problem_ids)
    return WriteResult(
        structured={
            "problems": [
                {"id": p.id, "title": p.title, "status": p.status, "order": p.order} for p in ordered
            ]
        },
        class_id=class_obj.id,
        summary="새 순서: " + ", ".join(str(p.id) for p in ordered),
    )


_COPY_PROBLEM_INPUT = _object(
    {
        "class_id": {**_CLASS_ID, "description": "원본 문제가 있는 클래스 번호"},
        "problem_id": {**_PROBLEM_ID, "description": "복사할 문제 번호"},
        "target_class_id": {
            "type": "integer",
            "description": "복사해 넣을 내 다른 클래스 번호. 보관된 클래스에는 넣을 수 없다.",
        },
    },
    ["class_id", "problem_id", "target_class_id"],
)


def _copy_problem(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _COPY_PROBLEM_INPUT)
    # 화면의 복사(`classroom.api.copy_problem`)와 같은 두 문 — 원본은 읽기만 하므로
    # 보관된 클래스에서도 꺼내 가고, 넣는 쪽은 보관이면 거절한다.
    source = problem_scope(
        _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=False
    )
    target_class = class_scope(_id(arguments, "target_class_id"), grant.instructor_id, write=True).class_obj
    copy = copy_problem_to_class(source.problem, target_class)
    return WriteResult(
        structured={"problem": _problem_out(copy, target_class)},
        class_id=target_class.id,
        problem_id=copy.id,
        summary=f"「{copy.title}」 — 클래스 {source.class_obj.id}의 문제 {source.problem.id}에서 복사",
    )


# --- 체크리스트 ------------------------------------------------------------------

_ADD_ITEM_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "problem_id": _PROBLEM_ID,
        "label": _LABEL,
        "required": {**_REQUIRED, "default": True},
    },
    ["class_id", "problem_id", "label"],
)


def _add_checklist_item(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _ADD_ITEM_INPUT)
    payload = _parse(ChecklistItemIn, _without(arguments, "class_id", "problem_id"))
    scope = problem_scope(
        _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True
    )
    item = problem_authoring.add_checklist_item(scope.problem, payload)
    return WriteResult(
        structured={"item": _item_out(item), "problem": _problem_out(scope.problem, scope.class_obj)},
        class_id=scope.class_obj.id,
        problem_id=scope.problem.id,
        summary=f"항목 {item.id} 「{item.label}」",
    )


_UPDATE_ITEM_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "problem_id": _PROBLEM_ID,
        "item_id": _ITEM_ID,
        "label": _LABEL,
        "required": _REQUIRED,
    },
    ["class_id", "problem_id", "item_id"],
)


def _update_checklist_item(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _UPDATE_ITEM_INPUT)
    payload = _parse(ChecklistItemPatchIn, _without(arguments, "class_id", "problem_id", "item_id"))
    scope = problem_scope(
        _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True
    )
    item = problem_authoring.update_checklist_item(scope.problem, _id(arguments, "item_id"), payload)
    return WriteResult(
        structured={"item": _item_out(item), "problem": _problem_out(scope.problem, scope.class_obj)},
        class_id=scope.class_obj.id,
        problem_id=scope.problem.id,
        summary=f"항목 {item.id} 「{item.label}」 — 고친 칸: {', '.join(sorted(payload.model_fields_set)) or '없음'}",
    )


_DELETE_ITEM_INPUT = _object(
    {"class_id": _CLASS_ID, "problem_id": _PROBLEM_ID, "item_id": _ITEM_ID},
    ["class_id", "problem_id", "item_id"],
)


def _delete_checklist_item(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _DELETE_ITEM_INPUT)
    scope = problem_scope(
        _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True
    )
    item = problem_authoring.delete_checklist_item(scope.problem, _id(arguments, "item_id"))
    return WriteResult(
        structured={"deleted_item_id": item.id, "problem": _problem_out(scope.problem, scope.class_obj)},
        class_id=scope.class_obj.id,
        problem_id=scope.problem.id,
        summary=f"항목 {item.id} 「{item.label}」",
    )


_REORDER_ITEMS_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "problem_id": _PROBLEM_ID,
        "item_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "이 문제의 체크리스트 항목 번호 전부를 원하는 순서대로. 하나라도 빠지면 거절한다.",
        },
    },
    ["class_id", "problem_id", "item_ids"],
)


def _reorder_checklist_items(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _REORDER_ITEMS_INPUT)
    item_ids = _ids(arguments, "item_ids")
    scope = problem_scope(
        _id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True
    )
    ordered = problem_authoring.reorder_checklist_items(scope.problem, item_ids)
    return WriteResult(
        structured={"problem": _problem_out(scope.problem, scope.class_obj)},
        class_id=scope.class_obj.id,
        problem_id=scope.problem.id,
        summary="새 순서: " + ", ".join(str(i.id) for i in ordered),
    )


# --- 등록 ----------------------------------------------------------------------

_ARCHIVED_NOTE = "보관된 클래스에서는 할 수 없다."

PROBLEM_TOOLS: list[Tool] = [
    Tool(
        name="create_problem",
        title="문제 만들기",
        description=(
            "클래스에 문제를 하나 만든다 — 제목·설명·제출 형식·체크리스트·채점 설정을 한 번에. "
            "기본은 초안(참여자에게 안 보임)이고, open 을 참으로 주면 바로 연다(필수 체크리스트 항목이 "
            f"하나 이상 있어야 한다). 새 문제는 클래스의 맨 뒤에 붙는다. {_ARCHIVED_NOTE}"
        ),
        input_schema=_CREATE_PROBLEM_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_create_problem,
    ),
    Tool(
        name="update_problem",
        title="문제 고치기",
        description=(
            "문제의 제목·설명·제출 형식·채점 모델·추론 강도·채점 지침·문법 검사를 고친다. 보낸 칸만 "
            "바뀌고 보내지 않은 칸은 그대로다. 체크리스트는 체크리스트 도구로 고친다. "
            f"{_ARCHIVED_NOTE}"
        ),
        input_schema=_UPDATE_PROBLEM_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_update_problem,
    ),
    Tool(
        name="add_checklist_item",
        title="체크리스트 항목 더하기",
        description=f"문제의 체크리스트 맨 뒤에 항목을 하나 더한다. {_ARCHIVED_NOTE}",
        input_schema=_ADD_ITEM_INPUT,
        output_schema=_ITEM_RESULT,
        read_only=False,
        handler=_add_checklist_item,
    ),
    Tool(
        name="update_checklist_item",
        title="체크리스트 항목 고치기",
        description=(
            "체크리스트 항목의 문장이나 필수 여부를 고친다. 열린·숨긴 문제의 마지막 필수 항목은 필수를 "
            f"풀 수 없다. {_ARCHIVED_NOTE}"
        ),
        input_schema=_UPDATE_ITEM_INPUT,
        output_schema=_ITEM_RESULT,
        read_only=False,
        handler=_update_checklist_item,
    ),
    Tool(
        name="delete_checklist_item",
        title="체크리스트 항목 지우기",
        description=(
            "체크리스트 항목을 하나 지운다. 열린·숨긴 문제의 마지막 필수 항목은 지울 수 없다. "
            f"{_ARCHIVED_NOTE}"
        ),
        input_schema=_DELETE_ITEM_INPUT,
        output_schema=_object(
            {"deleted_item_id": {"type": "integer"}, "problem": _PROBLEM_OUT}, ["deleted_item_id", "problem"]
        ),
        read_only=False,
        handler=_delete_checklist_item,
    ),
    Tool(
        name="reorder_checklist_items",
        title="체크리스트 순서 바꾸기",
        description=f"문제의 체크리스트 항목 순서를 바꾼다. 항목 번호 전부를 새 순서로 보낸다. {_ARCHIVED_NOTE}",
        input_schema=_REORDER_ITEMS_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_reorder_checklist_items,
        idempotent=True,
    ),
    Tool(
        name="open_problem",
        title="문제 열기",
        description=(
            "초안인 문제를 열어 참여자에게 보이고 제출을 받는다. 필수 체크리스트 항목이 하나 이상 "
            f"있어야 한다. {_ARCHIVED_NOTE}"
        ),
        input_schema=_PROBLEM_REF_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_transition_handler("open"),
    ),
    Tool(
        name="hide_problem",
        title="문제 숨기기",
        description=(
            "열린 문제를 참여자에게서 거둔다. 지난 시도와 통과는 그대로 남고, 다시 열 수 있다. "
            f"{_ARCHIVED_NOTE}"
        ),
        input_schema=_PROBLEM_REF_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_transition_handler("hide"),
    ),
    Tool(
        name="reopen_problem",
        title="문제 다시 열기",
        description=(
            "숨긴 문제를 다시 연다. 필수 체크리스트 항목이 하나 이상 있어야 한다. "
            f"{_ARCHIVED_NOTE}"
        ),
        input_schema=_PROBLEM_REF_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_transition_handler("reopen"),
    ),
    Tool(
        name="reorder_problems",
        title="문제 순서 바꾸기",
        description=(
            "클래스의 문제 순서를 바꾼다. 그 클래스의 문제 번호 전부를 새 순서로 보낸다. "
            f"{_ARCHIVED_NOTE}"
        ),
        input_schema=_REORDER_PROBLEMS_INPUT,
        output_schema=_object(
            {
                "problems": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "title": {"type": "string"},
                            "status": {"type": "string"},
                            "order": {"type": "integer"},
                        },
                        "required": ["id", "title", "status", "order"],
                    },
                }
            },
            ["problems"],
        ),
        read_only=False,
        handler=_reorder_problems,
        idempotent=True,
    ),
    Tool(
        name="copy_problem",
        title="문제를 다른 클래스로 복사",
        description=(
            "문제 하나를 체크리스트·채점 설정과 함께 내 다른 클래스로 복사한다. 복사본은 언제나 초안으로 "
            "그 클래스의 맨 뒤에 붙는다. 참여자의 시도는 따라가지 않는다. 보관된 클래스로는 복사할 수 없다."
        ),
        input_schema=_COPY_PROBLEM_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_copy_problem,
    ),
]
