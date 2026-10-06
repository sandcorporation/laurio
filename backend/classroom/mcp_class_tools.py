"""연결된 앱이 클래스를 다루는 MCP 도구들 (#516, spec #511 User Stories 5·6·10).

만들기·복사·보관·보관 되돌리기·설정 고치기·내 강사 이름 바꾸기(#576)·가입 링크 다시 발급·
템플릿 가져오기(문제·클래스).

**화면과 규칙이 한 벌이다.** 도구마다 화면 라우트와 같은 강사 범위(`class_scope`)를 같은
`write` 값으로 연다 — 보관 뒤에도 열려 있는 것(설정·복사·보관 되돌리기·링크 재발급,
`classroom.participation` 「열어 두는 것」)은 `write=False`, 보관된 클래스에 새 내용을
만드는 문제 템플릿 가져오기는 `write=True`. 그리고 화면 라우트가 부르는 바로 그 함수
(`classroom.class_authoring`, `services.copy_class`, `services.import_problem_template`)를
부른다. 인자는 화면 입력 스키마(`ClassIn`·`ClassPatchIn`·`ImportTemplateIn`·
`ImportClassTemplateIn`)로 검증하므로 금칙어가 덮는 칸도 화면과 같다.

**OpenAI 키는 여기 없다**(#511 「OpenAI 키」). 키를 넣거나 바꾸거나 지우는 도구가 없고,
설정 고치기의 입력 스키마에도 키 칸이 없어 `api_key` 같은 인자는 「알 수 없는 인자」로
거절된다 — 비밀값이 대화 기록과 AI 업체에 남지 않는다. 결과의 클래스도 키의 가린 표시
없이 「키가 있는가」만 싣는다(`mcp_read_tools.class_view`).

**전부 쓰기 도구다**(`read_only=False`) — 디스패치가 성공한 호출마다 `ConnectedAppWrite`
한 줄을 남긴다(`classroom.mcp_tool` docstring). 클래스 삭제·템플릿 공개는 두 단계 확인과
함께 #515 가 연다 — 여기는 되돌릴 수 있는 쓰기만 있다.
"""

from __future__ import annotations

from . import class_authoring, co_instructors
from .instructor_scope import class_scope
from .mcp_problem_tools import _PROBLEM_RESULT, _check_arguments, _id, _object, _parse, _problem_out, _without
from .mcp_read_tools import CLASS_OUTPUT_SCHEMA, class_view
from .mcp_tool import Tool, ToolInputError, WriteResult
from .models import ConnectedApp
from .schemas import ClassIn, ClassPatchIn, ImportClassTemplateIn, InstructorNameIn
from .scoring_models import REASONING_EFFORT_CHOICES
from .services import copy_class, import_problem_template

_CLASS_ID = {"type": "integer", "description": "클래스 번호(내 클래스 목록의 id)"}
_CLASS_NAME = {"type": "string", "minLength": 1, "maxLength": 200, "description": "클래스 이름"}
_INSTRUCTOR_DISPLAY_NAME = {
    "type": "string",
    "minLength": 1,
    "maxLength": 100,
    "description": "이 클래스에서 강사로 불릴 이름 — 가입 미리보기에 이메일 대신 뜬다.",
}
_SHARE_CODE = {"type": "string", "minLength": 1, "description": "템플릿의 공유 코드(공유 링크 끝부분)"}
_CLASS_RESULT = _object({"class": CLASS_OUTPUT_SCHEMA}, ["class"])


def _share_code(arguments: dict) -> str:
    value = arguments.get("share_code")
    if not isinstance(value, str) or not value:
        raise ToolInputError("share_code 는 비어 있지 않은 문자열이어야 합니다.")
    return value


def _class_result(grant: ConnectedApp, class_obj, summary: str) -> WriteResult:
    return WriteResult(
        structured={"class": class_view(class_obj, grant.instructor_id)}, class_id=class_obj.id, summary=summary
    )


# --- 만들기·복사 ------------------------------------------------------------------

_CREATE_CLASS_INPUT = _object(
    {"name": _CLASS_NAME, "instructor_display_name": _INSTRUCTOR_DISPLAY_NAME},
    ["name", "instructor_display_name"],
)


def _create_class(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _CREATE_CLASS_INPUT)
    payload = _parse(ClassIn, arguments)
    class_obj = class_authoring.create_class(grant.instructor_id, payload)
    return _class_result(grant, class_obj, f"「{class_obj.name}」")


_CLASS_REF_INPUT = _object({"class_id": _CLASS_ID}, ["class_id"])


def _copy_class(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _CLASS_REF_INPUT)
    # 화면의 복사(`classroom.api.copy_class_view`)와 같은 문 — 원본을 바꾸지 않으므로
    # 보관된 클래스도 복사해 새로 연다.
    source = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False).class_obj
    new_class = copy_class(source, grant.instructor_id)
    return _class_result(grant, new_class, f"「{new_class.name}」 — 클래스 {source.id}에서 복사")


# --- 보관 ----------------------------------------------------------------------


def _archive_handler(archive: bool):
    def handler(grant: ConnectedApp, arguments: dict) -> WriteResult:
        _check_arguments(arguments, _CLASS_REF_INPUT)
        class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False).class_obj
        if archive:
            class_authoring.archive_class(class_obj)
        else:
            class_authoring.unarchive_class(class_obj)
        return _class_result(grant, class_obj, f"「{class_obj.name}」")

    return handler


# --- 설정 ----------------------------------------------------------------------

_UPDATE_CLASS_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "name": _CLASS_NAME,
        "instructor_display_name": {
            **_INSTRUCTOR_DISPLAY_NAME,
            "description": (
                "소유자가 이 클래스에서 강사로 불릴 이름 — 소유자만 고친다. 내 강사 이름은 "
                "rename_my_instructor_name 으로 바꾼다."
            ),
        },
        "default_model": {
            "type": "string",
            "description": "기본 채점 모델 — 자기 모델을 정하지 않은 문제가 따른다. 클래스의 OpenAI 키로 쓸 수 있는 모델이어야 한다.",
        },
        "default_reasoning_effort": {
            "type": "string",
            "enum": [v for v, _ in REASONING_EFFORT_CHOICES],
            "description": "기본 추론 강도(low·medium·high) — 채점 모델이 추론 모델일 때만 뜻이 있다.",
        },
        "token_budget": {
            "type": "integer",
            "minimum": 1,
            "description": "채점 토큰 예산 상한. 다 쓰면 채점이 멈춘다. 무제한으로 되돌리는 값은 없다.",
        },
        "token_budget_warning_threshold_percent": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "description": "예산의 몇 %를 쓰면 경고 알림을 보낼지(1~100).",
        },
    },
    ["class_id"],
)


def _update_class_settings(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _UPDATE_CLASS_INPUT)
    payload = _parse(ClassPatchIn, _without(arguments, "class_id"))
    # 화면의 설정 고치기(`classroom.api.update_class`)와 같은 문 — 보관 뒤에도 고친다.
    scope = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False)
    if class_authoring.touches_owner_only_fields(payload):
        scope.require_owner()
    class_obj = scope.class_obj
    class_authoring.update_class(class_obj, payload)
    changed = ", ".join(sorted(payload.model_fields_set)) or "없음"
    return _class_result(grant, class_obj, f"「{class_obj.name}」 — 고친 칸: {changed}")


# --- 내 강사 이름 (#576) -------------------------------------------------------------

_RENAME_MY_INSTRUCTOR_NAME_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "display_name": {
            **_INSTRUCTOR_DISPLAY_NAME,
            "description": "이 클래스에서 내가 강사로 불릴 이름 — 강사 목록과 가입 미리보기에 뜬다.",
        },
    },
    ["class_id", "display_name"],
)


def _rename_my_instructor_name(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _RENAME_MY_INSTRUCTOR_NAME_INPUT)
    payload = _parse(InstructorNameIn, _without(arguments, "class_id"))
    # 화면의 `PATCH .../instructors/me`(`classroom.api.rename_my_instructor_name`)와 같은 문 —
    # 소유자든 공동 강사든, 보관 뒤에도. 바꾸는 자리는 grant 의 강사 자신뿐이다.
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False).class_obj
    row = co_instructors.rename_myself(class_obj, grant.instructor_id, payload.display_name)
    return WriteResult(
        structured={"class_id": class_obj.id, "display_name": row["display_name"], "role": row["role"]},
        class_id=class_obj.id,
        summary=f"「{class_obj.name}」 — 내 강사 이름: {row['display_name']}",
    )


# --- 가입 링크 ---------------------------------------------------------------------


def _regenerate_join_link(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _CLASS_REF_INPUT)
    # 화면과 같다 — 보관된 클래스라도 재발급은 막지 않는다(가입은 `join_class` 가 따로 막는다).
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False).class_obj
    class_authoring.regenerate_join_link(class_obj)
    # 새 코드 자체는 기록에 남기지 않는다 — 기록은 「무엇을 했나」이지 링크 보관소가 아니다.
    return WriteResult(
        structured={"class_id": class_obj.id, "join_code": class_obj.join_code},
        class_id=class_obj.id,
        summary=f"「{class_obj.name}」",
    )


# --- 템플릿 가져오기 ------------------------------------------------------------

_IMPORT_PROBLEM_TEMPLATE_INPUT = _object(
    {
        "share_code": _SHARE_CODE,
        "target_class_id": {
            "type": "integer",
            "description": "가져와 넣을 내 클래스 번호. 보관된 클래스에는 넣을 수 없다.",
        },
    },
    ["share_code", "target_class_id"],
)


def _import_problem_template(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _IMPORT_PROBLEM_TEMPLATE_INPUT)
    # 화면(`classroom.template_api.import_template`)과 같은 순서 — 템플릿이 살아 있는지
    # 먼저, 그다음 넣을 클래스(보관이면 거절).
    template = class_authoring.visible_problem_template_or_404(_share_code(arguments))
    target_class = class_scope(_id(arguments, "target_class_id"), grant.instructor_id, write=True, owner=False).class_obj
    problem = import_problem_template(template, target_class)
    return WriteResult(
        structured={"problem": _problem_out(problem, target_class)},
        class_id=target_class.id,
        problem_id=problem.id,
        summary=f"「{problem.title}」 — 템플릿 {template.share_code}에서 가져옴",
    )


_IMPORT_CLASS_TEMPLATE_INPUT = _object(
    {
        "share_code": _SHARE_CODE,
        "name": {**_CLASS_NAME, "description": "가져와 새로 만들 클래스의 이름 — 원본 이름을 그대로 쓰지 않는다."},
    },
    ["share_code", "name"],
)


def _import_class_template(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _check_arguments(arguments, _IMPORT_CLASS_TEMPLATE_INPUT)
    share_code = _share_code(arguments)
    payload = _parse(ImportClassTemplateIn, _without(arguments, "share_code"))
    new_class = class_authoring.import_class_template_as(share_code, grant.instructor_id, payload)
    return _class_result(grant, new_class, f"「{new_class.name}」 — 템플릿 {share_code}에서 가져옴")


# --- 등록 ----------------------------------------------------------------------

CLASS_TOOLS: list[Tool] = [
    Tool(
        name="create_class",
        title="클래스 만들기",
        description=(
            "새 클래스를 만든다 — 이름과 강사로 불릴 이름. 새 클래스에는 가입 코드가 생기고, 채점에 쓸 "
            "OpenAI 키는 들어 있지 않다(키는 강사가 화면에서만 넣는다)."
        ),
        input_schema=_CREATE_CLASS_INPUT,
        output_schema=_CLASS_RESULT,
        read_only=False,
        handler=_create_class,
    ),
    Tool(
        name="copy_class",
        title="클래스 복사해서 새로 열기",
        description=(
            "클래스 하나를 문제·체크리스트·채점 설정과 함께 복사해 새 클래스로 연다. 이름 뒤에 「 사본」이 "
            "붙고, 새 가입 코드가 생긴다. 참여자·제출·OpenAI 키는 따라오지 않는다. 보관된 클래스도 복사할 수 있다."
        ),
        input_schema=_CLASS_REF_INPUT,
        output_schema=_CLASS_RESULT,
        read_only=False,
        handler=_copy_class,
    ),
    Tool(
        name="archive_class",
        title="클래스 보관",
        description=(
            "수업이 끝난 클래스를 보관한다 — 지우지 않는다. 새 가입·새 제출이 닫히고 문제를 바꿀 수 없게 "
            "되지만, 지난 문제·제출·판정은 그대로 읽힌다. 보관 되돌리기로 다시 진행중으로 돌릴 수 있다. "
            "이미 보관된 클래스면 아무것도 바뀌지 않는다."
        ),
        input_schema=_CLASS_REF_INPUT,
        output_schema=_CLASS_RESULT,
        read_only=False,
        handler=_archive_handler(True),
        idempotent=True,
    ),
    Tool(
        name="unarchive_class",
        title="클래스 보관 되돌리기",
        description="보관된 클래스를 다시 진행중으로 돌린다. 이미 진행중이면 아무것도 바뀌지 않는다.",
        input_schema=_CLASS_REF_INPUT,
        output_schema=_CLASS_RESULT,
        read_only=False,
        handler=_archive_handler(False),
        idempotent=True,
    ),
    Tool(
        name="update_class_settings",
        title="클래스 설정 고치기",
        description=(
            "클래스의 이름·강사로 불릴 이름·기본 채점 모델·기본 추론 강도·채점 토큰 예산·경고 임계를 고친다. "
            "보낸 칸만 바뀐다. 보관된 클래스도 고칠 수 있다. 채점 토큰 예산·경고 임계·강사로 불릴 이름(소유자의 "
            "이름이다)은 소유자만 고친다 — 공동 강사가 그 칸을 보내면 아무것도 바뀌지 않고 거절된다. "
            "소유자든 공동 강사든 내 강사 이름은 rename_my_instructor_name 으로 바꾼다. "
            "OpenAI 키는 이 도구로 넣거나 바꿀 수 없다 — 소유자가 화면에서만 넣는다."
        ),
        input_schema=_UPDATE_CLASS_INPUT,
        output_schema=_CLASS_RESULT,
        read_only=False,
        handler=_update_class_settings,
        idempotent=True,
    ),
    Tool(
        name="rename_my_instructor_name",
        title="내 강사 이름 바꾸기",
        description=(
            "이 클래스에서 내가 강사로 불릴 이름을 바꾼다 — 소유자든 공동 강사든 자기 이름만 바뀌고, 다른 "
            "강사의 이름은 바꿀 수 없다. 바뀐 이름은 강사 목록과 가입 미리보기에 뜬다. 보관된 클래스에서도 "
            "바꿀 수 있다."
        ),
        input_schema=_RENAME_MY_INSTRUCTOR_NAME_INPUT,
        output_schema=_object(
            {
                "class_id": {"type": "integer", "description": "클래스 번호"},
                "display_name": {"type": "string", "description": "바뀐 내 강사 이름"},
                "role": {
                    "type": "string",
                    "enum": ["owner", "co_instructor"],
                    "description": "이 클래스에서 내 역할 — owner 소유자, co_instructor 공동 강사",
                },
            },
            ["class_id", "display_name", "role"],
        ),
        read_only=False,
        handler=_rename_my_instructor_name,
        idempotent=True,
    ),
    Tool(
        name="regenerate_join_link",
        title="가입 링크 다시 발급",
        description=(
            "클래스의 가입 코드를 새로 뽑는다. 이전 링크는 그 순간부터 열리지 않는다 — 링크가 새어 나갔을 때 "
            "쓴다. 이미 가입한 참여자는 그대로다."
        ),
        input_schema=_CLASS_REF_INPUT,
        output_schema=_object(
            {
                "class_id": {"type": "integer", "description": "클래스 번호"},
                "join_code": {"type": "string", "description": "새 가입 코드"},
            },
            ["class_id", "join_code"],
        ),
        read_only=False,
        handler=_regenerate_join_link,
    ),
    Tool(
        name="import_problem_template",
        title="문제 템플릿 가져오기",
        description=(
            "공개된 문제 템플릿을 내 클래스의 새 문제로 가져온다 — 초안으로 맨 뒤에 붙고, 체크리스트가 순서 "
            "그대로 따라온다. 채점 모델은 클래스 기본값을 따른다. 보관된 클래스로는 가져올 수 없다."
        ),
        input_schema=_IMPORT_PROBLEM_TEMPLATE_INPUT,
        output_schema=_PROBLEM_RESULT,
        read_only=False,
        handler=_import_problem_template,
    ),
    Tool(
        name="import_class_template",
        title="클래스 템플릿 가져오기",
        description=(
            "공개된 클래스 템플릿을 새 클래스로 가져온다 — 이름은 직접 정하고, 문제들은 순서 그대로 초안으로 "
            "들어온다. 새 가입 코드가 생기고 OpenAI 키는 들어 있지 않다."
        ),
        input_schema=_IMPORT_CLASS_TEMPLATE_INPUT,
        output_schema=_CLASS_RESULT,
        read_only=False,
        handler=_import_class_template,
    ),
]
