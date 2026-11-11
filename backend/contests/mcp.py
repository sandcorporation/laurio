"""공모전 MCP 서버 — 무료 공모전을 만들고·고치고·관리하는 도구 (#870, ADR-0069).

몸(JSON-RPC·두 세대·인증·상한·쓰기 기록 트랜잭션)은 `core.mcp_server`. 여기에는 공모전 자원
(`contests.oauth.CONTESTS`), 도구, 입장 검사, 쓰기 기록(`ContestConnectedAppWrite`)이 있다.

**권한** (대표 결정):
- 매 호출: 개최 권한이 켜져 있어야 한다(`contests.oauth.admission_refusal`) — 운영자도 같다.
- 다루는 범위: 개최자는 **자기 sponsor 의 무료 공모전만**(남의 것은 목록에서 빠지고 번호로
  찌르면 404), 운영자(`is_staff`)는 모든 무료 공모전. 유료 공모전은 어느 도구도 다루지 않는다.
- 만들기는 늘 호출한 본인 명의다(운영자 포함).

**도구는 화면과 같은 서비스 함수를 부른다** — `contests.api.create_free_contest_draft` 등
(웹 뷰에서 떼어낸 몸). 화면의 4xx 는 도구 오류(`isError`)로 같은 문장 그대로 돌아간다.
참가자 정보는 표시 이름·제출 상태만 돌려준다(이메일·실명 없음).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Count, QuerySet
from ninja.errors import HttpError
from pydantic import ValidationError

from core.clock import Clock
from core.mcp_confirmation import CONFIRMATION_ARGUMENT, CONFIRMATION_SCHEMA, needs_confirmation, presented, redeem
from core.mcp_server import McpServer
from core.mcp_tool import Preview, Tool, ToolInputError, WriteResult
from core.models import ConnectedApp
from policies.scope import current_policy

from . import api as contest_api
from .archiving import archive_contest, archive_refusal, unarchive_contest
from .models import Category, Contest, ContestConnectedAppWrite, ContestSubmission, DeliverableType
from .oauth import CONTESTS, admission_refusal
from .schemas import ContestUpdateIn, FreeContestCreateIn, RequirementCreateIn, RequirementUpdateIn
from .transitions import claim_contest_transition

SERVER_NAME = "codemit-contests"

INSTRUCTIONS = (
    "Codemit 무료 공모전을 만들고 고치고 관리하는 도구들이다. 유료 공모전은 다루지 않고, 상금을 넣거나 "
    "유료로 바꿀 수 없다. 상태는 초안(draft) → 공개(published) → 마감(closed) → 선정(awarded) 또는 "
    "심사 종료(judging_ended) 순서로만 간다. 순서: list_contest_options 로 카테고리·산출물 번호를 고르고 "
    "create_free_contest 로 초안을 만든 뒤, 요구사항을 하나 이상 두고 publish_free_contest 로 공개한다. "
    "공개 중에는 마감 전까지 내용과 요구사항을 고칠 수 있고, 마감 뒤에는 고칠 수 없다. close_free_contest_now "
    "는 마감을 지금으로 당긴다. 마감 뒤 심사 기간 안에 award_submission 으로 수상작 하나를 고른다. "
    "보관(archive)은 초안·끝난 공모전·제출이 없는 공개 공모전만 되고, 공개 목록에서 숨길 뿐 지우지 않는다. "
    "보관·해제·마감·선정은 되돌릴 수 없거나 참가자에게 닿으므로 두 단계다 — 먼저 확인 표 없이 불러 미리보기를 "
    "사용자에게 보여 주고, 동의를 받으면 같은 인자에 confirmation 을 더해 다시 부른다."
)


# --- 범위 ----------------------------------------------------------------------


def _is_operator(grant: ConnectedApp) -> bool:
    return bool(grant.instructor.is_staff)


def _scope(grant: ConnectedApp) -> QuerySet[Contest]:
    """이 연결이 다룰 수 있는 공모전 — 무료만, 운영자가 아니면 자기 sponsor 의 것만."""

    queryset = Contest.objects.filter(is_free=True).select_related("sponsor", "category")
    if not _is_operator(grant):
        queryset = queryset.filter(sponsor__user_id=grant.instructor_id)
    return queryset


def _contest(grant: ConnectedApp, arguments: dict, *, lock: bool = False) -> Contest:
    contest_id = _int(arguments, "contest_id")
    queryset = _scope(grant)
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    contest = queryset.filter(pk=contest_id).first()
    if contest is None:
        # 유료 공모전·남의 공모전·없는 공모전이 같은 모양으로 거절된다 — 있는지를 알려주지 않는다.
        raise HttpError(404, "공모전을 찾을 수 없습니다.")
    return contest


# --- 인자 ----------------------------------------------------------------------


def _int(arguments: dict, name: str) -> int:
    value = arguments.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolInputError(f"{name} 는 정수여야 합니다.")
    return value


def _reject_unknown(arguments: dict, allowed: set[str]) -> None:
    unknown = set(arguments) - allowed
    if "prize" in unknown or "is_free" in unknown:
        raise ToolInputError("무료 공모전만 다룹니다 — 상금을 넣거나 유료로 바꿀 수 없습니다.")
    if unknown:
        raise ToolInputError(f"알 수 없는 인자입니다: {', '.join(sorted(unknown))}")


def _parse[T](schema: type[T], data: dict) -> T:
    try:
        return schema(**data)  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ToolInputError(f"인자가 올바르지 않습니다: {exc.errors()[0].get('msg', '')}") from exc


@dataclass(frozen=True)
class ContestWriteResult(WriteResult):
    """공모전 쓰기 — 기록에 남길 공모전 번호를 함께 싣는다."""

    contest_id: int | None = None


# --- 보기 ----------------------------------------------------------------------


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def contest_view(contest: Contest, grant: ConnectedApp) -> dict:
    mine = contest.sponsor.user_id == grant.instructor_id
    requirements = list(contest.requirements.order_by("order", "id"))
    return {
        "id": contest.id,
        "title": contest.title,
        "status": contest.status,
        "archived": contest.archived_at is not None,
        "mine": mine,
        "category_id": contest.category_id,
        "deliverable_type_ids": sorted(contest.deliverable_types.values_list("id", flat=True)),
        "require_demo_video": contest.require_demo_video,
        "require_screenshot": contest.require_screenshot,
        "description": contest.description,
        "deadline_at": _iso(contest.deadline_at),
        "judging_ends_at": _iso(contest.judging_ends_at),
        "allows_classroom_import": contest.allows_classroom_import,
        "submission_count": contest.submissions.count(),
        # 숨은 항목(#906)은 개최자 본인에게만 — 남의 공모전을 보면 개수만.
        "requirements": [
            {"id": r.id, "text": r.text, "grade": r.grade, "points": r.points, "hidden": r.hidden, "order": r.order}
            for r in requirements
            if mine or not r.hidden
        ],
        "hidden_requirement_count": sum(1 for r in requirements if r.hidden),
    }


def _result(grant: ConnectedApp, contest: Contest, summary: str) -> WriteResult:
    contest.refresh_from_db()
    return ContestWriteResult(structured={"contest": contest_view(contest, grant)}, contest_id=contest.id, summary=summary)


# --- 읽기 도구 -------------------------------------------------------------------

_ARCHIVED_FILTER = ("exclude", "only", "include")


def _list(grant: ConnectedApp, arguments: dict) -> dict:
    _reject_unknown(arguments, {"status", "archived"})
    queryset = _scope(grant).annotate(n_submissions=Count("submissions")).order_by("-created_at", "-id")
    status = arguments.get("status")
    if status is not None:
        if status not in Contest.Status.values:
            raise ToolInputError(f"status 는 {', '.join(Contest.Status.values)} 중 하나여야 합니다.")
        queryset = queryset.filter(status=status)
    archived = arguments.get("archived", "exclude")
    if archived not in _ARCHIVED_FILTER:
        raise ToolInputError("archived 는 exclude·only·include 중 하나여야 합니다.")
    if archived == "exclude":
        queryset = queryset.filter(archived_at__isnull=True)
    elif archived == "only":
        queryset = queryset.filter(archived_at__isnull=False)
    return {
        "contests": [
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "archived": c.archived_at is not None,
                "mine": c.sponsor.user_id == grant.instructor_id,
                "deadline_at": _iso(c.deadline_at),
                "submission_count": c.n_submissions,
            }
            for c in queryset[:200]
        ]
    }


def _get(grant: ConnectedApp, arguments: dict) -> dict:
    _reject_unknown(arguments, {"contest_id"})
    return {"contest": contest_view(_contest(grant, arguments), grant)}


def _options(grant: ConnectedApp, arguments: dict) -> dict:
    _reject_unknown(arguments, set())
    return {
        "categories": [{"id": c.id, "name": c.name} for c in Category.objects.filter(is_active=True).order_by("id")],
        "deliverable_types": [
            {"id": d.id, "name": d.name} for d in DeliverableType.objects.filter(is_active=True).order_by("id")
        ],
    }


def _submission_view(submission: ContestSubmission) -> dict:
    developer = submission.developer
    return {
        "id": submission.id,
        # 표시 이름만 — 이메일·실명은 돌려주지 않는다(#870).
        "developer_display_name": developer.display_name or f"Developer#{developer.id}",
        "submitted_at": _iso(submission.created_at),
        "awarded": hasattr(submission, "award"),
    }


def _list_submissions(grant: ConnectedApp, arguments: dict) -> dict:
    _reject_unknown(arguments, {"contest_id"})
    contest = _contest(grant, arguments)
    submissions = contest.submissions.select_related("developer").order_by("created_at", "id")
    return {"contest_id": contest.id, "submissions": [_submission_view(s) for s in submissions]}


def _get_submission(grant: ConnectedApp, arguments: dict) -> dict:
    _reject_unknown(arguments, {"contest_id", "submission_id"})
    contest = _contest(grant, arguments)
    submission = (
        contest.submissions.select_related("developer").filter(pk=_int(arguments, "submission_id")).first()
    )
    if submission is None:
        raise HttpError(404, "이 공모전에 속한 제출물을 찾을 수 없습니다.")
    return {"contest_id": contest.id, "submission": _submission_view(submission)}


# --- 쓰기 도구 -------------------------------------------------------------------

_CREATE_FIELDS = {"title", "category_id", "deliverable_type_ids", "description", "deadline_at", "requirements", "allows_classroom_import", "require_demo_video", "require_screenshot"}
_UPDATE_FIELDS = {"contest_id", "title", "category_id", "deliverable_type_ids", "description", "deadline_at", "allows_classroom_import", "require_demo_video", "require_screenshot"}


def _create(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _reject_unknown(arguments, _CREATE_FIELDS)
    contest_api.require_contest_product_enabled()
    contest_api._require_hosting_permission(grant.instructor)
    payload = _parse(FreeContestCreateIn, arguments)
    out = contest_api.create_free_contest_draft(grant.instructor, payload)
    contest = Contest.objects.select_related("sponsor").get(pk=out.id)
    return _result(grant, contest, f"초안 만들기: {contest.title}")


def _update(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _reject_unknown(arguments, _UPDATE_FIELDS)
    contest = _contest(grant, arguments, lock=True)
    _require_content_editable(contest)
    payload = _parse(ContestUpdateIn, {k: v for k, v in arguments.items() if k != "contest_id"})
    contest_api.apply_contest_update(contest, payload)
    return _result(grant, contest, f"고치기: {', '.join(sorted(set(arguments) - {'contest_id'}))}")


def _require_content_editable(contest: Contest) -> None:
    if not Contest.Status.CONTENT_EDITABLE(contest.status):
        raise HttpError(409, "마감된 공모전은 더 이상 수정할 수 없습니다.")


def _add_requirement(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _reject_unknown(arguments, {"contest_id", "text", "grade", "points", "hidden"})
    contest = _contest(grant, arguments, lock=True)
    _require_content_editable(contest)
    contest_api.add_contest_requirement(contest, _parse(RequirementCreateIn, {k: v for k, v in arguments.items() if k != "contest_id"}))
    return _result(grant, contest, "요구사항 더하기")


def _update_requirement(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _reject_unknown(arguments, {"contest_id", "requirement_id", "text", "grade", "order", "hidden"})
    contest = _contest(grant, arguments, lock=True)
    _require_content_editable(contest)
    fields = {k: v for k, v in arguments.items() if k not in {"contest_id", "requirement_id"}}
    contest_api.update_contest_requirement(contest, _int(arguments, "requirement_id"), _parse(RequirementUpdateIn, fields))
    return _result(grant, contest, "요구사항 고치기")


def _delete_requirement(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _reject_unknown(arguments, {"contest_id", "requirement_id"})
    contest = _contest(grant, arguments, lock=True)
    _require_content_editable(contest)
    contest_api.delete_contest_requirement(contest, _int(arguments, "requirement_id"))
    return _result(grant, contest, "요구사항 빼기")


def _publish(grant: ConnectedApp, arguments: dict) -> WriteResult:
    _reject_unknown(arguments, {"contest_id"})
    contest = _contest(grant, arguments, lock=True)
    if contest.status != Contest.Status.DRAFT:
        raise HttpError(409, "초안만 공개할 수 있습니다.")
    if contest.archived_at is not None:
        raise HttpError(409, "보관한 공모전은 해제한 뒤에 공개할 수 있습니다.")
    contest_api.publish_free_contest_draft(contest, grant.instructor)
    return _result(grant, contest, f"공개: {contest.title}")


def _two_step(grant: ConnectedApp, tool: str, arguments: dict, preview: dict, act) -> WriteResult | Preview:
    token = presented(arguments)
    if token is None:
        return Preview(structured=needs_confirmation(grant, tool, arguments, preview))
    redeem(grant, tool, arguments, token)
    return act()


def _close_now(grant: ConnectedApp, arguments: dict) -> WriteResult | Preview:
    _reject_unknown(arguments, {"contest_id", CONFIRMATION_ARGUMENT})
    contest = _contest(grant, arguments, lock=True)
    if contest.status != Contest.Status.PUBLISHED:
        raise HttpError(409, "공개 중인 공모전만 마감할 수 있습니다.")

    def act() -> WriteResult:
        now = Clock.now()
        # 마감 스캔(`contest-close`)과 같은 간선·같은 심사 종료 시각 — 마감을 지금으로 당긴 뒤 넘긴다.
        Contest.objects.filter(pk=contest.pk).update(deadline_at=now)
        judging_ends_at = now + timedelta(days=current_policy().judging_period_days)
        if not claim_contest_transition("contest-close", contest.pk, now=now, extra_fields={"judging_ends_at": judging_ends_at}):
            raise HttpError(409, "이미 마감되었거나 마감할 수 없는 상태입니다.")
        return _result(grant, contest, f"지금 마감: {contest.title}")

    preview = {"contest_id": contest.id, "title": contest.title, "submission_count": contest.submissions.count(), "effect": "지금 마감하고 심사 기간을 시작한다. 다시 열 수 없다."}
    return _two_step(grant, "close_free_contest_now", arguments, preview, act)


def _award(grant: ConnectedApp, arguments: dict) -> WriteResult | Preview:
    _reject_unknown(arguments, {"contest_id", "submission_id", CONFIRMATION_ARGUMENT})
    contest = _contest(grant, arguments)
    submission_id = _int(arguments, "submission_id")
    submission = contest.submissions.select_related("developer").filter(pk=submission_id).first()
    if submission is None:
        raise HttpError(404, "이 공모전에 속한 제출물을 찾을 수 없습니다.")

    def act() -> WriteResult:
        contest_api_award(contest, submission_id)
        return _result(grant, contest, f"수상작 선정: 제출 {submission_id}")

    preview = {"contest_id": contest.id, "submission": _submission_view(submission), "effect": "이 제출물을 수상작으로 고르고 참가자에게 결과를 알린다. 되돌릴 수 없다."}
    return _two_step(grant, "award_submission", arguments, preview, act)


def contest_api_award(contest: Contest, submission_id: int) -> None:
    from awards.api import award_contest_submission  # 공모전 가족 — awards 는 contests 를 쓴다.

    award_contest_submission(contest, submission_id)


def _archive(grant: ConnectedApp, arguments: dict) -> WriteResult | Preview:
    _reject_unknown(arguments, {"contest_id", CONFIRMATION_ARGUMENT})
    contest = _contest(grant, arguments, lock=True)
    refusal = archive_refusal(contest)
    if refusal is not None:
        raise HttpError(409, refusal)
    preview = {"contest_id": contest.id, "title": contest.title, "status": contest.status, "effect": "공개 목록·상세·검색·강의실 들여오기에서 숨긴다. 지우지 않고, 해제하면 돌아온다."}
    return _two_step(grant, "archive_free_contest", arguments, preview, lambda: (archive_contest(contest), _result(grant, contest, f"보관: {contest.title}"))[1])


def _unarchive(grant: ConnectedApp, arguments: dict) -> WriteResult | Preview:
    _reject_unknown(arguments, {"contest_id", CONFIRMATION_ARGUMENT})
    contest = _contest(grant, arguments, lock=True)
    if contest.archived_at is None:
        raise HttpError(409, "보관하지 않은 공모전입니다.")
    preview = {"contest_id": contest.id, "title": contest.title, "status": contest.status, "effect": "보관을 풀어 다시 공개 목록에 보인다(공개 상태일 때)."}
    return _two_step(grant, "unarchive_free_contest", arguments, preview, lambda: (unarchive_contest(contest), _result(grant, contest, f"보관 해제: {contest.title}"))[1])


# --- 등록부 ---------------------------------------------------------------------

_ID = {"type": "integer", "minimum": 1}
_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer", "minimum": 0}
#: 배점 1~10(#904) — 없으면 등급별 기본값(필수 2·선택 1). 완성도에만 쓴다.
_POINTS = {"type": "integer", "minimum": 1, "maximum": 10}

_REQUIREMENT = {
    "type": "object",
    "properties": {"id": _ID, "text": _STR, "grade": {"type": "string", "enum": ["required", "optional", "bonus"]}, "points": _INT, "hidden": _BOOL, "order": _INT},
    "required": ["id", "text", "grade", "points", "hidden", "order"],
}
_CONTEST = {
    "type": "object",
    "properties": {
        "id": _ID,
        "title": _STR,
        "status": {"type": "string", "enum": list(Contest.Status.values)},
        "archived": _BOOL,
        "mine": _BOOL,
        "category_id": _ID,
        "deliverable_type_ids": {"type": "array", "items": _ID},
        "require_demo_video": _BOOL,
        "require_screenshot": _BOOL,
        "description": _STR,
        "deadline_at": _STR,
        "judging_ends_at": _STR,
        "allows_classroom_import": _BOOL,
        "submission_count": _INT,
        "requirements": {"type": "array", "items": _REQUIREMENT},
        "hidden_requirement_count": _INT,
    },
    "required": ["id", "title", "status", "archived", "mine", "category_id", "deliverable_type_ids", "require_demo_video", "require_screenshot", "description", "deadline_at", "judging_ends_at", "allows_classroom_import", "submission_count", "requirements", "hidden_requirement_count"],
}
_CONTEST_OUT = {"type": "object", "properties": {"contest": _CONTEST}, "required": ["contest"]}
_PREVIEW_OUT = {
    "type": "object",
    "description": "확인 표 없이 부르면 status=needs_confirmation 과 preview·confirmation 을, 확인 표와 함께 부르면 contest 를 돌려준다.",
}
_SUBMISSION = {
    "type": "object",
    "properties": {"id": _ID, "developer_display_name": _STR, "submitted_at": _STR, "awarded": _BOOL},
    "required": ["id", "developer_display_name", "submitted_at", "awarded"],
}
_CONTEST_ID_INPUT = {"type": "object", "properties": {"contest_id": _ID}, "required": ["contest_id"], "additionalProperties": False}
_CONFIRM_INPUT = {
    "type": "object",
    "properties": {"contest_id": _ID, CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA},
    "required": ["contest_id"],
    "additionalProperties": False,
}
_BRIEF = {
    "title": {"type": "string", "maxLength": 200},
    "category_id": _ID,
    "deliverable_type_ids": {"type": "array", "items": _ID},
    "description": _STR,
    "deadline_at": {"type": "string", "description": "마감 시각(ISO 8601, 시간대 포함). 지금보다 뒤여야 한다."},
    "allows_classroom_import": {"type": "boolean", "description": "강의실 강사가 이 공모전을 클래스로 들여올 수 있게 할지"},
    "require_demo_video": {"type": "boolean", "description": "시연 영상 파일 또는 영상 링크를 제출 필수로 할지"},
    "require_screenshot": {"type": "boolean", "description": "스크린샷을 제출 필수로 할지"},
}


def _write(name: str, title: str, description: str, input_schema: dict, handler, *, output=_CONTEST_OUT, destructive: bool = False) -> Tool:
    return Tool(name=name, title=title, description=description, input_schema=input_schema, output_schema=output, read_only=False, handler=handler, destructive=destructive)


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            name="list_free_contests",
            title="무료 공모전 목록",
            description="내가 다룰 수 있는 무료 공모전을 최근에 만든 순서로 돌려준다(운영자는 전부). 상태로 거르고, 보관한 것은 기본으로 뺀다.",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(Contest.Status.values)},
                    "archived": {"type": "string", "enum": list(_ARCHIVED_FILTER), "description": "exclude(기본)·only·include"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "contests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": _ID, "title": _STR, "status": _STR, "archived": _BOOL, "mine": _BOOL, "deadline_at": _STR, "submission_count": _INT},
                            "required": ["id", "title", "status", "archived", "mine", "deadline_at", "submission_count"],
                        },
                    }
                },
                "required": ["contests"],
            },
            read_only=True,
            handler=_list,
        ),
        Tool(name="get_free_contest", title="무료 공모전 상세", description="공모전 하나의 내용·요구사항·제출 수를 돌려준다.", input_schema=_CONTEST_ID_INPUT, output_schema=_CONTEST_OUT, read_only=True, handler=_get),
        Tool(
            name="list_contest_options",
            title="카테고리·산출물 종류",
            description="공모전을 만들 때 고를 수 있는 카테고리와 산출물 종류의 번호와 이름.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "categories": {"type": "array", "items": {"type": "object", "properties": {"id": _ID, "name": _STR}, "required": ["id", "name"]}},
                    "deliverable_types": {"type": "array", "items": {"type": "object", "properties": {"id": _ID, "name": _STR}, "required": ["id", "name"]}},
                },
                "required": ["categories", "deliverable_types"],
            },
            read_only=True,
            handler=_options,
        ),
        Tool(
            name="list_submissions",
            title="제출물 목록",
            description="공모전의 제출물을 낸 순서로 — 참가자 표시 이름·낸 시각·수상 여부만 담는다.",
            input_schema=_CONTEST_ID_INPUT,
            output_schema={"type": "object", "properties": {"contest_id": _ID, "submissions": {"type": "array", "items": _SUBMISSION}}, "required": ["contest_id", "submissions"]},
            read_only=True,
            handler=_list_submissions,
        ),
        Tool(
            name="get_submission",
            title="제출물 하나",
            description="제출물 하나의 표시 이름·낸 시각·수상 여부.",
            input_schema={"type": "object", "properties": {"contest_id": _ID, "submission_id": _ID}, "required": ["contest_id", "submission_id"], "additionalProperties": False},
            output_schema={"type": "object", "properties": {"contest_id": _ID, "submission": _SUBMISSION}, "required": ["contest_id", "submission"]},
            read_only=True,
            handler=_get_submission,
        ),
        _write(
            "create_free_contest",
            "무료 공모전 초안 만들기",
            "내 명의로 무료 공모전 초안을 만든다. 상금은 없다. 요구사항은 여기서 함께 넣거나 나중에 더한다.",
            {
                "type": "object",
                "properties": {
                    **_BRIEF,
                    "requirements": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"text": {"type": "string", "maxLength": 500}, "grade": {"type": "string", "enum": ["required", "optional", "bonus"]}, "points": _POINTS, "hidden": _BOOL}, "required": ["text", "grade"]},
                    },
                },
                "required": ["title", "category_id", "deliverable_type_ids", "deadline_at"],
                "additionalProperties": False,
            },
            _create,
        ),
        _write(
            "update_free_contest",
            "무료 공모전 고치기",
            "초안이나 공개 중(마감 전)인 공모전의 제목·설명·카테고리·산출물·마감·들여오기 허용을 고친다. 준 칸만 바뀐다. 마감 뒤에는 거절된다.",
            {"type": "object", "properties": {"contest_id": _ID, **_BRIEF}, "required": ["contest_id"], "additionalProperties": False},
            _update,
        ),
        _write(
            "add_requirement",
            "요구사항 더하기",
            "요구사항 하나를 끝에 더한다. 마감 전까지만.",
            {"type": "object", "properties": {"contest_id": _ID, "text": {"type": "string", "maxLength": 500}, "grade": {"type": "string", "enum": ["required", "optional", "bonus"]}, "points": _POINTS, "hidden": _BOOL}, "required": ["contest_id", "text", "grade"], "additionalProperties": False},
            _add_requirement,
        ),
        _write(
            "update_requirement",
            "요구사항 고치기",
            "요구사항 하나의 문장·등급·순서를 고친다. 마감 전까지만.",
            {"type": "object", "properties": {"contest_id": _ID, "requirement_id": _ID, "text": {"type": "string", "maxLength": 500}, "grade": {"type": "string", "enum": ["required", "optional", "bonus"]}, "order": _INT, "hidden": _BOOL}, "required": ["contest_id", "requirement_id"], "additionalProperties": False},
            _update_requirement,
        ),
        _write(
            "delete_requirement",
            "요구사항 빼기",
            "요구사항 하나를 뺀다. 마감 전까지만.",
            {"type": "object", "properties": {"contest_id": _ID, "requirement_id": _ID}, "required": ["contest_id", "requirement_id"], "additionalProperties": False},
            _delete_requirement,
        ),
        _write("publish_free_contest", "무료 공모전 공개", "초안을 공개해 제출을 받기 시작한다. 요구사항이 하나 이상 있어야 하고, 개최자 표시 이름이 있어야 한다.", _CONTEST_ID_INPUT, _publish),
        _write("close_free_contest_now", "지금 마감", "공개 중인 공모전을 지금 마감하고 심사 기간을 시작한다. 두 단계.", _CONFIRM_INPUT, _close_now, output=_PREVIEW_OUT, destructive=True),
        _write(
            "award_submission",
            "수상작 선정",
            "마감 뒤 심사 기간 안에 제출물 하나를 수상작으로 고르고 결과를 알린다. 두 단계.",
            {"type": "object", "properties": {"contest_id": _ID, "submission_id": _ID, CONFIRMATION_ARGUMENT: CONFIRMATION_SCHEMA}, "required": ["contest_id", "submission_id"], "additionalProperties": False},
            _award,
            output=_PREVIEW_OUT,
            destructive=True,
        ),
        _write("archive_free_contest", "보관", "초안·끝난 공모전·제출이 없는 공개 공모전을 보관해 공개 목록에서 숨긴다. 지우지 않는다. 두 단계.", _CONFIRM_INPUT, _archive, output=_PREVIEW_OUT, destructive=True),
        _write("unarchive_free_contest", "보관 해제", "보관한 공모전을 되돌린다. 두 단계.", _CONFIRM_INPUT, _unarchive, output=_PREVIEW_OUT, destructive=True),
    ]
}


def _record(grant: ConnectedApp, tool: str, outcome: WriteResult) -> None:
    summary = outcome.summary[:300]
    ContestConnectedAppWrite.objects.create(
        user_id=grant.instructor_id,
        connected_app=grant,
        tool=tool,
        target_contest_id=getattr(outcome, "contest_id", None),
        summary=summary,
        created_at=Clock.now(),
    )


SERVER = McpServer(
    resource=CONTESTS,
    server_name=SERVER_NAME,
    server_title="Codemit 공모전",
    instructions=INSTRUCTIONS,
    tools=TOOLS,
    record_write=_record,
    calls_per_minute_setting="CONTESTS_MCP_CALLS_PER_MINUTE",
    rate_key_prefix="contest-mcp-calls",
    admit=admission_refusal,
)

mcp_endpoint = SERVER.endpoint()

