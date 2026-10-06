"""연결된 앱의 읽기 도구 (#513, 부모 #511, ADR-0052, CONTEXT.md 「연결된 앱」).

강사 화면이 보여주는 것을 연결된 앱도 읽는다 — 클래스 상세, 문제 목록과 상세, 참여자
명단, 명단 격자. **화면 API 와 같은 함수를 부른다**: 범위는 `instructor_scope` 의
`class_scope`/`problem_scope`(`write=False`)가 정하고 — 그래서 남의 클래스는 화면과
똑같이 「없다」다 — 값은 `classroom.api` 의 직렬화 함수가 만든다. 무엇이 보이는가를
두 표면이 따로 정하지 않는다.

**화면과 다른 것은 하나다**: 클래스 상세에서 OpenAI 키의 가린 표시
(`openai_key_masked`, 끝 네 자리)를 뺀다. 연결된 앱이 보는 것은 「키가 있는가」와 그
상태뿐이다(#511 「OpenAI 키」) — 키의 어느 조각도 대화 기록과 AI 업체로 가지 않는다.
이메일은 화면 응답에도 없다(참여자는 클래스에서 불릴 이름으로만 나온다).

**읽기는 아무것도 남기지 않는다**(ADR-0040). 이 모듈의 처리기는 질의만 한다 —
`tests/test_classroom_mcp_read_tools.py` 가 호출 앞뒤의 모든 테이블 행 수가 같음을 고정한다.

이 모듈은 `classroom.mcp` 를 import 하지 않는다 — 처리기와 명세만 내놓고, 등록은
`mcp.TOOLS` 끝에 덧붙이는 쪽이 한다(순환 import 를 만들지 않는다). 처리기가 낸
`HttpError` 는 `mcp._call_tool` 이 도구 오류(`isError: true`)로 바꾼다.
"""

from __future__ import annotations

import json

from ninja.errors import HttpError
from ninja.responses import NinjaJSONEncoder

from .api import (
    _build_roster_grid,
    _serialize_class,
    _serialize_members,
    _serialize_problem,
    _serialize_problem_list,
)
from .instructor_scope import class_scope, problem_scope
from .models import ConnectedApp

#: 화면 응답에는 있지만 연결된 앱에게는 주지 않는 클래스 필드.
_CLASS_FIELDS_WITHHELD = {"openai_key_masked"}


def _as_screen_json(value):
    """화면 응답이 지나는 인코더(`NinjaJSONEncoder`) 그대로 JSON 값으로 — 시각의 모양까지
    화면과 한 글자도 다르지 않다."""

    return json.loads(json.dumps(value, cls=NinjaJSONEncoder))


def _int_argument(arguments: dict, name: str, label: str) -> int:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HttpError(422, f"{label} 번호({name})를 정수로 주세요.")
    return value


def _class_id(arguments: dict) -> int:
    return _int_argument(arguments, "class_id", "클래스")


def _problem_id(arguments: dict) -> int:
    return _int_argument(arguments, "problem_id", "문제")


def class_view(class_obj, viewer_id: int) -> dict:
    """연결된 앱이 보는 클래스 하나 — 화면 응답에서 키의 가린 표시만 뺀다. 클래스를 바꾸는
    도구(`classroom.mcp_class_tools`)도 결과를 이 모양으로 돌려준다."""

    return _as_screen_json(_serialize_class(class_obj, viewer_id=viewer_id).model_dump(exclude=_CLASS_FIELDS_WITHHELD))


def _get_class(grant: ConnectedApp, arguments: dict) -> dict:
    class_obj = class_scope(_class_id(arguments), grant.instructor_id, write=False, owner=False).class_obj
    return class_view(class_obj, grant.instructor_id)


def _list_problems(grant: ConnectedApp, arguments: dict) -> dict:
    class_obj = class_scope(_class_id(arguments), grant.instructor_id, write=False, owner=False).class_obj
    return {"problems": _as_screen_json(_serialize_problem_list(class_obj))}


def _get_problem(grant: ConnectedApp, arguments: dict) -> dict:
    scope = problem_scope(_class_id(arguments), _problem_id(arguments), grant.instructor_id, write=False, owner=False)
    return _as_screen_json(_serialize_problem(scope.problem, scope.class_obj))


def _list_participants(grant: ConnectedApp, arguments: dict) -> dict:
    class_obj = class_scope(_class_id(arguments), grant.instructor_id, write=False, owner=False).class_obj
    return {"participants": _as_screen_json(_serialize_members(class_obj))}


def _get_roster_grid(grant: ConnectedApp, arguments: dict) -> dict:
    class_obj = class_scope(_class_id(arguments), grant.instructor_id, write=False, owner=False).class_obj
    return _as_screen_json(_build_roster_grid(class_obj))


#: 명단 격자·참여자 리포트가 함께 쓰는 「공모전에도 냈다」 칸(#550).
CONTEST_ENTRY_CELL_SCHEMA = {
    "type": ["string", "null"],
    "enum": ["current", "entered", None],
    "description": (
        "공모전 문제에서만 — current: 지금 그 공모전의 제출이 이 칸의 시도다, entered: 공모전에도 "
        "냈었지만 지금 제출은 다른 시도·직접 고친 것이다, null: 낸 적 없다. 근거·공모전 점수·수상은 "
        "알려 주지 않는다"
    ),
}


# --- 입력·출력 모양 ----------------------------------------------------------------

_CLASS_ID = {"type": "integer", "description": "클래스 번호(내 클래스 목록의 id)"}
_PROBLEM_ID = {"type": "integer", "description": "문제 번호(문제 목록의 id)"}
_COUNT = {"type": "integer", "minimum": 0}
_NULLABLE_INT = {"type": ["integer", "null"]}
_DATETIME = {"type": "string", "description": "ISO 8601 시각"}
_PROBLEM_STATUS = {
    "type": "string",
    "enum": ["draft", "open", "hidden"],
    "description": "문제 상태 — draft 초안(참여자에게 안 보인다), open 열림, hidden 숨김(새 제출이 닫힌다)",
}
_PASS_RATE = {
    "type": ["number", "null"],
    "description": "달성률(통과한 참여자 수 / 참여자 수). 참여자가 없으면 null",
}
_TEMPLATE_SUMMARY = {
    "type": ["object", "null"],
    "description": "이것을 원본으로 지금 공개돼 있는 템플릿. 없으면 null",
    "properties": {
        "share_code": {"type": "string", "description": "공유 코드"},
        "publisher_display_name": {"type": "string", "description": "공개한 사람으로 보이는 이름"},
        "created_at": _DATETIME,
    },
}

_CLASS_ONLY_INPUT = {
    "type": "object",
    "properties": {"class_id": _CLASS_ID},
    "required": ["class_id"],
    "additionalProperties": False,
}

_PROBLEM_OBJECT = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "문제 번호"},
        "classroom_id": {"type": "integer", "description": "클래스 번호"},
        "title": {"type": "string", "description": "제목"},
        "description": {"type": "string", "description": "설명(마크다운)"},
        "submission_formats": {
            "type": "array",
            "items": {"type": "string", "enum": ["source", "repository"]},
            "description": "받는 제출 형식 — source 소스(zip·파일), repository 저장소(GitHub URL)",
        },
        "status": _PROBLEM_STATUS,
        "order": {"type": "integer", "description": "클래스 안의 순서"},
        "model": {"type": "string", "description": "이 문제 자신의 채점 모델. 빈 문자열이면 클래스 기본값을 따른다"},
        "effective_model": {"type": "string", "description": "실제로 채점에 쓰일 모델"},
        "effective_model_is_reasoning": {"type": "boolean"},
        "reasoning_effort": {"type": "string", "description": "이 문제 자신의 추론 강도. 빈 문자열이면 클래스 기본값"},
        "effective_reasoning_effort": {"type": "string", "description": "실제로 쓰일 추론 강도(low·medium·high)"},
        "scoring_model_rejected": {
            "type": "boolean",
            "description": "OpenAI 가 이 문제의 채점 모델을 거부했는가 — 참이면 어느 시도도 채점되지 않는다",
        },
        "grading_strictness": {
            "type": "string",
            "enum": ["strict", "normal", "lenient", "custom"],
            "description": "채점 지침 — 엄격·보통·관대·직접 입력",
        },
        "grading_guideline_text": {"type": "string", "description": "직접 쓴 채점 지침(custom 일 때만)"},
        "syntax_check_enabled": {"type": "boolean", "description": "문법 검사 항목이 켜져 있는가"},
        "checklist_items": {
            "type": "array",
            "description": "체크리스트 — 필수 항목을 모두 만족해야 통과다",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string", "description": "항목 문장"},
                    "required": {"type": "boolean", "description": "필수 항목인가"},
                    "order": {"type": "integer"},
                },
                "required": ["id", "label", "required", "order"],
            },
        },
        "passed_count": {**_COUNT, "description": "한 번이라도 통과한 참여자 수(강사(소유자·공동 강사)·내보낸 참여자 제외)"},
        "member_count": {**_COUNT, "description": "참여자 수(강사(소유자·공동 강사)·내보낸 참여자 제외)"},
        "pass_rate": _PASS_RATE,
        "published_template": _TEMPLATE_SUMMARY,
        "deletable": {
            "type": "boolean",
            "description": "지금 지울 수 있는가 — 강사(소유자·공동 강사)가 아닌 누군가의 시도가 하나라도 있으면 거짓",
        },
        "available_transitions": {
            "type": "array",
            "description": "지금 상태에서 할 수 있는 상태 바꾸기 — open 열기·hide 숨기기·reopen 다시 열기",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["open", "hide", "reopen"]},
                    "to_state": _PROBLEM_STATUS,
                    "blocked_reason": {
                        "type": ["string", "null"],
                        "description": "null 이면 지금 할 수 있다. archived 보관된 클래스, no_required_item 필수 체크리스트 항목이 없음",
                    },
                },
                "required": ["name", "to_state"],
            },
        },
    },
    "required": ["id", "classroom_id", "title", "description", "submission_formats", "status", "checklist_items"],
}

_PARTICIPANT_OBJECT = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "참여자 번호"},
        "display_name": {"type": "string", "description": "이 클래스에서 불릴 이름"},
        "joined_at": {**_DATETIME, "description": "가입한 시각(ISO 8601)"},
        "expelled": {"type": "boolean", "description": "내보낸 참여자인가 — 기록은 남고 새 제출만 막힌다"},
        "is_instructor": {"type": "boolean", "description": "강사(소유자·공동 강사)가 참여자로도 들어온 자리인가 — 집계에서 빠진다"},
    },
    "required": ["id", "display_name", "joined_at", "expelled", "is_instructor"],
}


CLASS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "클래스 번호"},
        "name": {"type": "string", "description": "클래스 이름"},
        "instructor_display_name": {"type": "string", "description": "소유자의 강사 이름 — 참여자에게 보인다"},
        "role": {
            "type": "string",
            "enum": ["owner", "co_instructor"],
            "description": "이 클래스에서 내 역할 — owner 소유자, co_instructor 공동 강사. 채점 키·예산·클래스 삭제는 소유자만 한다",
        },
        "join_code": {"type": "string", "description": "가입 링크의 코드"},
        "created_at": _DATETIME,
        "archived": {"type": "boolean", "description": "보관된 클래스인가 — 참이면 새 가입·새 제출이 닫히고 문제를 바꿀 수 없다"},
        "default_model": {"type": "string", "description": "기본 채점 모델"},
        "default_model_is_reasoning": {"type": "boolean"},
        "default_reasoning_effort": {"type": "string", "description": "기본 추론 강도(low·medium·high)"},
        "has_openai_key": {"type": "boolean", "description": "채점에 쓸 OpenAI 키가 들어 있는가"},
        "openai_key_status": {
            "type": ["string", "null"],
            "description": "키가 있을 때만 — verified 확인됨, unverified 확인 전, rejected 거부됨",
        },
        "token_budget": {**_NULLABLE_INT, "description": "채점 토큰 예산. null 이면 무제한"},
        "token_budget_warning_threshold_percent": {"type": "integer", "description": "경고 알림 임계(예산 대비 %)"},
        "token_usage_total": {**_COUNT, "description": "지금까지 채점에 쓴 토큰"},
        "token_budget_remaining": {**_NULLABLE_INT, "description": "남은 토큰. 예산이 없으면 null"},
        "token_budget_exhausted": {"type": "boolean", "description": "예산이 다 떨어져 채점이 멈춰 있는가"},
        "has_submissions": {"type": "boolean", "description": "어느 문제에든 제출이 하나라도 있는가"},
        "published_template": _TEMPLATE_SUMMARY,
    },
    "required": ["id", "name", "archived", "has_openai_key", "token_usage_total"],
}


READ_TOOL_SPECS: list[dict] = [
    {
        "name": "get_class",
        "title": "클래스 상세",
        "description": (
            "클래스 하나의 설정을 돌려준다 — 이름, 내 역할(소유자·공동 강사), 소유자의 강사 이름, 가입 코드, 보관 여부, 기본 채점 모델과 "
            "추론 강도, OpenAI 키가 있는가(키 값은 주지 않는다)와 그 상태, 채점 토큰 예산·사용량·남은 양·"
            "경고 임계, 제출이 있는가, 공개된 템플릿. 내가 강사가 아닌 클래스는 찾을 수 없다고 답한다."
        ),
        "input_schema": _CLASS_ONLY_INPUT,
        "output_schema": CLASS_OUTPUT_SCHEMA,
        "handler": _get_class,
    },
    {
        "name": "list_problems",
        "title": "문제 목록",
        "description": (
            "클래스의 문제 전부를 순서대로 돌려준다 — 초안·열림·숨김 모두. 문제마다 설명, 체크리스트, "
            "채점 설정(모델·추론 강도·채점 지침·문법 검사), 받는 제출 형식, 상태와 지금 할 수 있는 상태 "
            "바꾸기, 달성률, 지울 수 있는가를 담는다."
        ),
        "input_schema": _CLASS_ONLY_INPUT,
        "output_schema": {
            "type": "object",
            "properties": {"problems": {"type": "array", "items": _PROBLEM_OBJECT}},
            "required": ["problems"],
        },
        "handler": _list_problems,
    },
    {
        "name": "get_problem",
        "title": "문제 상세",
        "description": (
            "문제 하나를 돌려준다 — 문제 목록의 한 줄과 같은 모양이다(설명·체크리스트·채점 설정·상태·"
            "제출 형식·달성률)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"class_id": _CLASS_ID, "problem_id": _PROBLEM_ID},
            "required": ["class_id", "problem_id"],
            "additionalProperties": False,
        },
        "output_schema": _PROBLEM_OBJECT,
        "handler": _get_problem,
    },
    {
        "name": "list_participants",
        "title": "참여자 명단",
        "description": (
            "클래스의 참여자 명단을 돌려준다 — 참여자마다 이 클래스에서 불릴 이름, 가입한 시각, 내보냈는가, "
            "강사(소유자·공동 강사)의 자리인가. 이메일 같은 계정 정보는 담지 않는다."
        ),
        "input_schema": _CLASS_ONLY_INPUT,
        "output_schema": {
            "type": "object",
            "properties": {"participants": {"type": "array", "items": _PARTICIPANT_OBJECT}},
            "required": ["participants"],
        },
        "handler": _list_participants,
    },
    {
        "name": "get_roster_grid",
        "title": "명단 격자",
        "description": (
            "참여자 × 문제 격자 — 누가 어느 문제에서 막혔는지. problems 는 문제마다 상태와 달성률, members 는 "
            "참여자마다 문제별 칸이다. 칸의 status 는 통과 이력이다(최신 시도가 아니다): passed 한 번이라도 "
            "통과, attempted_not_passed 채점됐지만 통과 없음, scoring 채점을 기다림, needs_setup 강사가 키나 "
            "채점 모델을 손봐야 채점됨, not_submitted 시도 없음."
        ),
        "input_schema": _CLASS_ONLY_INPUT,
        "output_schema": {
            "type": "object",
            "properties": {
                "problems": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "description": "문제 번호"},
                            "title": {"type": "string"},
                            "status": _PROBLEM_STATUS,
                            "passed_count": _COUNT,
                            "member_count": _COUNT,
                            "pass_rate": _PASS_RATE,
                        },
                        "required": ["id", "title", "status", "passed_count", "member_count"],
                    },
                },
                "members": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "description": "참여자 번호"},
                            "display_name": {"type": "string", "description": "이 클래스에서 불릴 이름"},
                            "is_instructor": {"type": "boolean"},
                            "expelled": {"type": "boolean", "description": "내보낸 참여자인가"},
                            "cells": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "problem_id": {"type": "integer"},
                                        "status": {
                                            "type": "string",
                                            "enum": [
                                                "passed",
                                                "attempted_not_passed",
                                                "scoring",
                                                "needs_setup",
                                                "not_submitted",
                                            ],
                                        },
                                        "contest_entry": CONTEST_ENTRY_CELL_SCHEMA,
                                    },
                                    "required": ["problem_id", "status"],
                                },
                            },
                        },
                        "required": ["id", "display_name", "is_instructor", "expelled", "cells"],
                    },
                },
            },
            "required": ["problems", "members"],
        },
        "handler": _get_roster_grid,
    },
]
