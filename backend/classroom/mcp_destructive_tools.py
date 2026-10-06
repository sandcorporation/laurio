"""연결된 앱의 되돌릴 수 없는 도구 — 두 단계 확인 (#515, spec #511 User Story 7, ADR-0052).

문제 삭제·클래스 삭제·참여자 내보내기·템플릿 공개(문제 하나·클래스 통째). 도구마다 MCP
`destructiveHint` 를 붙이고, **확인 표 없이 불리면 실행하지 않는다** — 무엇이 사라지거나
나가는지의 미리보기와 확인 표만 돌려준다(`classroom.mcp_confirmation`). 같은 인자에 그 표를
더해 다시 불러야 실행되고, 그때 다른 쓰기처럼 `ConnectedAppWrite` 한 줄이 남는다. 미리보기만
받은 호출은 남지 않는다 — 바뀐 것이 없다.

**규칙은 화면과 한 벌이다.** 범위는 화면 라우트와 같은 `instructor_scope`(남의 것은 「없다」,
문제 삭제는 보관 잠금), 판정은 화면 라우트가 부르는 바로 그 함수(`api.ensure_problem_deletable`
·`ensure_class_deletable`·`class_member_or_404`, 템플릿 공개자 이름의 금칙어)다. 그 판정을
**미리보기에서도 실행에서도** 부른다: 화면이 막을 일이면 표를 내주지 않고 그 문장으로
거절하고, 표를 받은 뒤 상태가 바뀌었으면(그 사이 참여자가 냈다) 실행이 같은 문장으로
거절된다.

**할 일이 없으면 표를 내주지 않는다.** 이미 내보낸 참여자, 같은 원본에서 이미 공개된(내리지
않은) 템플릿은 화면에서도 아무것도 바뀌지 않는 멱등 호출이다 — `status: "nothing_to_do"` 와
지금 모습을 돌려준다.
"""

from __future__ import annotations

from collections import Counter

from .api import (
    _reject_if_banned_name,
    class_member_or_404,
    ensure_class_deletable,
    ensure_problem_deletable,
    expel_class_member,
    remove_class,
    remove_problem,
)
from .instructor_scope import class_scope, problem_scope
from .instructors import instructor_user_ids, is_instructor
from .mcp_confirmation import CONFIRMATION_ARGUMENT, CONFIRMATION_SCHEMA, needs_confirmation, presented, redeem
from .mcp_problem_tools import _check_arguments, _id, _object, _parse
from .mcp_tool import Preview, Tool, WriteResult
from .models import (
    Class,
    ClassMember,
    ClassroomSubmission,
    ClassTemplate,
    ConnectedApp,
    Problem,
    ProblemTemplate,
)
from .schemas import PublishTemplateIn
from .template_api import publish_class_template_checked, publish_problem_template_checked

# --- 공통 ----------------------------------------------------------------------


def _two_steps(grant: ConnectedApp, tool: str, arguments: dict, preview: dict, execute) -> Preview | WriteResult:
    """판정을 마친 뒤 부른다 — 표가 없으면 미리보기, 있으면 표를 쓰고 실행한다."""

    token = presented(arguments)
    if token is None:
        return Preview(needs_confirmation(grant, tool, arguments, preview))
    redeem(grant, tool, arguments, token)
    return execute()


def _nothing_to_do(reason: str, **current) -> Preview:
    return Preview({"status": "nothing_to_do", "reason": reason, **current})


def _status_counts(problems) -> dict:
    counts = Counter(p.status for p in problems)
    return {status: counts.get(status, 0) for status, _ in Problem.Status.choices}


_CLASS_ID = {"type": "integer", "description": "클래스 번호(내 클래스 목록의 id)"}
_PROBLEM_ID = {"type": "integer", "description": "문제 번호"}
_PUBLISHER = {
    "type": "string",
    "minLength": 1,
    "maxLength": 100,
    "description": "템플릿 목록에 공개자로 보일 이름. 계정 이름을 끌어오지 않으니 직접 적는다.",
}
_RESULT = {
    "type": "object",
    "description": (
        "status 가 needs_confirmation 이면 아무것도 바뀌지 않았고 preview·confirmation 이 있다. "
        "done 이면 실행됐다. nothing_to_do 면 할 일이 없었다(reason)."
    ),
    "properties": {
        "status": {"type": "string", "enum": ["needs_confirmation", "done", "nothing_to_do"]},
        "preview": {"type": "object", "description": "무엇이 사라지거나 나가는가"},
        "confirmation": {"type": "string", "description": "확인 표 — 같은 인자에 더해 다시 부르면 실행된다"},
        "expires_at": {"type": "string", "description": "확인 표가 끝나는 시각(ISO 8601)"},
        "how_to_confirm": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["status"],
}
_FLOW = (
    "되돌릴 수 없어 두 단계다: confirmation 없이 부르면 실행하지 않고 미리보기와 확인 표를 돌려준다. "
    "미리보기를 사용자에게 보여 주고 동의를 받은 뒤 같은 인자에 confirmation 을 더해 다시 부르면 실행된다."
)

# --- 문제 삭제 -------------------------------------------------------------------

_DELETE_PROBLEM_INPUT = _object(
    {"class_id": _CLASS_ID, "problem_id": _PROBLEM_ID, CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA},
    ["class_id", "problem_id"],
)


def _delete_problem(grant: ConnectedApp, arguments: dict) -> Preview | WriteResult:
    _check_arguments(arguments, _DELETE_PROBLEM_INPUT)
    scope = problem_scope(_id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=True, owner=False)
    class_obj, problem = scope.class_obj, scope.problem
    ensure_problem_deletable(problem, class_obj)

    checklist_count = problem.checklist_items.count()
    # 「강사 자신의 시도」는 화면의 삭제 판정(`classroom.api._problem_deletable`)과 같은 사람들이다.
    own_attempts = ClassroomSubmission.objects.filter(
        problem=problem, member__user_id__in=instructor_user_ids(class_obj)
    ).count()
    template_kept = ProblemTemplate.objects.filter(source_problem=problem, taken_down_at__isnull=True).exists()
    preview = {
        "class": {"id": class_obj.id, "name": class_obj.name},
        "problem": {"id": problem.id, "title": problem.title, "status": problem.status},
        "checklist_item_count": checklist_count,
        "instructor_attempt_count": own_attempts,
        "participant_attempt_count": 0,
        "published_template_kept": template_kept,
        "summary": (
            f"문제 「{problem.title}」와 체크리스트 항목 {checklist_count}개가 사라진다. "
            + (f"강사(소유자·공동 강사)가 내본 시도 {own_attempts}개와 그 채점도 함께 사라진다. " if own_attempts else "")
            + "참여자의 시도는 없다. "
            + ("공개한 템플릿은 사본이라 그대로 남는다. " if template_kept else "")
            + "되돌릴 수 없다."
        ),
    }

    def execute() -> WriteResult:
        title = problem.title
        remove_problem(class_obj, problem)
        return WriteResult(
            structured={"status": "done", "deleted_problem": {"id": arguments["problem_id"], "title": title}},
            class_id=class_obj.id,
            problem_id=arguments["problem_id"],
            summary=f"「{title}」 삭제 — 체크리스트 {checklist_count}개, 강사의 시도 {own_attempts}개",
        )

    return _two_steps(grant, "delete_problem", arguments, preview, execute)


# --- 클래스 삭제 ------------------------------------------------------------------

_DELETE_CLASS_INPUT = _object({"class_id": _CLASS_ID, CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA}, ["class_id"])


def _delete_class(grant: ConnectedApp, arguments: dict) -> Preview | WriteResult:
    _check_arguments(arguments, _DELETE_CLASS_INPUT)
    # 화면(`classroom.api.delete_class`)과 같다 — 보관된 클래스도 지울 수 있고, 소유자만 지운다(ADR-0055).
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=True).class_obj
    ensure_class_deletable(class_obj)

    problems = list(class_obj.problems.order_by("order", "id"))
    members = list(class_obj.members.all())
    instructor_ids = instructor_user_ids(class_obj)
    participants = [m for m in members if m.user_id not in instructor_ids]
    expelled = sum(1 for m in participants if m.expelled_at is not None)
    template_kept = ClassTemplate.objects.filter(source_class=class_obj, taken_down_at__isnull=True).exists()
    preview = {
        "class": {"id": class_obj.id, "name": class_obj.name, "archived": class_obj.archived_at is not None},
        "problem_count": len(problems),
        "problem_counts": _status_counts(problems),
        "problems": [{"id": p.id, "title": p.title, "status": p.status} for p in problems],
        "participant_count": len(participants) - expelled,
        "expelled_participant_count": expelled,
        "submission_count": 0,
        "published_template_kept": template_kept,
        "summary": (
            f"클래스 「{class_obj.name}」와 그 안의 문제 {len(problems)}개(체크리스트 포함), "
            f"참여자 {len(participants)}명의 가입"
            + (f"(내보낸 {expelled}명 포함)" if expelled else "")
            + "이 사라지고 가입 링크도 끊긴다. 제출은 없다. "
            + ("이 클래스에서 공개한 템플릿은 사본이라 그대로 남는다. " if template_kept else "")
            + "보관과 달리 되돌릴 수 없다."
        ),
    }

    def execute() -> WriteResult:
        name, class_id = class_obj.name, class_obj.id
        remove_class(class_obj)
        return WriteResult(
            structured={"status": "done", "deleted_class": {"id": class_id, "name": name}},
            class_id=class_id,
            summary=f"「{name}」 삭제 — 문제 {len(problems)}개, 참여자 {len(participants)}명",
        )

    return _two_steps(grant, "delete_class", arguments, preview, execute)


# --- 참여자 내보내기 ----------------------------------------------------------------

_EXPEL_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "member_id": {"type": "integer", "description": "참여자 번호(참여자 명단의 id)"},
        CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA,
    },
    ["class_id", "member_id"],
)


def _member_out(member: ClassMember, class_obj: Class) -> dict:
    return {
        "id": member.id,
        "display_name": member.display_name,
        "joined_at": member.joined_at.isoformat(),
        "expelled": member.expelled_at is not None,
        "is_instructor": is_instructor(class_obj, member.user_id),
    }


def _expel_member(grant: ConnectedApp, arguments: dict) -> Preview | WriteResult:
    _check_arguments(arguments, _EXPEL_INPUT)
    # 화면(`classroom.api.expel_member`)과 같다 — 보관된 클래스에서도 명단 정리는 열려 있다.
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False).class_obj
    member = class_member_or_404(class_obj, _id(arguments, "member_id"))
    if member.expelled_at is not None:
        return _nothing_to_do("이미 내보낸 참여자입니다.", member=_member_out(member, class_obj))

    attempts = ClassroomSubmission.objects.filter(member=member).count()
    preview = {
        "class": {"id": class_obj.id, "name": class_obj.name},
        "member": _member_out(member, class_obj),
        "attempt_count": attempts,
        "summary": (
            f"「{member.display_name}」을(를) 클래스 「{class_obj.name}」에서 내보낸다. 이 클래스에 더는 낼 수 "
            f"없고 달성률에서 빠진다. 지난 시도 {attempts}개와 판정은 그 사람의 기록으로 남는다. "
            "다시 들이는 길은 없다."
        ),
    }

    def execute() -> WriteResult:
        expelled = expel_class_member(member)
        return WriteResult(
            structured={"status": "done", "member": _member_out(expelled, class_obj)},
            class_id=class_obj.id,
            summary=f"참여자 {expelled.id} 「{expelled.display_name}」 내보냄",
        )

    return _two_steps(grant, "expel_member", arguments, preview, execute)


# --- 템플릿 공개 -----------------------------------------------------------------

_COPIED = "제목·설명·제출 형식·체크리스트·채점 지침·문법 검사 설정"
_NOT_COPIED = "채점 모델·추론 강도·참여자와 시도·채점 연결"
_WHO_SEES = (
    "강의실에 로그인한 누구나 템플릿 목록에서 보고 자기 클래스로 가져갈 수 있다. 나중에 내릴 수는 있지만 "
    "이미 가져간 사본은 그 사람의 것으로 남는다."
)


def _publisher_name(arguments: dict) -> str:
    name = _parse(PublishTemplateIn, {"publisher_display_name": arguments.get("publisher_display_name")})
    _reject_if_banned_name(name.publisher_display_name)
    return name.publisher_display_name


def _problem_template_out(template: ProblemTemplate) -> dict:
    return {
        "share_code": template.share_code,
        "title": template.title,
        "publisher_display_name": template.publisher_display_name,
    }


def _class_template_out(template: ClassTemplate) -> dict:
    return {
        "share_code": template.share_code,
        "name": template.name,
        "publisher_display_name": template.publisher_display_name,
    }


_PUBLISH_PROBLEM_INPUT = _object(
    {
        "class_id": _CLASS_ID,
        "problem_id": _PROBLEM_ID,
        "publisher_display_name": _PUBLISHER,
        CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA,
    },
    ["class_id", "problem_id", "publisher_display_name"],
)


def _publish_problem_template(grant: ConnectedApp, arguments: dict) -> Preview | WriteResult:
    _check_arguments(arguments, _PUBLISH_PROBLEM_INPUT)
    # 화면(`classroom.template_api.publish_template`)과 같다 — 원본을 바꾸지 않으므로 보관이어도 된다.
    scope = problem_scope(_id(arguments, "class_id"), _id(arguments, "problem_id"), grant.instructor_id, write=False, owner=False)
    class_obj, problem = scope.class_obj, scope.problem
    publisher = _publisher_name(arguments)
    live = ProblemTemplate.objects.filter(source_problem=problem, taken_down_at__isnull=True).first()
    if live is not None:
        return _nothing_to_do("이 문제는 이미 템플릿으로 공개돼 있습니다.", template=_problem_template_out(live))

    items = list(problem.checklist_items.all())
    preview = {
        "problem": {"id": problem.id, "title": problem.title, "status": problem.status},
        "publisher_display_name": publisher,
        "checklist_items": [{"label": i.label, "required": i.required} for i in items],
        "copied": _COPIED,
        "not_copied": _NOT_COPIED,
        "who_sees": _WHO_SEES,
        "summary": (
            f"문제 「{problem.title}」의 지금 모습({_COPIED}, 체크리스트 항목 {len(items)}개)을 "
            f"「{publisher}」 이름으로 공개한다. {_NOT_COPIED}은 따라가지 않는다. {_WHO_SEES}"
        ),
    }

    def execute() -> Preview | WriteResult:
        template, created = publish_problem_template_checked(
            problem, published_by_id=grant.instructor_id, publisher_display_name=publisher
        )
        if not created:  # 확인 사이에 화면에서 먼저 공개했다
            return _nothing_to_do("이 문제는 이미 템플릿으로 공개돼 있습니다.", template=_problem_template_out(template))
        return WriteResult(
            structured={"status": "done", "template": _problem_template_out(template)},
            class_id=class_obj.id,
            problem_id=problem.id,
            summary=f"「{problem.title}」 템플릿 공개 — 공개자 「{publisher}」",
        )

    return _two_steps(grant, "publish_problem_template", arguments, preview, execute)


_PUBLISH_CLASS_INPUT = _object(
    {"class_id": _CLASS_ID, "publisher_display_name": _PUBLISHER, CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA},
    ["class_id", "publisher_display_name"],
)


def _publish_class_template(grant: ConnectedApp, arguments: dict) -> Preview | WriteResult:
    _check_arguments(arguments, _PUBLISH_CLASS_INPUT)
    # 화면(`classroom.template_api.publish_class_template`)과 같다.
    class_obj = class_scope(_id(arguments, "class_id"), grant.instructor_id, write=False, owner=False).class_obj
    publisher = _publisher_name(arguments)
    live = ClassTemplate.objects.filter(source_class=class_obj, taken_down_at__isnull=True).first()
    if live is not None:
        return _nothing_to_do("이 클래스는 이미 템플릿으로 공개돼 있습니다.", template=_class_template_out(live))

    problems = list(class_obj.problems.order_by("order", "id"))
    counts = _status_counts(problems)
    preview = {
        "class": {"id": class_obj.id, "name": class_obj.name},
        "publisher_display_name": publisher,
        "problem_count": len(problems),
        "problem_counts": counts,
        "problems": [{"id": p.id, "title": p.title, "status": p.status} for p in problems],
        "copied": f"클래스 이름, 문제 전부와 순서, 문제마다 {_COPIED}",
        "not_copied": f"{_NOT_COPIED}·가입 링크",
        "who_sees": _WHO_SEES,
        "summary": (
            f"클래스 「{class_obj.name}」의 문제 {len(problems)}개를 통째로 「{publisher}」 이름으로 공개한다"
            + (
                f" — 초안 {counts['draft']}개·숨김 {counts['hidden']}개도 함께 공개된다"
                if counts["draft"] or counts["hidden"]
                else ""
            )
            + f". {_NOT_COPIED}·가입 링크는 따라가지 않는다. {_WHO_SEES}"
        ),
    }

    def execute() -> Preview | WriteResult:
        template, created = publish_class_template_checked(
            class_obj, published_by_id=grant.instructor_id, publisher_display_name=publisher
        )
        if not created:
            return _nothing_to_do("이 클래스는 이미 템플릿으로 공개돼 있습니다.", template=_class_template_out(template))
        return WriteResult(
            structured={"status": "done", "template": _class_template_out(template)},
            class_id=class_obj.id,
            summary=f"「{class_obj.name}」 클래스 템플릿 공개 — 문제 {len(problems)}개, 공개자 「{publisher}」",
        )

    return _two_steps(grant, "publish_class_template", arguments, preview, execute)


# --- 등록 ----------------------------------------------------------------------


def _tool(name: str, title: str, description: str, input_schema: dict, handler) -> Tool:
    return Tool(
        name=name,
        title=title,
        description=f"{description} {_FLOW}",
        input_schema=input_schema,
        output_schema=_RESULT,
        read_only=False,
        destructive=True,
        handler=handler,
    )


DESTRUCTIVE_TOOLS: list[Tool] = [
    _tool(
        "delete_problem",
        "문제 삭제",
        "문제를 체크리스트와 함께 지운다. 참여자의 시도(내보낸 참여자 포함)가 하나라도 있으면 지울 수 없다 — "
        "그때는 숨긴다. 강사(소유자·공동 강사)만 내본 문제는 지울 수 있고 그 시도와 채점도 함께 사라진다. "
        "보관된 클래스에서는 할 수 없다.",
        _DELETE_PROBLEM_INPUT,
        _delete_problem,
    ),
    _tool(
        "delete_class",
        "클래스 삭제",
        "클래스를 문제·체크리스트·참여자 가입과 함께 지운다. 제출이 하나라도 있으면 지울 수 없다 — 그때는 보관한다. "
        "소유자만 지울 수 있다 — 공동 강사가 부르면 거절된다.",
        _DELETE_CLASS_INPUT,
        _delete_class,
    ),
    _tool(
        "expel_member",
        "참여자 내보내기",
        "참여자를 클래스에서 내보낸다. 더는 낼 수 없고 달성률에서 빠지며, 지난 시도와 판정은 남는다. "
        "다시 들이는 길은 없다. 이미 내보낸 참여자면 아무것도 하지 않는다.",
        _EXPEL_INPUT,
        _expel_member,
    ),
    _tool(
        "publish_problem_template",
        "문제를 템플릿으로 공개",
        "문제 하나의 지금 모습을 사본으로 떠 템플릿 목록에 공개한다. 로그인한 누구나 보고 가져갈 수 있다. "
        "같은 문제가 이미 공개돼 있으면 새로 만들지 않는다.",
        _PUBLISH_PROBLEM_INPUT,
        _publish_problem_template,
    ),
    _tool(
        "publish_class_template",
        "클래스를 템플릿으로 공개",
        "클래스의 문제 전부(초안·숨김 포함)와 순서를 사본으로 떠 템플릿 목록에 공개한다. 로그인한 누구나 보고 "
        "가져갈 수 있다. 같은 클래스가 이미 공개돼 있으면 새로 만들지 않는다.",
        _PUBLISH_CLASS_INPUT,
        _publish_class_template,
    ),
]
