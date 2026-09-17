"""Classroom API (#278/#279/#280/#282/#283/#286, ADR-0037).

**Class·Problem·체크리스트 엔드포인트는 여전히 강사 전용이다.** `.../mine`과
`.../submissions`(#286)만 예외다 — 참여자가 가입 링크로 들어와 열린 문제를
보고 소스·저장소를 낸다. 강사가 아닌 요청은 그 강사 전용 엔드포인트에서는
여전히 클래스가 아예 없는 것처럼 404를 받는다.

**`/join/{join_code}` 둘만 예외다.** 미리보기(GET)는 누구나 인증 없이 보고,
가입(POST)은 로그인만 되어 있으면 강사 전용 규칙과 무관하게 누구든(강사
본인 포함) 참여자가 된다 — 가입 링크가 하는 일 자체가 그 규칙 밖의 문이기
때문이다.

**라우트 등록 순서에 규칙이 있다.** 정적 세그먼트(`reorder`)를 가진 라우트는
전부 그 바로 위 동적 세그먼트(`{problem_id}`·`{item_id}`) 라우트보다 먼저
등록한다 — 나중이면 django-ninja가 정적 세그먼트를 동적 파라미터 값으로 먼저
매치해 405가 난다.
"""

from __future__ import annotations

import asyncio
import json
import logging

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, StreamingHttpResponse
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import SocialAccount
from core.crypto import encrypt
from core.events import Event, get_event_bus
from core.llm_scoring import LLMKeyCheckStatus
from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename, safe_download_base_name
from submissions.models import GITHUB_REPO_URL_PATTERN, Submission, SubmissionAsset

from .models import (
    ChecklistItem,
    Class,
    ClassMember,
    ClassroomScore,
    ClassroomSubmission,
    ClassTemplate,
    Problem,
    ProblemTemplate,
    _generate_join_code,
)
from .schemas import (
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemPatchIn,
    ChecklistReorderIn,
    ClassIn,
    ClassOut,
    ClassPatchIn,
    ClassroomChecklistVerdictOut,
    ClassroomGridCellOut,
    ClassroomGridMemberOut,
    ClassroomInstructorSubmissionOut,
    ClassroomMyProblemsOut,
    ClassroomProblemListItemOut,
    ClassroomProblemMineOut,
    ClassroomProblemStatsOut,
    ClassroomProblemSubmissionsOut,
    ClassroomRosterGridOut,
    ClassroomScoreOut,
    ClassroomSubmissionIn,
    ClassroomSubmissionOut,
    ClassroomSyntaxCheckFindingOut,
    ClassroomSyntaxCheckOut,
    ErrorOut,
    ImportableProblemOut,
    JoinedClassOut,
    JoinIn,
    JoinLinkOut,
    JoinPreviewOut,
    JoinResultOut,
    MemberOut,
    MemberRenameIn,
    MemberRenameOut,
    OpenAIKeyIn,
    ProblemCopyIn,
    ProblemIn,
    ProblemOut,
    ProblemPatchIn,
    ProblemReorderIn,
    ProblemTemplateChecklistItemOut,
    ProblemTransitionOut,
    PublishedTemplateSummaryOut,
    ScoringModelCatalogOut,
    ScoringModelOut,
)
from . import pending_scoring
from .events import publish_attempt_submitted
from .participation import (
    SUBMIT_BLOCKED_ARCHIVED,
    SUBMIT_BLOCKED_EXPELLED,
    SUBMIT_BLOCKED_HIDDEN,
    SUBMIT_BLOCKED_VIEWING_AS_INSTRUCTOR,
    assert_class_mutable,
    participant_membership_blocked_reason,
    participant_submit_blocked_reason,
    visible_problems_queryset,
)
from .problem_transitions import (
    assert_has_required_item,
    assert_required_item_floor,
    assert_transition_from_state,
    available_transitions,
)
from .scoring import check_scoring_key
from .scoring_model_catalog import get_scoring_model_catalog
from .scoring_models import is_fallback_model, is_reasoning_model_id, is_valid_reasoning_effort
from .submission_target_refs import source_target_ref
from .services import copy_class, copy_problem_to_class
from .tasks import score_attempt

logger = logging.getLogger(__name__)

router = Router(tags=["classroom"])

_SUBMISSION_FORMATS = {choice for choice, _label in Problem.SubmissionFormat.choices}
#: 화면에 늘 같은 순서로 보이도록(체크박스 둘의 고정 순서), 저장 전에 이
#: 순서로 정렬해 중복을 제거한다 — 입력 순서를 그대로 믿지 않는다.
_SUBMISSION_FORMAT_ORDER = [choice for choice, _label in Problem.SubmissionFormat.choices]


def _normalize_submission_formats(values: list[str]) -> list[str]:
    unique = set(values)
    return [f for f in _SUBMISSION_FORMAT_ORDER if f in unique]


def _validate_submission_formats(values: list[str]) -> list[str]:
    """빈 목록·모르는 값을 422로 거절한다(#373 AC) — 만들기·편집 두 자리가
    같은 규칙을 쓴다."""

    if not values:
        raise HttpError(422, "제출 형식을 하나 이상 골라주세요.")
    unknown = [v for v in values if v not in _SUBMISSION_FORMATS]
    if unknown:
        raise HttpError(422, f"알 수 없는 제출 형식입니다: {unknown[0]}")
    return _normalize_submission_formats(values)


_GRADING_STRICTNESS_VALUES = {choice for choice, _label in Problem.GradingStrictness.choices}


def _validate_grading_guideline(strictness: str, text: str) -> tuple[str, str]:
    """채점 지침 두 칸을 검증하고 저장할 모양으로 정규화한다(#386 AC) —
    만들기·편집 두 자리가 같은 규칙을 쓴다(`_validate_submission_formats`와
    같은 관용구). 알 수 없는 단계와 빈 직접 입력 문장은 422다. 직접 입력이
    아니면 문장을 언제나 빈 문자열로 되돌린다 — "문장은 직접 입력일 때만
    비어 있지 않다"(#385 Implementation Decisions)를 저장 시점에 구조로
    지킨다."""

    if strictness not in _GRADING_STRICTNESS_VALUES:
        raise HttpError(422, f"알 수 없는 채점 지침입니다: {strictness}")
    if strictness == Problem.GradingStrictness.CUSTOM:
        if not text.strip():
            raise HttpError(422, "직접 입력 채점 지침은 문장을 비울 수 없습니다.")
        return strictness, text
    return strictness, ""


def _validate_scoring_model_choice(class_obj: Class, model_id: str, *, current_value: str) -> None:
    """저장 시점에 이 모델이 그 클래스의 키로 실제로 쓸 수 있는지 검증한다
    (#401 AC). 클래스 기본값·문제별 값 둘 다 이 함수 하나를 쓴다 — 두
    자리가 갈리면 클래스에서는 통과한 값이 문제에서는 거절되는(또는 그
    반대) 상태가 생긴다.

    조회가 되면(`source == "live"`) 그 결과에 있어야만 받는다 — 이미 같은
    값을 쓰고 있어도 예외를 두지 않는다(그 사이 키의 권한이 좁혀졌을 수
    있다). 조회가 불가하면(`source == "fallback"`, 키 없음·거부·조회 실패)
    기본 목록 안의 값이거나 지금 저장된 값과 같을 때만 받는다 — 오타는
    막되, 멀쩡히 쓰던 값이 벤더 장애 한 번에 막히지 않는다(#401
    Implementation Decisions)."""

    catalog = get_scoring_model_catalog(class_obj)
    if catalog.source == "live":
        if any(choice.id == model_id for choice in catalog.models):
            return
        raise HttpError(422, f"이 키로 쓸 수 없는 채점 모델입니다: {model_id}")

    if model_id == current_value or is_fallback_model(model_id):
        return
    raise HttpError(
        422,
        f"지금은 모델 목록을 확인할 수 없어 기본 목록의 모델이나 지금 쓰는 모델만 "
        f"저장할 수 있습니다: {model_id}",
    )


def _validate_reasoning_effort(value: str) -> None:
    if not is_valid_reasoning_effort(value):
        raise HttpError(422, f"알 수 없는 추론 강도입니다: {value}")


#: 마스킹은 복호화가 아니라 저장 시점에 남긴 마지막 네 자리로만 만든다 —
#: `Class.openai_api_key_encrypted`를 다시 풀지 않는다(#284, 파일 상단 라우터
#: docstring과 같은 이유: 복호화는 채점 요청을 보낼 때만 한다).
_KEY_MASK_PREFIX = "••••••••"


def _mask_from_last4(last4: str) -> str:
    return f"{_KEY_MASK_PREFIX}{last4}"


def _published_template_summary(template) -> PublishedTemplateSummaryOut | None:
    if template is None:
        return None
    return PublishedTemplateSummaryOut(
        share_code=template.share_code,
        publisher_display_name=template.publisher_display_name,
        created_at=template.created_at,
    )


def _live_class_template(class_obj: Class) -> ClassTemplate | None:
    return class_obj.templates.filter(taken_down_at__isnull=True).first()


def _live_problem_template(problem: Problem) -> ProblemTemplate | None:
    return problem.templates.filter(taken_down_at__isnull=True).first()


def _serialize_class(class_obj: Class) -> ClassOut:
    has_key = class_obj.has_scoring_key()
    token_budget_remaining = (
        max(class_obj.token_budget - class_obj.token_usage_total, 0)
        if class_obj.token_budget is not None
        else None
    )
    return ClassOut(
        id=class_obj.id,
        name=class_obj.name,
        instructor_display_name=class_obj.instructor_display_name,
        join_code=class_obj.join_code,
        created_at=class_obj.created_at,
        default_model=class_obj.default_model,
        default_model_is_reasoning=is_reasoning_model_id(class_obj.default_model),
        default_reasoning_effort=class_obj.default_reasoning_effort,
        has_openai_key=has_key,
        openai_key_masked=_mask_from_last4(class_obj.openai_api_key_last4) if has_key else None,
        openai_key_status=class_obj.openai_api_key_status if has_key else None,
        archived=class_obj.archived_at is not None,
        token_budget=class_obj.token_budget,
        token_budget_warning_threshold_percent=class_obj.token_budget_warning_threshold_percent,
        token_usage_total=class_obj.token_usage_total,
        token_budget_remaining=token_budget_remaining,
        token_budget_exhausted=class_obj.token_budget_exhausted(),
        has_submissions=ClassroomSubmission.objects.filter(problem__classroom=class_obj).exists(),
        published_template=_published_template_summary(_live_class_template(class_obj)),
    )


def _serialize_checklist_item(item: ChecklistItem) -> ChecklistItemOut:
    return ChecklistItemOut(id=item.id, label=item.label, required=item.required, order=item.order)


def _active_member_ids(class_obj: Class) -> set[int]:
    """달성률의 분모를 이루는 참여자 id — 강사 본인과 내보내진 사람은 뺀다
    (#289, CONTEXT.md 「달성률」)."""

    return set(
        class_obj.members.filter(expelled_at__isnull=True)
        .exclude(user_id=class_obj.instructor_id)
        .values_list("id", flat=True)
    )


def _problem_pass_stats(problem: Problem, active_member_ids: set[int]) -> tuple[int, int]:
    """(passed_count, member_count) — 분모는 `active_member_ids`의 크기,
    분자는 그중 이 문제를 한 번이라도 통과한 사람 수다(#289). 매번 지금의
    체크리스트 기준으로 다시 셈한다 — `Problem.is_score_passed`(#436)가
    그렇게 되어 있어 여기서는 한 번 불러온 체크리스트만 그대로 넘기면
    된다."""

    member_count = len(active_member_ids)
    if not active_member_ids:
        return 0, 0

    checklist_items = list(problem.checklist_items.all())
    if not any(item.required for item in checklist_items):
        return 0, member_count

    submissions = ClassroomSubmission.objects.filter(
        problem=problem, member_id__in=active_member_ids
    ).select_related("classroom_score")

    passed_member_ids: set[int] = set()
    for submission in submissions:
        if submission.member_id in passed_member_ids:
            continue
        score = getattr(submission, "classroom_score", None)
        if problem.is_score_passed(score, checklist_items=checklist_items):
            passed_member_ids.add(submission.member_id)

    return len(passed_member_ids), member_count


def _problem_ids_blocking_deletion(class_obj: Class) -> set[int]:
    """강사 자신이 아닌 누군가의 시도가 하나라도 달린 문제 id 집합(#431,
    ADR-0050) — **내보낸 참여자의 시도도 포함한다**(`member__expelled_at`을
    보지 않는다, ADR-0050의 경계: 내보내면 지울 수 있게 되는 우회를 막는다).
    목록 화면(`list_problems`/`reorder_problems`)이 문제마다 따로 질의하지
    않도록 클래스 전체를 한 번에 묻는다 — `_active_member_ids`와 같은 배치
    관용구다."""

    return set(
        ClassroomSubmission.objects.filter(problem__classroom=class_obj)
        .exclude(member__user_id=class_obj.instructor_id)
        .values_list("problem_id", flat=True)
    )


def _problem_deletable(
    problem: Problem, class_obj: Class, *, blocking_problem_ids: set[int] | None = None
) -> bool:
    """이 문제를 지금 지울 수 있는가(#430/#431, ADR-0050) — 강사 자신이 아닌
    누군가의 시도가 하나도 없을 때 참이다.

    강사 판정은 `member__user_id == class_obj.instructor_id`로 한다 — 「그
    시도가 어느 멤버십의 것인가」가 아니라 「그 시도를 낸 사람이 강사
    자신인가」로 좁게 본다(#431 Further Notes가 정한 더 좁은 쪽). 두 판정은
    `unique_classroom_member` 제약(클래스 하나에 유저 하나당 멤버십 하나) 아래
    에서 같은 답을 내지만, 달성률 분모(`_active_member_ids`)와는 **의도적으로
    필터를 공유하지 않는다** — 그쪽은 내보낸 사람을 빼고 「지금 배우는 사람이
    몇인가」를 세고, 이쪽은 내보낸 사람도 포함해 「지워도 되는 기록인가」를
    묻는다. 같은 필터를 썼다면 내보낸 참여자의 시도가 조용히 안 걸렸을
    것이다."""

    if blocking_problem_ids is not None:
        return problem.id not in blocking_problem_ids
    return not (
        ClassroomSubmission.objects.filter(problem=problem)
        .exclude(member__user_id=class_obj.instructor_id)
        .exists()
    )


def _serialize_problem(
    problem: Problem,
    class_obj: Class,
    *,
    active_member_ids: set[int] | None = None,
    blocking_problem_ids: set[int] | None = None,
) -> ProblemOut:
    if active_member_ids is None:
        active_member_ids = _active_member_ids(class_obj)
    passed_count, member_count = _problem_pass_stats(problem, active_member_ids)
    effective_model = problem.effective_model()
    effective_reasoning_effort = problem.effective_reasoning_effort()
    return ProblemOut(
        id=problem.id,
        classroom_id=problem.classroom_id,
        title=problem.title,
        description=problem.description,
        submission_formats=problem.submission_formats,
        status=problem.status,
        order=problem.order,
        model=problem.model,
        effective_model=effective_model,
        effective_model_is_reasoning=is_reasoning_model_id(effective_model),
        reasoning_effort=problem.reasoning_effort,
        effective_reasoning_effort=effective_reasoning_effort,
        scoring_model_rejected=problem.scoring_model_rejected_at is not None,
        grading_strictness=problem.grading_strictness,
        grading_guideline_text=problem.grading_guideline_text,
        syntax_check_enabled=problem.syntax_check_enabled,
        checklist_items=[_serialize_checklist_item(i) for i in problem.checklist_items.all()],
        passed_count=passed_count,
        member_count=member_count,
        pass_rate=(passed_count / member_count) if member_count else None,
        published_template=_published_template_summary(_live_problem_template(problem)),
        deletable=_problem_deletable(problem, class_obj, blocking_problem_ids=blocking_problem_ids),
        available_transitions=[
            ProblemTransitionOut(name=t.name, to_state=t.to_state, blocked_reason=t.blocked_reason)
            for t in available_transitions(problem, class_obj)
        ],
    )


def _serialize_problem_mine(problem: Problem, *, passed: bool = False) -> ClassroomProblemMineOut:
    return ClassroomProblemMineOut(
        id=problem.id,
        classroom_id=problem.classroom_id,
        title=problem.title,
        description=problem.description,
        submission_formats=problem.submission_formats,
        grading_strictness=problem.grading_strictness,
        grading_guideline_text=problem.grading_guideline_text,
        syntax_check_enabled=problem.syntax_check_enabled,
        checklist_items=[_serialize_checklist_item(i) for i in problem.checklist_items.all()],
        passed=passed,
    )


def _source_download_url(asset: SubmissionAsset, user) -> str:
    """소스 자료 하나의 presigned 다운로드 URL — 파일명은 제출자 본인의 User
    정보를 따른다(#286 AC). 강의실 참여자는 `accounts.DeveloperProfile`이
    없으므로 공모전 제출 화면처럼 `developer.display_name`을 쓸 수 없다 —
    대신 `User.email`을 쓴다(`classroom.api.preview_join`이 강사를 가리킬 때
    이미 같은 값을 쓰고 있다)."""

    adapter = get_storage_adapter()
    base_name = safe_download_base_name(user.email)
    presigned = adapter.presign_download(
        asset.value,
        filename=build_download_filename(asset.content_type or None, base_name=base_name),
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )
    return presigned.url


def _serialize_syntax_check(result: dict | None) -> ClassroomSyntaxCheckOut | None:
    if result is None:
        return None
    return ClassroomSyntaxCheckOut(
        is_met=result["is_met"],
        reasoning=result["reasoning"],
        judged_by=result["judged_by"],
        findings=[
            ClassroomSyntaxCheckFindingOut(path=f["path"], line=f.get("line"), message=f["message"])
            for f in result.get("findings", [])
        ],
    )


def _serialize_score(score: ClassroomScore) -> ClassroomScoreOut:
    return ClassroomScoreOut(
        model_version=score.model_version,
        reasoning=[
            ClassroomChecklistVerdictOut(
                checklist_item_id=r["checklist_item_id"],
                is_met=r["is_met"],
                reasoning=r["reasoning"],
            )
            for r in score.reasoning
        ],
        syntax_check=_serialize_syntax_check(score.syntax_check_result),
        created_at=score.created_at,
    )


def _pending_reason(score, class_obj: Class, problem: Problem) -> str | None:
    """아직 채점되지 않은 시도가 왜 멈춰 있는지(#295, #346, #355, #403, #434) —
    참여자·강사 화면 모두 이 값 하나를 읽어 다르게 그린다.
    `classroom.pending_scoring.pending_reason`에 그대로 맡긴다 — 스캔 후보
    (`scoring.pending_submissions`)가 거르는 것과 **같은 기준**이어야 한다는
    불변식이 이제 그 모듈 하나에 산다. 셋이 겹치면 키(없음·거부) → 모델
    거부 → 예산 소진 순서로 하나만 말한다. **키가 거부된 것과 아예 없는
    것, 그리고 모델이 거부된 것을 참여자 화면에서는 구별하지 않는다**
    (#355 AC, #403 AC "참여자에게는 기존 「채점하지 못함」 안내를 보인다")
    — 강사의 계정·설정 문제가 참여자에게 새어 나가지 않는다, 강사 전용
    화면(설정·시도 목록·클래스 상세 배너)만 다르게 말한다."""

    return pending_scoring.pending_reason(score, class_obj, problem)


def _serialize_classroom_submission(
    submission: ClassroomSubmission,
    *,
    asset: SubmissionAsset,
    user,
    class_obj: Class,
    problem: Problem,
    checklist_items=None,
) -> ClassroomSubmissionOut:
    download_url = (
        _source_download_url(asset, user) if asset.kind == SubmissionAsset.Kind.SOURCE else None
    )
    score = getattr(submission, "classroom_score", None)
    pending_reason = _pending_reason(score, class_obj, problem)
    return ClassroomSubmissionOut(
        id=submission.id,
        problem_id=submission.problem_id,
        attempt_number=submission.attempt_number,
        submission_format=asset.kind,
        value=asset.value,
        download_url=download_url,
        created_at=submission.created_at,
        status="scored" if score is not None else "pending",
        score=_serialize_score(score) if score is not None else None,
        passed=problem.is_score_passed(score, checklist_items=checklist_items),
        pending_reason=pending_reason,
    )


def _instructor_source_download_url(
    asset: SubmissionAsset, *, member: ClassMember, attempt_number: int
) -> str:
    """강사가 소스를 내려받을 때의 presigned URL(#291) — 참여자 본인용
    `_source_download_url`과 달리 파일명이 `User.email`이 아니라 **그 클래스에서
    불릴 이름 + 시도 번호**로 조립된다. 강사 한 사람이 참여자 여러 명의, 그리고
    한 참여자의 여러 시도를 잇달아 내려받으므로 이메일 하나로는(같은 참여자의
    다른 시도끼리) 구별되지 않는다."""

    adapter = get_storage_adapter()
    base_name = safe_download_base_name(f"{member.display_name}-{attempt_number}")
    presigned = adapter.presign_download(
        asset.value,
        filename=build_download_filename(asset.content_type or None, base_name=base_name),
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )
    return presigned.url


def _serialize_instructor_submission(
    submission: ClassroomSubmission,
    *,
    asset: SubmissionAsset,
    class_obj: Class,
    problem: Problem,
    checklist_items=None,
) -> ClassroomInstructorSubmissionOut:
    download_url = (
        _instructor_source_download_url(
            asset, member=submission.member, attempt_number=submission.attempt_number
        )
        if asset.kind == SubmissionAsset.Kind.SOURCE
        else None
    )
    score = getattr(submission, "classroom_score", None)
    return ClassroomInstructorSubmissionOut(
        id=submission.id,
        problem_id=submission.problem_id,
        member_id=submission.member_id,
        member_display_name=submission.member.display_name,
        attempt_number=submission.attempt_number,
        submission_format=asset.kind,
        value=asset.value,
        download_url=download_url,
        created_at=submission.created_at,
        status="scored" if score is not None else "pending",
        score=_serialize_score(score) if score is not None else None,
        passed=problem.is_score_passed(score, checklist_items=checklist_items),
        pending_reason=_pending_reason(score, class_obj, problem),
    )


def _get_owned_class_or_404(class_id: int, user_id: int) -> Class:
    """강사 본인의 클래스만 돌려준다. 남의 것은 「없다」로 답한다 — 목록에도
    상세에도 나오지 않아야 한다는 AC(#278)를 403이 아니라 404로 지킨다."""

    try:
        return Class.objects.get(id=class_id, instructor_id=user_id)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "클래스를 찾을 수 없습니다.") from exc


def _get_owned_problem_or_404(classroom_obj: Class, problem_id: int) -> Problem:
    try:
        return classroom_obj.problems.get(id=problem_id)
    except Problem.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


# --- Class -------------------------------------------------------------------


@router.post("/classes", response={201: ClassOut}, auth=jwt_auth)
def create_class(request: HttpRequest, payload: ClassIn):
    class_obj = Class.objects.create(
        instructor_id=request.auth_user.id,
        name=payload.name,
        instructor_display_name=payload.instructor_display_name,
    )
    return 201, _serialize_class(class_obj)


@router.get("/classes", response={200: list[ClassOut]}, auth=jwt_auth)
def list_my_classes(request: HttpRequest):
    """「내 클래스」— 본인이 강사인 것만. 남의 클래스는 여기 나오지 않는다."""

    classes = Class.objects.filter(instructor_id=request.auth_user.id)
    return 200, [_serialize_class(c) for c in classes]


@router.get("/classes/joined", response={200: list[JoinedClassOut]}, auth=jwt_auth)
def list_joined_classes(request: HttpRequest):
    """「내 클래스」— 본인이 참여자로 들어간 것만(#328). 본인이 강사인
    클래스는 강사 본인도 `ClassMember` 행을 가질 수 있지만(models.py
    `ClassMember` docstring) 여기서는 뺀다 — 그 클래스는 이미
    `list_my_classes`가 「연 것」으로 보여주므로, 여기까지 포함하면 첫
    화면에 같은 클래스가 두 자리에 겹쳐 나온다."""

    memberships = (
        ClassMember.objects.filter(user_id=request.auth_user.id)
        .exclude(classroom__instructor_id=request.auth_user.id)
        .select_related("classroom")
        .order_by("-joined_at")
    )
    return 200, [
        JoinedClassOut(
            id=m.classroom.id,
            name=m.classroom.name,
            instructor_display_name=m.classroom.instructor_display_name,
            joined_at=m.joined_at,
            archived=m.classroom.archived_at is not None,
            expelled=m.expelled_at is not None,
        )
        for m in memberships
    ]


@router.get("/classes/{class_id}", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def get_class(request: HttpRequest, class_id: int):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    return 200, _serialize_class(class_obj)


@router.patch(
    "/classes/{class_id}", response={200: ClassOut, 404: ErrorOut, 422: ErrorOut}, auth=jwt_auth
)
def update_class(request: HttpRequest, class_id: int, payload: ClassPatchIn):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)

    if payload.default_model is not None:
        _validate_scoring_model_choice(
            class_obj, payload.default_model, current_value=class_obj.default_model
        )
    if payload.default_reasoning_effort is not None:
        _validate_reasoning_effort(payload.default_reasoning_effort)

    update_fields = []
    if payload.name is not None:
        class_obj.name = payload.name
        update_fields.append("name")
    if payload.instructor_display_name is not None:
        class_obj.instructor_display_name = payload.instructor_display_name
        update_fields.append("instructor_display_name")
    if payload.default_model is not None and payload.default_model != class_obj.default_model:
        class_obj.default_model = payload.default_model
        update_fields.append("default_model")
        # 클래스 기본값을 물려받던 문제(자기 모델을 명시하지 않은 것)들은
        # 새 모델로 다시 시도할 자격을 얻는다(#403 AC "모델을 바꾼 뒤 새
        # 시도는 새 모델로 채점된다") — 이전 모델이 거부됐던 것이든 아니든,
        # 값이 실제로 바뀌었으면 그 문제들의 "거부됨" 표시는 더 이상 지금
        # 값을 설명하지 않는다.
        class_obj.problems.filter(model="").update(scoring_model_rejected_at=None)
    if payload.default_reasoning_effort is not None:
        class_obj.default_reasoning_effort = payload.default_reasoning_effort
        update_fields.append("default_reasoning_effort")
    if payload.token_budget is not None and payload.token_budget != class_obj.token_budget:
        class_obj.token_budget = payload.token_budget
        update_fields.append("token_budget")
        if class_obj.token_budget_warning_sent_at is not None:
            # 예산 값을 바꾸는 것을 새 주기의 시작으로 본다(#295) — 그러지
            # 않으면 한 번 경고한 뒤로는 예산을 아무리 늘려도 다시는 경고가
            # 가지 않는다.
            class_obj.token_budget_warning_sent_at = None
            update_fields.append("token_budget_warning_sent_at")
    if payload.token_budget_warning_threshold_percent is not None:
        class_obj.token_budget_warning_threshold_percent = payload.token_budget_warning_threshold_percent
        update_fields.append("token_budget_warning_threshold_percent")
    if update_fields:
        class_obj.save(update_fields=update_fields)
    return 200, _serialize_class(class_obj)


@router.put(
    "/classes/{class_id}/openai-key",
    response={200: ClassOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def set_class_openai_key(request: HttpRequest, class_id: int, payload: OpenAIKeyIn):
    """참여자에게는 어떤 형태로도 보이지 않는다(#284) — 이 엔드포인트도 강사
    본인 전용이다. 응답은 마스킹된 `ClassOut`뿐, 평문은 어디에도 싣지 않는다.

    저장 전에 강의실 채점 어댑터를 통해 이 키를 벤더에게 한 번 확인한다
    (#354, ADR-0045). 벤더가 명시적으로 거부했을 때(401·403)만 저장 자체를
    거절한다 — DB의 기존 키는 그대로 남아 오타 하나가 멀쩡한 옛 키를 밀어내지
    않는다. 벤더에 닿지 못했을 때(타임아웃·5xx·네트워크)는 저장은 성공하되
    상태를 "미검증"으로 남긴다 — 막으려는 것은 오타이지 벤더의 그 순간
    가용성이 아니다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)

    raw_key = payload.api_key.strip()
    if not raw_key:
        raise HttpError(422, "채점 키를 입력해주세요.")

    check_result = check_scoring_key(api_key=raw_key)
    if check_result == LLMKeyCheckStatus.REJECTED:
        raise HttpError(422, "이 채점 키를 벤더가 거절했습니다 — 키를 다시 확인해 저장해주세요.")

    class_obj.openai_api_key_encrypted = encrypt(raw_key)
    class_obj.openai_api_key_last4 = raw_key[-4:]
    class_obj.openai_api_key_status = (
        Class.ScoringKeyStatus.VERIFIED
        if check_result == LLMKeyCheckStatus.VALID
        else Class.ScoringKeyStatus.UNVERIFIED
    )
    class_obj.save(
        update_fields=["openai_api_key_encrypted", "openai_api_key_last4", "openai_api_key_status"]
    )
    return 200, _serialize_class(class_obj)


@router.post("/classes/{class_id}/copy", response={201: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def copy_class_view(request: HttpRequest, class_id: int):
    """지난 기수로 다음 기수를 연다(#293) — 문제·체크리스트·채점 설정이
    순서 그대로 따라오고, 참여자·제출물·Score·OpenAI 키는 따라오지 않는다
    (`services.copy_class` docstring 참고)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    new_class = copy_class(class_obj, request.auth_user.id)
    return 201, _serialize_class(new_class)


@router.get(
    "/classes/{class_id}/scoring-models",
    response={200: ScoringModelCatalogOut, 404: ErrorOut},
    auth=jwt_auth,
)
def list_class_scoring_models(request: HttpRequest, class_id: int):
    """「클래스 설정」과 문제 만들기·편집이 선택지를 채우는 자리(#401) —
    예전 전역 `GET /scoring-models`(#285)를 대신한다: 키가 클래스에 있으므로
    "이 클래스의 키로 실제로 쓸 수 있는 모델"은 클래스 기준으로만 답할 수
    있다. 남의 클래스는 404다(`_get_owned_class_or_404`와 같은 규율)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    catalog = get_scoring_model_catalog(class_obj)
    return 200, ScoringModelCatalogOut(
        models=[
            ScoringModelOut(
                id=c.id,
                label=c.label,
                context_window=c.context_window,
                is_reasoning_model=c.is_reasoning_model,
            )
            for c in catalog.models
        ],
        source=catalog.source,
        unavailable_reason=catalog.unavailable_reason,
    )


@router.post(
    "/classes/{class_id}/join-link/regenerate",
    response={200: JoinLinkOut, 404: ErrorOut},
    auth=jwt_auth,
)
def regenerate_join_link(request: HttpRequest, class_id: int):
    """가입 링크를 다시 뽑는다(#279). 새 코드로 덮어쓰므로 이전 코드는 그
    순간부터 어떤 클래스도 가리키지 않는다 — 링크가 새어 나갔을 때 강사가
    쓸 수 있는 유일한 조치다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    class_obj.join_code = _generate_join_code()
    class_obj.save(update_fields=["join_code"])
    return 200, JoinLinkOut(join_code=class_obj.join_code)


@router.post("/classes/{class_id}/archive", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def archive_class(request: HttpRequest, class_id: int):
    """수업이 끝나면 보관한다(#294) — 지우지 않는다. 새 가입·새 제출만
    닫히고, 지난 문제·제출물·판정·달성률은 계속 읽힌다(CONTEXT.md
    「Class」). 이미 보관된 클래스를 다시 보관해도 오류를 내지 않는다(멱등,
    `expel_member`와 같은 관용구)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    if class_obj.archived_at is None:
        class_obj.archived_at = timezone.now()
        class_obj.save(update_fields=["archived_at"])
    return 200, _serialize_class(class_obj)


@router.post(
    "/classes/{class_id}/unarchive", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth
)
def unarchive_class(request: HttpRequest, class_id: int):
    """보관을 되돌린다(#294 AC "강사가 클래스를 보관하고 다시 되돌릴 수
    있다") — `archived_at`을 지우면 그대로 진행중이다, 보관 이력을 따로
    남기지 않는다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    if class_obj.archived_at is not None:
        class_obj.archived_at = None
        class_obj.save(update_fields=["archived_at"])
    return 200, _serialize_class(class_obj)


@router.delete(
    "/classes/{class_id}", response={204: None, 403: ErrorOut, 404: ErrorOut}, auth=jwt_auth
)
def delete_class(request: HttpRequest, class_id: int):
    """실수로 만든 클래스를 없던 일로 한다(#330) — 보관과 다르다, 되돌릴 수 없다.

    **제출이 하나라도 있으면 거절한다.** 그 사람이 낸 것과 그 판정은 참여자의
    기록이지 강사가 지울 것이 아니다 — 그때는 보관이 맞는 답이다. 제출이 없으면
    `ClassroomScore`도 없으므로(제출 없이 채점은 없다) `submission`의 PROTECT가
    이 경로에서 막힐 일도 없다.

    문제·체크리스트·참여자 가입은 `Class`에 걸린 CASCADE로 함께 지워진다. 이
    클래스에서 공개한 템플릿(`ProblemTemplate`·`ClassTemplate`)은 `Class`를
    가리키지 않는, 공개 시점에 뜬 사본이라 영향받지 않는다(#316·#319)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    if ClassroomSubmission.objects.filter(problem__classroom=class_obj).exists():
        raise HttpError(403, "제출이 있는 클래스는 지울 수 없습니다. 대신 보관해주세요.")
    class_obj.delete()
    return 204, None


# --- Join (#280) -----------------------------------------------------------------


def _get_class_by_join_code_or_404(join_code: str) -> Class:
    """코드가 없거나(오타) 재발급으로 죽었거나 — 이유를 구별하지 않는다.
    둘 다 "이 링크는 더 이상 쓸 수 없다"로 같게 답하는 것이 곧 #279가 정한
    재발급의 효과다."""

    try:
        return Class.objects.get(join_code=join_code)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "이 가입 링크는 더 이상 사용할 수 없습니다.") from exc


@router.get("/join/{join_code}", response={200: JoinPreviewOut, 404: ErrorOut}, auth=None)
def preview_join(request: HttpRequest, join_code: str):
    """가입 여부와 무관하게 누구나 본다 — 계정이 없는 사람이 가입할지 먼저
    판단할 수 있어야 한다(#280 AC).

    **보관된 클래스도 404로 숨기지 않는다**(#294) — 재발급으로 죽은 코드와
    달리, 보관은 "이 링크가 무효다"가 아니라 "이 수업이 끝났다"이다. 그
    차이가 화면에서 "고장"과 "끝났다"를 가르므로(AC), 미리보기는 그대로
    보여주고 `archived`만 참으로 켠다 — 가입 폼을 접는 판단은 화면의 몫.

    **로그인되어 있으면 이미 참여자인지도 함께 알려준다**(#300) — 이
    엔드포인트는 `auth=None`이라 로그인하지 않은 방문자도 여전히 미리보기를
    보지만, `JWTAuthenticationMiddleware`가 `request.auth_user`는 인증
    요구와 무관하게 항상 채워 둔다(`accounts/middleware.py`) — 그 값이
    있으면 멤버십을 확인할 수 있다. 다시 가입 링크를 연 사람이 이름 입력
    폼을 또 보지 않게 하는 것이 이 신호의 목적이다."""

    class_obj = _get_class_by_join_code_or_404(join_code)
    auth_user = getattr(request, "auth_user", None)
    already_joined = (
        auth_user is not None
        and class_obj.members.filter(user_id=auth_user.id).exists()
    )
    # 제안 이름은 로그인한 사람에게만 싣는다(#390 AC) — 익명 방문자에게는
    # 애초에 누구의 닉네임인지가 없다. 카카오만 닉네임을 채우므로(#189가
    # GitHub·구글을 켤 때까지) 다른 제공자·미동의 사용자는 빈 문자열이 와
    # `suggested_name`도 `None`으로 떨어진다.
    suggested_name = None
    if auth_user is not None:
        social_account = SocialAccount.objects.filter(user_id=auth_user.id).first()
        if social_account is not None and social_account.nickname:
            suggested_name = social_account.nickname
    # `members.count()`는 강사 본인이 가입했으면 그 행도 센다 — CONTEXT.md
    # 「ClassMember」가 강사를 빼라고 정한 것은 **달성률**의 분모뿐이다(그
    # 계산은 아직 없는 티켓의 몫이다). 이 미리보기의 "참여자 수"는 그
    # 지표가 아니라 문자 그대로 "이 클래스에 누가 있는가"라 뺄 이유가
    # 없다.
    return 200, JoinPreviewOut(
        class_id=class_obj.id,
        class_name=class_obj.name,
        instructor_display_name=class_obj.instructor_display_name or None,
        problem_count=class_obj.problems.count(),
        participant_count=class_obj.members.count(),
        archived=class_obj.archived_at is not None,
        already_joined=already_joined,
        suggested_name=suggested_name,
    )


@router.post(
    "/join/{join_code}",
    response={200: JoinResultOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def join_class(request: HttpRequest, join_code: str, payload: JoinIn):
    """가입과 클래스 가입이 한 흐름이다 — 계정이 있으면(로그인 되어 있으면)
    이 요청 하나로 끝난다. 이미 참여자면 새로 만들지 않고 그 행을 그대로
    돌려준다(#280 AC "같은 사람이 같은 클래스에 두 번 들어가지 않는다") —
    두 번째 이름은 버려진다, 첫 가입 때 정한 이름이 그 클래스에서의 정체성이기
    때문이다.

    **보관된 클래스는 새 가입을 받지 않는다**(#294 AC). 미리보기가 이미
    `archived`를 알려 화면이 가입 폼을 접으므로, 여기 닿는 것은 그 안내를
    보고도 보낸 요청뿐이다 — `expel_member`의 403과 같은 이유로, 이미 아는
    사실을 403으로 정직하게 답한다."""

    class_obj = _get_class_by_join_code_or_404(join_code)
    if class_obj.archived_at is not None:
        raise HttpError(403, "이 클래스는 보관되어 더 이상 가입할 수 없습니다.")
    member, _created = ClassMember.objects.get_or_create(
        classroom=class_obj,
        user_id=request.auth_user.id,
        defaults={"display_name": payload.display_name},
    )
    return 200, JoinResultOut(
        class_id=class_obj.id, class_name=class_obj.name, display_name=member.display_name
    )


# --- Member (#281) ---------------------------------------------------------------


def _serialize_member(member: ClassMember, *, instructor_id: int) -> MemberOut:
    return MemberOut(
        id=member.id,
        display_name=member.display_name,
        joined_at=member.joined_at,
        expelled=member.expelled_at is not None,
        is_instructor=member.user_id == instructor_id,
    )


@router.get(
    "/classes/{class_id}/members", response={200: list[MemberOut], 404: ErrorOut}, auth=jwt_auth
)
def list_members(request: HttpRequest, class_id: int):
    """강사만 본다 — 참여자는 자기 클래스든 남의 클래스든 명단에 닿지
    못한다(#281 AC "참여자는 남의 명단을 볼 수 없다"), `_get_owned_class_or_404`가
    강사가 아닌 모든 요청을 404로 돌리는 것과 같은 문이다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    members = class_obj.members.all()
    return 200, [_serialize_member(m, instructor_id=class_obj.instructor_id) for m in members]


@router.post(
    "/classes/{class_id}/members/{member_id}/expel",
    response={200: MemberOut, 404: ErrorOut},
    auth=jwt_auth,
)
def expel_member(request: HttpRequest, class_id: int, member_id: int):
    """행을 지우지 않는다 — 표시만 한다(#281). 이미 내보낸 사람을 다시
    내보내도 오류를 내지 않고 그대로 둔다(멱등)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    try:
        member = class_obj.members.get(id=member_id)
    except ClassMember.DoesNotExist as exc:
        raise HttpError(404, "참여자를 찾을 수 없습니다.") from exc

    if member.expelled_at is None:
        member.expelled_at = timezone.now()
        member.save(update_fields=["expelled_at"])

    return 200, _serialize_member(member, instructor_id=class_obj.instructor_id)


@router.patch(
    "/classes/{class_id}/members/me",
    response={200: MemberRenameOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def rename_myself(request: HttpRequest, class_id: int, payload: MemberRenameIn):
    """참여자 본인이 그 클래스에서 불릴 이름을 스스로 바꾼다(#372, CONTEXT.md
    「ClassMember」) — 강사는 참여자의 이름을 바꿀 길이 없다: 이 엔드포인트는
    요청자 자신의 행만 찾는다(`_get_member_or_404`, 참여자 제출과 같은
    존재-숨김 규칙이라 강사 본인도 이 클래스의 참여자가 아니면 404다).
    제출물·명단은 이 행을 그대로 가리키므로 비정규화 없이 새 이름이 즉시
    따라간다.

    내보내진 참여자와 보관된 클래스는 `create_classroom_submission`과 같은
    이유로 403이다 — 화면이 이미 그 사실을 알려준 뒤라 존재를 숨길 필요가
    없다. 검증 규칙(빈 이름·100자 초과)은 가입 때와 같은
    `ClassMemberDisplayName`을 그대로 쓴다."""

    member = _get_member_or_404(class_id, request.auth_user.id)

    reason = participant_membership_blocked_reason(member.classroom, member)
    if reason == SUBMIT_BLOCKED_ARCHIVED:
        raise HttpError(403, "이 클래스는 보관되어 이름을 바꿀 수 없습니다.")
    if reason == SUBMIT_BLOCKED_EXPELLED:
        raise HttpError(403, "더 이상 이 클래스의 참여자가 아닙니다.")

    member.display_name = payload.display_name
    member.save(update_fields=["display_name"])

    return 200, MemberRenameOut(display_name=member.display_name)


# --- Roster grid (#290) -----------------------------------------------------------


def _cell_status(
    submissions: list[ClassroomSubmission],
    class_obj: Class,
    problem: Problem,
) -> str:
    """이 참여자·이 문제 한 칸의 상태 — **통과 이력**을 그린다(최신 시도가
    아니다, #290 AC). 우선순위는 이 순서다: 한 번이라도 통과했으면 이후
    시도가 미통과여도 "passed"다(#289/#288과 같은 OR 규칙). 통과가 없고
    아직 채점을 기다리는 시도가 있으면, `pending_scoring.needs_setup`이
    참이면 "needs_setup"(#346·#403, 키가 아예 없거나 #355로 거부됐거나
    이 문제의 모델이 거부됐다 — 셋 다 강사 본인이 손대기 전까지는 절대
    안 바뀐다는 것을 하나로 묶어 보여준다, #434 — 이 격자는 강사 전용
    화면이지만 참여자별 칸 하나하나까지 세 사유를 따로 말할 자리는 아니다,
    강사는 클래스 상세 배너·설정 화면·문제별 제출 현황에서 이미 그 사실을
    본다) — 아니면(예산 소진뿐이면) "scoring"(예산을 채우면 저절로 풀려
    아직 뒤집힐 여지가 있다는 뜻이다). 전부 채점됐는데 하나도 통과가 없으면
    "attempted_not_passed". 시도 자체가 없으면 "not_submitted".

    통과 판정은 `Problem.is_score_passed`(#436)에 맡긴다 — 필수 항목·문법
    검사 설정을 이 함수가 다시 받지 않는다. `problem.checklist_items`가
    이미 `prefetch_related`로 불려 있어(호출부인 `get_roster_grid`) 문제
    수만큼 질의가 늘지 않는다."""

    if not submissions:
        return "not_submitted"
    if any(problem.is_score_passed(getattr(s, "classroom_score", None)) for s in submissions):
        return "passed"
    if any(getattr(s, "classroom_score", None) is None for s in submissions):
        return "needs_setup" if pending_scoring.needs_setup(class_obj, problem) else "scoring"
    return "attempted_not_passed"


@router.get(
    "/classes/{class_id}/roster-grid",
    response={200: ClassroomRosterGridOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_roster_grid(request: HttpRequest, class_id: int):
    """참여자 × 문제 격자(#290) — 「누가 어디서 막혔는지」. 강사 전용이다,
    참여자 명단과 같은 이유로 남의 클래스는 404다. 달성률 행은 `_problem_pass_stats`를
    그대로 재사용해 문제 중심 탭(`list_problems`)과 정확히 같은 값을 낸다(AC) —
    계산을 두 번 쓰지 않는다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problems = list(class_obj.problems.prefetch_related("checklist_items").all())
    members = list(class_obj.members.all())
    active_member_ids = _active_member_ids(class_obj)

    submissions = ClassroomSubmission.objects.filter(
        problem__in=problems, member__in=members
    ).select_related("classroom_score")
    submissions_by_key: dict[tuple[int, int], list[ClassroomSubmission]] = {}
    for submission in submissions:
        submissions_by_key.setdefault((submission.problem_id, submission.member_id), []).append(submission)

    problem_stats = []
    for problem in problems:
        passed_count, member_count = _problem_pass_stats(problem, active_member_ids)
        problem_stats.append(
            ClassroomProblemStatsOut(
                id=problem.id,
                title=problem.title,
                status=problem.status,
                passed_count=passed_count,
                member_count=member_count,
                pass_rate=(passed_count / member_count) if member_count else None,
            )
        )

    member_rows = []
    for member in members:
        cells = [
            ClassroomGridCellOut(
                problem_id=problem.id,
                status=_cell_status(
                    submissions_by_key.get((problem.id, member.id), []),
                    class_obj,
                    problem,
                ),
            )
            for problem in problems
        ]
        member_rows.append(
            ClassroomGridMemberOut(
                id=member.id,
                display_name=member.display_name,
                is_instructor=member.user_id == class_obj.instructor_id,
                expelled=member.expelled_at is not None,
                cells=cells,
            )
        )

    return 200, ClassroomRosterGridOut(problems=problem_stats, members=member_rows)


# --- Problem -------------------------------------------------------------------


@router.post(
    "/classes/{class_id}/problems",
    response={201: ProblemOut, 404: ErrorOut, 400: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def create_problem(request: HttpRequest, class_id: int, payload: ProblemIn):
    """만들기 한 번이 문제와 체크리스트 항목을 함께 만든다(#315). `open`이
    참이면 만든 직후 바로 연다 — 필수 항목이 하나도 없으면(`open_problem`과
    같은 규칙) 문제 자체를 만들지 않고 거부한다("실패하면 문제도 안
    생긴다")."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    assert_class_mutable(class_obj)

    submission_formats = _validate_submission_formats(payload.submission_formats)

    # 편집(`update_problem`)과 같은 규칙이다 — 두 자리가 갈리면 만들 때는
    # 통과한 값이 고칠 때 거절되는 상태가 생긴다.
    if payload.model:
        _validate_scoring_model_choice(class_obj, payload.model, current_value="")
    if payload.reasoning_effort:
        _validate_reasoning_effort(payload.reasoning_effort)
    grading_strictness, grading_guideline_text = _validate_grading_guideline(
        payload.grading_strictness, payload.grading_guideline_text
    )

    if payload.open and not any(item.required for item in payload.checklist_items):
        raise HttpError(400, "필수 항목이 하나도 없는 문제는 열 수 없습니다.")

    with transaction.atomic():
        next_order = class_obj.problems.count()
        problem = Problem.objects.create(
            classroom=class_obj,
            title=payload.title,
            description=payload.description,
            submission_formats=submission_formats,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
            grading_strictness=grading_strictness,
            grading_guideline_text=grading_guideline_text,
            syntax_check_enabled=payload.syntax_check_enabled,
            order=next_order,
            status=Problem.Status.OPEN if payload.open else Problem.Status.DRAFT,
        )
        for index, item_in in enumerate(payload.checklist_items):
            ChecklistItem.objects.create(
                problem=problem, label=item_in.label, required=item_in.required, order=index
            )

    return 201, _serialize_problem(problem, class_obj)


@router.get(
    "/classes/{class_id}/problems", response={200: list[ProblemOut], 404: ErrorOut}, auth=jwt_auth
)
def list_problems(request: HttpRequest, class_id: int):
    """강사 본인의 클래스 문제 전부(초안 + 열림), 순서대로."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problems = class_obj.problems.prefetch_related("checklist_items").all()
    active_member_ids = _active_member_ids(class_obj)
    blocking_problem_ids = _problem_ids_blocking_deletion(class_obj)
    return 200, [
        _serialize_problem(
            p, class_obj, active_member_ids=active_member_ids, blocking_problem_ids=blocking_problem_ids
        )
        for p in problems
    ]


@router.post(
    "/classes/{class_id}/problems/reorder",
    response={200: list[ProblemOut], 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def reorder_problems(request: HttpRequest, class_id: int, payload: ProblemReorderIn):
    """정적 세그먼트("reorder")를 가진 라우트는 전부 `/{problem_id}` 동적
    라우트보다 **먼저** 등록해야 한다 — 나중이면 django-ninja가 "reorder"를
    `problem_id` 값으로 먼저 매치해, 이 라우트가 그 동적 라우트 중 하나(메서드가
    다른)에서 405로 막힌다. 이 파일의 라우트 등록 순서가 그래서 이렇다: 정적
    세그먼트 전부 → 동적 `{problem_id}` 전부."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    assert_class_mutable(class_obj)
    problems = {p.id: p for p in class_obj.problems.all()}

    if set(payload.problem_ids) != set(problems):
        raise HttpError(422, "이 클래스의 문제 목록과 일치하지 않습니다.")

    with transaction.atomic():
        for index, problem_id in enumerate(payload.problem_ids):
            problem = problems[problem_id]
            problem.order = index
        Problem.objects.bulk_update(problems.values(), ["order"])

    ordered = sorted(problems.values(), key=lambda p: p.order)
    active_member_ids = _active_member_ids(class_obj)
    blocking_problem_ids = _problem_ids_blocking_deletion(class_obj)
    return 200, [
        _serialize_problem(
            p, class_obj, active_member_ids=active_member_ids, blocking_problem_ids=blocking_problem_ids
        )
        for p in ordered
    ]


@router.get(
    "/classes/{class_id}/problems/from-other-classes",
    response={200: list[ImportableProblemOut], 404: ErrorOut},
    auth=jwt_auth,
)
def list_importable_problems(request: HttpRequest, class_id: int):
    """새 문제 화면의 「이미 있는 문제로 시작하기」, 「내 다른 클래스에서」
    탭(#326) — 강사 본인이 **이 클래스를 뺀 나머지** 클래스에 가진 문제
    전부다. 정적 세그먼트("from-other-classes")라 `/{problem_id}` 동적
    라우트보다 먼저 등록한다(파일 상단 docstring과 같은 이유).

    `class_id`는 그저 "뺄 클래스"를 정하고 그 클래스가 본인 것인지
    확인하는 자리다 — 목록 자체는 다른 클래스들에서 온다. 원본 클래스가
    보관됐어도 그대로 나온다: 보관은 **그 클래스**에 새 내용이 느는 길을
    막는 것이지(`Class.archived_at` docstring), 거기 있던 문제를 다른
    곳으로 복사해 가져오는 것과는 무관하다 — 읽기는 보관 뒤에도 남는다는
    같은 원칙이다."""

    _get_owned_class_or_404(class_id, request.auth_user.id)

    problems = (
        Problem.objects.filter(classroom__instructor_id=request.auth_user.id)
        .exclude(classroom_id=class_id)
        .select_related("classroom")
        .prefetch_related("checklist_items")
        .order_by("classroom__name", "order", "id")
    )
    return 200, [
        ImportableProblemOut(
            id=p.id,
            classroom_id=p.classroom_id,
            classroom_name=p.classroom.name,
            title=p.title,
            description=p.description,
            submission_formats=p.submission_formats,
            syntax_check_enabled=p.syntax_check_enabled,
            checklist_items=[
                ProblemTemplateChecklistItemOut(label=i.label, required=i.required, order=i.order)
                for i in p.checklist_items.all()
            ],
        )
        for p in problems
    ]


@router.get(
    "/classes/{class_id}/problems/mine",
    response={200: ClassroomMyProblemsOut, 404: ErrorOut},
    auth=jwt_auth,
)
def list_my_problems(request: HttpRequest, class_id: int):
    """참여자의 문제 목록(#288) — 통과/미통과가 한눈에 보인다. 정적
    세그먼트("mine")라 `/{problem_id}` 동적 라우트보다 먼저 등록한다(파일
    상단 docstring, `reorder_problems`와 같은 이유).

    **지금 이름과 편집 칸을 숨길 신호도 함께 싣는다**(#372) — 이 화면
    위쪽의 인라인 이름 편집 칸이 그 값을 초기값으로 쓴다(`get_my_problem`이
    `submit_blocked_reason`으로 같은 종류의 신호를 싣는 것과 같은 이유,
    #439).

    **한 번이라도 낸 숨긴 문제는 `hidden_problems`에 따로 실린다**(#406) —
    열린 목록(`problems`)과 같은 방식으로 통과 여부를 계산하지만, 시도가
    없는 숨긴 문제는 이 묶음에도 들지 않는다(#405 「존재 숨김」 규칙).

    **이 목록과 문제 상세가 같은 존재 판정을 쓴다**(#439 AC "내 문제 목록에
    보이는 문제와 상세로 열 수 있는 문제가 언제나 같다") —
    `classroom.participation.visible_problems_queryset`이 열림·숨김 두
    묶음을 한 질의로 내려주고, 여기서는 상태로만 갈라 둘로 쪼갠다."""

    member = _get_member_or_404(class_id, request.auth_user.id)
    visible = list(
        visible_problems_queryset(class_id, member)
        .prefetch_related("checklist_items")
        .order_by("order", "id")
    )
    problems = [p for p in visible if p.status == Problem.Status.OPEN]
    hidden_problems = [p for p in visible if p.status == Problem.Status.HIDDEN]

    all_problems = problems + hidden_problems
    submissions = ClassroomSubmission.objects.filter(
        problem__in=all_problems, member=member
    ).select_related("classroom_score")
    submissions_by_problem: dict[int, list[ClassroomSubmission]] = {}
    for s in submissions:
        submissions_by_problem.setdefault(s.problem_id, []).append(s)

    def _list_items(problem_list: list[Problem]) -> list[ClassroomProblemListItemOut]:
        items = []
        for problem in problem_list:
            passed = any(
                problem.is_score_passed(getattr(s, "classroom_score", None))
                for s in submissions_by_problem.get(problem.id, [])
            )
            items.append(
                ClassroomProblemListItemOut(
                    id=problem.id,
                    title=problem.title,
                    submission_formats=problem.submission_formats,
                    passed=passed,
                )
            )
        return items

    return 200, ClassroomMyProblemsOut(
        class_name=member.classroom.name,
        member_display_name=member.display_name,
        member_expelled=member.expelled_at is not None,
        archived=member.classroom.archived_at is not None,
        problems=_list_items(problems),
        hidden_problems=_list_items(hidden_problems),
    )


@router.get(
    "/classes/{class_id}/problems/{problem_id}",
    response={200: ProblemOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_problem(request: HttpRequest, class_id: int, problem_id: int):
    """문제 편집 화면이 초기값을 채우는 자리."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    return 200, _serialize_problem(problem, class_obj)


@router.patch(
    "/classes/{class_id}/problems/{problem_id}",
    response={200: ProblemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def update_problem(request: HttpRequest, class_id: int, problem_id: int, payload: ProblemPatchIn):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)

    submission_formats = (
        _validate_submission_formats(payload.submission_formats)
        if payload.submission_formats is not None
        else None
    )
    if payload.model:
        _validate_scoring_model_choice(class_obj, payload.model, current_value=problem.model)
    if payload.reasoning_effort:
        _validate_reasoning_effort(payload.reasoning_effort)

    # 두 칸 중 하나라도 보내면 둘 다 함께 검증한다 — "문장은 직접 입력일
    # 때만 비어 있지 않다"는 두 칸을 함께 봐야 판단할 수 있는 불변식이라,
    # 필드 하나만 따로 저장하면 어긋난 상태가 생길 수 있다(#386). 예를
    # 들어 `grading_strictness="custom"`만 보내면 문장은 지금 저장된
    # 값(비-CUSTOM이었다면 빈 문자열)을 그대로 검증에 쓴다.
    grading_strictness = None
    grading_guideline_text = None
    if payload.grading_strictness is not None or payload.grading_guideline_text is not None:
        grading_strictness, grading_guideline_text = _validate_grading_guideline(
            payload.grading_strictness
            if payload.grading_strictness is not None
            else problem.grading_strictness,
            payload.grading_guideline_text
            if payload.grading_guideline_text is not None
            else problem.grading_guideline_text,
        )

    update_fields = []
    if payload.title is not None:
        problem.title = payload.title
        update_fields.append("title")
    if payload.description is not None:
        problem.description = payload.description
        update_fields.append("description")
    if submission_formats is not None:
        problem.submission_formats = submission_formats
        update_fields.append("submission_formats")
    if payload.model is not None:
        problem.model = payload.model
        update_fields.append("model")
        # 강사가 이 문제의 채점 모델을 손댔으니 재시도할 자격을 준다(#403
        # AC "모델을 바꾼 뒤 새 시도는 새 모델로 채점된다") — 같은 값을
        # 다시 보내도 마찬가지다: "설정을 확인했다"는 사실 자체가 재시도
        # 트리거다, 값이 실제로 달라졌는지는 따지지 않는다.
        problem.scoring_model_rejected_at = None
        update_fields.append("scoring_model_rejected_at")
    if payload.reasoning_effort is not None:
        problem.reasoning_effort = payload.reasoning_effort
        update_fields.append("reasoning_effort")
    if grading_strictness is not None:
        problem.grading_strictness = grading_strictness
        problem.grading_guideline_text = grading_guideline_text
        update_fields.extend(["grading_strictness", "grading_guideline_text"])
    if payload.syntax_check_enabled is not None:
        problem.syntax_check_enabled = payload.syntax_check_enabled
        update_fields.append("syntax_check_enabled")
    if update_fields:
        problem.save(update_fields=[*update_fields, "updated_at"])
    return 200, _serialize_problem(problem, class_obj)


@router.delete(
    "/classes/{class_id}/problems/{problem_id}",
    response={204: None, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def delete_problem(request: HttpRequest, class_id: int, problem_id: int):
    """아무도 내지 않은 문제, 또는 강사 자신만 내본 문제를 없던 일로 한다
    (#430/#431, ADR-0050) — 클래스 삭제(위 `delete_class`)와 같은 절차·같은
    판정 모양이다. **참여자의 시도가 하나라도 있으면 거절한다**(내보낸
    참여자의 시도도 「남은 시도」다, `_problem_deletable`). 그 조건을 만족하면
    강사 자신의 시도에 달린 채점을 QuerySet `delete()`로 먼저 걷는다 — 걷어내는
    범위는 「그 문제 × 강사 자신」으로 닫혀 있고, 그 필터가 이 우회의 근거
    전부다(넓히지 않는다). 강사 자신의 시도가 없으면(#430의 원래 경우, 시도가
    0) 이 삭제는 아무 행도 지우지 않는 no-op이다.

    체크리스트 항목·시도(`ClassroomSubmission`)는 `Problem`에 걸린 CASCADE로
    함께 지워진다. 이 문제를 공개한 템플릿(`ProblemTemplate`)은 이 문제를
    가리키지 않는, 공개 시점에 뜬 사본이라 영향받지 않는다(#316). 삭제된
    문제를 가리키는 채점 완료 알림은 그대로 남는다(ADR-0050 결과 — 알림을
    함께 지우면 알림이 append-only가 아니게 된다). 공모전의 `Score`·원장에는
    닿지 않는다(강의실과 공모전은 서로 다른 앱 경계, ADR-0037/0039)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)
    if not _problem_deletable(problem, class_obj):
        raise HttpError(403, "지울 수 없습니다 — 대신 숨겨주세요.")
    # 채점을 걷는 것과 문제를 지우는 것, 둘이 한 트랜잭션이어야 한다 — 둘로
    # 쪼개진 채 죽으면(#431이 채점 걷기를 더하며 새로 생긴 위험) 채점만 사라지고
    # 문제·시도는 남는 어중간한 상태가 생긴다.
    with transaction.atomic():
        ClassroomScore.objects.filter(
            submission__problem=problem, submission__member__user_id=class_obj.instructor_id
        ).delete()
        problem.delete()
    return 204, None


@router.post(
    "/classes/{class_id}/problems/{problem_id}/open",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def open_problem(request: HttpRequest, class_id: int, problem_id: int):
    """초안을 연다. 필수 체크리스트 항목이 하나도 없으면 통과가 정의되지
    않아 막는다(#283 AC). 전이 표(`classroom.problem_transitions`, #440)가
    「초안에서만」과 「필수 항목이 있어야」 두 조건을 함께 정한다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)

    assert_transition_from_state("open", problem, wrong_state_message="초안만 열 수 있습니다.")
    assert_has_required_item(problem, message="필수 항목이 하나도 없는 문제는 열 수 없습니다.")

    problem.status = Problem.Status.OPEN
    problem.save(update_fields=["status", "updated_at"])
    return 200, _serialize_problem(problem, class_obj)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/hide",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def hide_problem(request: HttpRequest, class_id: int, problem_id: int):
    """열린 문제를 참여자에게서 거둔다(#405) — 제출 유무와 무관하다. 열림
    →숨김만 허용한다: 초안은 애초에 참여자에게 보인 적이 없어 거둘 것이
    없고, 이미 숨긴 문제를 다시 숨기는 것도 뜻이 없다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)

    assert_transition_from_state("hide", problem, wrong_state_message="열린 문제만 숨길 수 있습니다.")

    problem.status = Problem.Status.HIDDEN
    problem.save(update_fields=["status", "updated_at"])
    return 200, _serialize_problem(problem, class_obj)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/reopen",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def reopen_problem(request: HttpRequest, class_id: int, problem_id: int):
    """숨긴 문제를 되돌린다(#405) — 지난 시도·통과는 손대지 않고 상태만
    되돌린다. `open_problem`과 같은 필수 항목 규칙을 다시 확인한다: 그
    사이 강사가 체크리스트를 비웠으면 통과가 정의되지 않아 열 수 없다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)

    assert_transition_from_state("reopen", problem, wrong_state_message="숨긴 문제만 다시 열 수 있습니다.")
    assert_has_required_item(problem, message="필수 항목이 하나도 없는 문제는 열 수 없습니다.")

    problem.status = Problem.Status.OPEN
    problem.save(update_fields=["status", "updated_at"])
    return 200, _serialize_problem(problem, class_obj)


# --- Submission (참여자, #286) --------------------------------------------------


def _get_member_or_404(class_id: int, user_id: int) -> ClassMember:
    """강사 전용 엔드포인트의 `_get_owned_class_or_404`와 같은 존재-숨김
    규칙을 참여자 쪽에서 지킨다 — 참여자가 아니면 그 문제가 아예 없는 것처럼
    404를 받는다(#286 AC "그 클래스의 참여자가 아니면 제출할 수 없다"). 강사
    본인도 ClassMember 행이 없으면(가입 링크로 자기 클래스에 들어온 적이
    없으면) 여기 닿지 못한다 — 참여자 표면은 어디까지나 ClassMember 기준이다."""

    try:
        return ClassMember.objects.select_related("classroom").get(
            classroom_id=class_id, user_id=user_id
        )
    except ClassMember.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


def _get_submitting_member_or_404(class_id: int, user_id: int) -> ClassMember:
    """제출하는 사람의 참여자 행 — 없으면 404다(`_get_member_or_404`와 같은
    존재-숨김 규칙).

    **다만 그 클래스의 강사 본인은 여기서 행을 만들어 준다**(2026-09-17, #429
    개정). 강사도 열린 문제에는 낼 수 있어야 하는데, 제출물·명단·채점이 모두
    참여자 행을 가리키므로 행이 필요하다 — 예전에는 강사가 **가입 링크로 자기
    클래스에 들어간 적이 있을 때만** 그 행이 있었고, 그래서 자기 문제를 내
    보려면 링크를 스스로 열어야 했다(그 사실을 아는 사람이 없었다). 이름은
    클래스에 이미 적어 둔 강사 이름을 그대로 쓴다.

    보관된 클래스에서는 행을 만들지 않는다 — 읽기 전용이라 어차피 제출이
    403이고, 없던 행을 남기지 않는 편이 정직하다."""

    try:
        return ClassMember.objects.select_related("classroom").get(
            classroom_id=class_id, user_id=user_id
        )
    except ClassMember.DoesNotExist:
        pass

    class_obj = Class.objects.filter(id=class_id, instructor_id=user_id).first()
    if class_obj is None:
        raise HttpError(404, "문제를 찾을 수 없습니다.")
    if class_obj.archived_at is not None:
        raise HttpError(403, "이 클래스는 보관되어 새 제출을 받지 않습니다.")

    member, _created = ClassMember.objects.get_or_create(
        classroom=class_obj,
        user_id=user_id,
        defaults={"display_name": class_obj.instructor_display_name or "강사"},
    )
    member.classroom = class_obj
    return member


def _get_visible_problem_for_participant_or_404(
    class_id: int, problem_id: int, member: ClassMember
) -> Problem:
    """참여자에게는 열린 문제와, **그 참여자가 한 번이라도 낸** 숨긴
    문제만 존재한다(#405) — 초안과, 낸 적 없는 숨긴 문제는 강사만 본다
    (Problem docstring, CONTEXT.md 「Problem」). 남의 클래스와 같은 이유로
    404다 — 숨김은 존재를 숨기는 게 아니라 낸 사람에게는 계속 보인다는
    점이 다를 뿐, 그 밖에는 같은 "존재 숨김" 규칙을 따른다.

    `classroom.participation.visible_problems_queryset`을 그대로 쓴다 —
    `list_my_problems`가 목록을 거르는 것과 같은 질의라야 「목록에 보이는
    문제와 상세로 열 수 있는 문제가 언제나 같다」(#439 AC)가 성립한다."""

    try:
        return (
            visible_problems_queryset(class_id, member)
            .select_related("classroom")
            .prefetch_related("checklist_items")
            .get(id=problem_id)
        )
    except Problem.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


def _serialize_own_submissions(problem, member, user, checklist_items) -> list:
    """이 사람 자신의 시도만 최신 순으로 — 남의 시도는 질의에 애초에 없다
    (`member=member`). 참여자와 강사(#429 개정)가 같은 함수를 쓴다: 강사가 아직
    참여자 행이 없으면(`member is None`) 낸 적이 없다는 뜻이라 빈 목록이다."""

    if member is None:
        return []
    submissions = (
        ClassroomSubmission.objects.filter(problem=problem, member=member)
        .select_related("classroom_score")
        .prefetch_related("assets")
        .order_by("-attempt_number")
    )
    return [
        # `s.assets.all()[0]`이 아니라 리스트로 먼저 받는다 — 그래야
        # `prefetch_related("assets")`가 채워 둔 캐시를 쓴다. `.get()`은
        # 매니저를 거쳐 매번 새 질의를 날려 그 prefetch를 헛수고로 만든다.
        _serialize_classroom_submission(
            s,
            asset=list(s.assets.all())[0],
            user=user,
            class_obj=problem.classroom,
            problem=problem,
            checklist_items=checklist_items,
        )
        for s in submissions
    ]


def _instructor_submit_blocked_reason(class_obj: Class, problem: Problem) -> str | None:
    """강사가 자기 클래스의 이 문제에 지금 낼 수 없는 이유 하나(2026-09-17,
    #429 개정) — 열린 문제에는 낼 수 있으므로 `None`이다. 보관된 클래스는
    참여자와 같은 이유로 막고(읽기 전용), 초안·숨김은 참여자에게 애초에 보이지
    않는 상태라 「강사가 보는 중」이 그 자리를 대신한다 — 화면의 띠가 그 상태를
    이미 설명하고 있어 새 문구를 만들지 않는다."""

    if class_obj.archived_at is not None:
        return SUBMIT_BLOCKED_ARCHIVED
    if problem.status != Problem.Status.OPEN:
        return SUBMIT_BLOCKED_VIEWING_AS_INSTRUCTOR
    return None


@router.get(
    "/classes/{class_id}/problems/{problem_id}/mine",
    response={200: ClassroomProblemSubmissionsOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_my_problem(request: HttpRequest, class_id: int, problem_id: int):
    """참여자가 보는 문제 하나 — 체크리스트와 본인의 시도 목록(#286). 남의
    시도는 애초에 이 질의에 없다(`member=member` 필터) — "남의 제출물을 볼 수
    없다"는 AC를 별도 권한 검사가 아니라 쿼리 모양으로 지킨다.

    **그 클래스의 강사가 부르면 달리 대한다**(#429) — 참여자가 실제로 걷는
    이 주소 그대로 「학생 화면으로」가 연다. 상태(초안·열림·숨김)와 무관하게
    문제를 내려준다. 강사 판정은 `instructor_id`만 본다.

    **열린 문제에는 강사도 낸다**(2026-09-17, #429 개정). 예전에는 이 분기가
    시도 목록을 언제나 빈 배열로 주고 제출을 막힌 것으로 표시해, 강사가 자기
    문제를 직접 내 볼 길이 화면에 없었다 — 가입 링크로 자기 클래스 참여자가
    되어 있어도 그랬다. 이제 **자기 시도는 그대로 보이고**(남의 시도는 여전히
    이 질의에 없다), 문제가 열려 있고 클래스가 보관되지 않았으면 제출 잠금이
    풀린다. 「강사가 보는 중」은 `viewing_as_instructor`가 따로 말한다 —
    초안·숨김처럼 참여자라면 못 낼 상태에서는 그 사유가 여전히 잠금을 건다.
    명단·달성률·토큰 예산이 강사를 세지 않는 것은 그대로다(#290 — 강사 행은
    격자에 표시만 되고 집계에서 빠진다)."""

    instructor_class = Class.objects.filter(id=class_id, instructor_id=request.auth_user.id).first()
    if instructor_class is not None:
        class_obj = instructor_class
        problem = _get_owned_problem_or_404(class_obj, problem_id)
        member = ClassMember.objects.filter(
            classroom=class_obj, user_id=request.auth_user.id
        ).first()
        checklist_items = list(problem.checklist_items.all())
        submissions = _serialize_own_submissions(
            problem, member, request.auth_user, checklist_items
        )
        return 200, ClassroomProblemSubmissionsOut(
            class_name=class_obj.name,
            problem=_serialize_problem_mine(
                problem, passed=any(s.passed for s in submissions)
            ),
            submissions=submissions,
            # 낼 수 있는 상태가 아니면 그 이유를 말한다 — 보관이 먼저다
            # (참여자와 같은 우선순위), 초안·숨김은 참여자에게 애초에 보이지
            # 않는 상태라 「강사가 보는 중」이 그 자리를 대신한다.
            submit_blocked_reason=_instructor_submit_blocked_reason(class_obj, problem),
            instructor_problem_status=problem.status,
            viewing_as_instructor=True,
        )

    member = _get_member_or_404(class_id, request.auth_user.id)
    problem = _get_visible_problem_for_participant_or_404(class_id, problem_id, member)
    checklist_items = list(problem.checklist_items.all())

    serialized_submissions = _serialize_own_submissions(
        problem, member, request.auth_user, checklist_items
    )
    return 200, ClassroomProblemSubmissionsOut(
        class_name=problem.classroom.name,
        # 문제 자체의 통과 여부는 시도 전체의 OR이다(#288 AC "한 번 통과하면
        # 유지된다") — 최신 시도만 보지 않는다.
        problem=_serialize_problem_mine(
            problem, passed=any(s.passed for s in serialized_submissions)
        ),
        submissions=serialized_submissions,
        # 내보내진 사람도 지난 시도는 그대로 읽되(#300 AC), 화면이 제출
        # 수단을 감추고 이유를 말해 줄 수 있도록 이유 하나만 얹는다(#439,
        # 우선순위는 보관 → 내보냄 → 숨김) — 막는 문 자체는 여전히
        # `create_classroom_submission`의 403이다.
        submit_blocked_reason=participant_submit_blocked_reason(member.classroom, member, problem),
    )


def _enqueue_immediate_scoring(submission_id: int) -> None:
    """시도 하나의 즉시 채점 작업을 큐에 넣는다(#378, ADR-0046). **발행이 실패해도
    제출을 실패시키지 않는다** — 이 콜백은 트랜잭션이 커밋된 뒤에 돌므로 시도는 이미
    저장됐고, 60초 스캔이 그 시도를 줍는다(안전망). 여기서 예외가 튀면 참여자는
    저장된 시도에 500 을 받고 다시 내 시도가 중복된다 — 브로커(Redis)가 재시작 중이거나
    호스트 runserver 의 기본 브로커 주소가 비어 있을 때 실제로 그렇게 된다."""

    try:
        score_attempt.delay(submission_id)
    except Exception:  # noqa: BLE001 — 어떤 브로커 오류든 스캔이 대신 줍는다
        logger.warning(
            "강의실 즉시 채점 작업을 큐에 넣지 못했다 — 스캔이 줍는다 (submission_id=%s)",
            submission_id,
            exc_info=True,
        )


@router.post(
    "/classes/{class_id}/problems/{problem_id}/submissions",
    response={201: ClassroomSubmissionOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def create_classroom_submission(
    request: HttpRequest, class_id: int, problem_id: int, payload: ClassroomSubmissionIn
):
    """제출할 때마다 새 시도가 쌓인다 — 마감도 시도 횟수 상한도 없다
    (ADR-0039, CONTEXT.md 「Problem」). 근거 연결도 자가 체크도 없다: 소스
    또는 저장소 값 하나만 받는다."""

    member = _get_submitting_member_or_404(class_id, request.auth_user.id)
    problem = _get_visible_problem_for_participant_or_404(class_id, problem_id, member)

    # 낼 수 있는가는 참여 정책 모듈이 한 곳에서 답한다(#439) — 우선순위는
    # 보관 → 내보냄 → 숨김이고, 화면의 `submit_blocked_reason`과 여기 문이
    # 같은 기준이어야 어긋나지 않는다.
    blocked_reason = participant_submit_blocked_reason(member.classroom, member, problem)
    if blocked_reason == SUBMIT_BLOCKED_ARCHIVED:
        # #294 AC "보관된 클래스에는 새 제출을 낼 수 없다" — 지난 시도는
        # 그대로 읽히므로(`get_my_problem`) 이 엔드포인트만 막는다.
        raise HttpError(403, "이 클래스는 보관되어 새 제출을 받지 않습니다.")
    if blocked_reason == SUBMIT_BLOCKED_EXPELLED:
        # ClassMember.expelled_at의 docstring이 이 엔드포인트를 지목해 둔
        # 자리다 — 행은 지우지 않되 새 제출만 막는다. 강사가 이미 그 사실을
        # 아는 사람에게는 404(존재 자체를 숨김)보다 403(권한이 없다는 것을
        # 안다)이 더 정직하다.
        raise HttpError(403, "더 이상 이 클래스의 참여자가 아닙니다.")
    if blocked_reason == SUBMIT_BLOCKED_HIDDEN:
        # 강사가 거둔 문제다(#405) — 낸 적 있는 사람만 여기 닿는다
        # (`_get_visible_problem_for_participant_or_404`), 그래도 새로
        # 낼 수는 없다. 다시 열면(`reopen_problem`) 이 분기를 벗어난다.
        raise HttpError(403, "강사가 숨긴 문제라 새로 낼 수 없습니다.")

    value = payload.value.strip()
    if not value:
        raise HttpError(422, "제출 값을 입력해주세요.")

    if payload.submission_format not in problem.submission_formats:
        # 화면을 우회해도 서버가 거절한다(#373 AC) — 허용 목록 밖의 형식은
        # 그 자체로 422다, 값의 모양이 맞고 틀리고와 무관하다.
        raise HttpError(422, f"이 문제가 받지 않는 제출 형식입니다: {payload.submission_format}")

    content_type = ""
    if payload.submission_format == Problem.SubmissionFormat.SOURCE:
        expected_ref = source_target_ref(problem.id, request.auth_user.id)
        if not value.startswith(f"{expected_ref}/"):
            raise HttpError(422, "본인의 업로드 대상에 속하지 않는 소스입니다.")
        asset_kind = SubmissionAsset.Kind.SOURCE
        content_type = (payload.content_type or "").strip()
    else:
        if not GITHUB_REPO_URL_PATTERN.match(value):
            raise HttpError(422, "저장소는 https://github.com/<owner>/<repo> 형식만 받습니다.")
        asset_kind = SubmissionAsset.Kind.REPOSITORY

    with transaction.atomic():
        # 시도 번호는 참여자 행을 잠그고 센다 — 같은 참여자가 같은 문제에
        # 동시에 두 번 제출해도 번호가 겹치지 않게 한다(#10류 동시성 규율과
        # 같은 이유, 유니크 제약이 없는 자리라 여기서 직접 막는다).
        locked_member = ClassMember.objects.select_for_update().get(id=member.id)
        next_attempt = (
            ClassroomSubmission.objects.filter(problem=problem, member=locked_member).count() + 1
        )
        submission = ClassroomSubmission.objects.create(
            user_id=request.auth_user.id,
            product=Submission.Product.CLASSROOM,
            problem=problem,
            member=locked_member,
            attempt_number=next_attempt,
        )
        asset = SubmissionAsset.objects.create(
            submission=submission, kind=asset_kind, value=value, content_type=content_type
        )
        # 이 시도가 생겼다는 신호를 그 참여자와 그 클래스 강사에게 낸다
        # (#383, ADR-0046) — 강사 제출 현황이 새로고침 없이 새 시도를 보여줄
        # 수 있게 한다. 커밋 뒤 발행 규율은 `publish_attempt_submitted`
        # 안에 있다(아래 즉시 채점 큐잉과 같은 이유로 `on_commit`을 쓴다).
        publish_attempt_submitted(submission)
        # 이 시도의 채점을 곧바로 큐에 넣는다(#378, ADR-0046) — 60초 스캔을
        # 기다리지 않는다. `on_commit`인 이유는 트랜잭션이 아직 커밋되지
        # 않았을 때 태스크가 먼저 돌면(워커가 있는 배포 환경에서는 그럴 수
        # 있다) 내부 엔드포인트가 아직 존재하지 않는 시도를 채점하려 들기
        # 때문이다. dev·CI는 워커가 없어 이 태스크가 실제로 돌지 않고
        # (#40), 큐에 쌓인 채 스캔이 안전망으로 대신 줍는다.
        transaction.on_commit(lambda: _enqueue_immediate_scoring(submission.id))

    # 방금 만든 시도는 아직 채점되지 않아 언제나 passed=False다
    # (`Problem.is_score_passed`가 `score is None`을 바로 거짓으로 본다).
    return 201, _serialize_classroom_submission(
        submission,
        asset=asset,
        user=request.auth_user,
        class_obj=problem.classroom,
        problem=problem,
    )


@router.get(
    "/classes/{class_id}/problems/{problem_id}/submissions",
    response={200: list[ClassroomInstructorSubmissionOut], 404: ErrorOut},
    auth=jwt_auth,
)
def list_problem_submissions(request: HttpRequest, class_id: int, problem_id: int):
    """강사가 참여자들의 시도를 훑어본다(#291) — 소스 다운로드, 저장소 URL(이미
    `value`가 그 주소다), AI 판정과 근거가 한 번에 실린다.

    **이 요청은 어디에도 기록되지 않는다**(ADR-0040) — 강사가 보는 것은 지도
    그 자체라 "몇 번 봤다"가 신호가 아니라 잡음이 된다. 그래서 이 엔드포인트는
    어떤 모델도 만들지 않는다.

    같은 경로에 있는 `POST`(참여자의 제출, 위 `create_classroom_submission`)와
    메서드로만 갈린다 — `/join/{join_code}`가 GET(누구나)·POST(로그인)로
    갈리는 것과 같은 모양이다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    checklist_items = list(problem.checklist_items.all())

    submissions = (
        ClassroomSubmission.objects.filter(problem=problem)
        .select_related("classroom_score", "member")
        .prefetch_related("assets")
        .order_by("member__display_name", "-attempt_number")
    )
    return 200, [
        _serialize_instructor_submission(
            # `_mine`과 같은 이유로 리스트를 먼저 받아 prefetch 캐시를 쓴다.
            s,
            asset=list(s.assets.all())[0],
            class_obj=class_obj,
            problem=problem,
            checklist_items=checklist_items,
        )
        for s in submissions
    ]
@router.post(
    "/classes/{class_id}/problems/{problem_id}/copy",
    response={201: ProblemOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def copy_problem(request: HttpRequest, class_id: int, problem_id: int, payload: ProblemCopyIn):
    """자기 문제를 자기 다른 클래스로 복사한다(#292, #326의 「내 다른
    클래스에서」 가져오기도 방향만 반대일 뿐 같은 엔드포인트를 부른다).
    원본·대상 둘 다 강사 본인 소유여야 한다 — 어느 쪽이 남의 것이어도
    404다(존재를 알려주지 않는다, 이 파일의 다른 소유권 검사와 같은
    이유).

    **대상 클래스가 보관됐으면 403이다**(#326 AC "보관된 클래스에서는
    가져올 수 없다", #438) — `classroom.participation.assert_class_mutable`이
    `problem_templates.import_template`과 같은 규칙을 여기서도 지킨다: 보관은
    읽기 전용이라는 뜻이라 복사도 예외가 아니다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    target_class = _get_owned_class_or_404(payload.target_class_id, request.auth_user.id)
    assert_class_mutable(target_class)

    copy = copy_problem_to_class(problem, target_class)
    return 201, _serialize_problem(copy, target_class)


# --- ChecklistItem -------------------------------------------------------------


def _get_owned_checklist_item_or_404(problem: Problem, item_id: int) -> ChecklistItem:
    try:
        return problem.checklist_items.get(id=item_id)
    except ChecklistItem.DoesNotExist as exc:
        raise HttpError(404, "체크리스트 항목을 찾을 수 없습니다.") from exc


@router.post(
    "/classes/{class_id}/problems/{problem_id}/checklist-items",
    response={201: ChecklistItemOut, 404: ErrorOut},
    auth=jwt_auth,
)
def create_checklist_item(
    request: HttpRequest, class_id: int, problem_id: int, payload: ChecklistItemIn
):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)

    next_order = problem.checklist_items.count()
    item = ChecklistItem.objects.create(
        problem=problem, label=payload.label, required=payload.required, order=next_order
    )
    return 201, _serialize_checklist_item(item)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/reorder",
    response={200: list[ChecklistItemOut], 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def reorder_checklist_items(
    request: HttpRequest, class_id: int, problem_id: int, payload: ChecklistReorderIn
):
    """정적 세그먼트("reorder")라 `{item_id}` 동적 라우트보다 먼저 등록한다
    (파일 상단 docstring 참고)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    assert_class_mutable(class_obj)
    items = {i.id: i for i in problem.checklist_items.all()}

    if set(payload.item_ids) != set(items):
        raise HttpError(422, "이 문제의 체크리스트 항목과 일치하지 않습니다.")

    with transaction.atomic():
        for index, item_id in enumerate(payload.item_ids):
            items[item_id].order = index
        ChecklistItem.objects.bulk_update(items.values(), ["order"])

    ordered = sorted(items.values(), key=lambda i: i.order)
    return 200, [_serialize_checklist_item(i) for i in ordered]


@router.patch(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
    response={200: ChecklistItemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def update_checklist_item(
    request: HttpRequest,
    class_id: int,
    problem_id: int,
    item_id: int,
    payload: ChecklistItemPatchIn,
):
    """열린·숨긴 문제는 필수 항목을 하나 이상 유지해야 한다(#440) — 마지막
    필수 항목을 필수 해제하면 422로 거절한다(초안은 예외, `classroom.
    problem_transitions.assert_required_item_floor`)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    item = _get_owned_checklist_item_or_404(problem, item_id)
    assert_class_mutable(class_obj)

    if payload.required is False and item.required:
        remaining = problem.checklist_items.filter(required=True).exclude(id=item.id).count()
        assert_required_item_floor(problem, remaining_required_count=remaining)

    update_fields = []
    if payload.label is not None:
        item.label = payload.label
        update_fields.append("label")
    if payload.required is not None:
        item.required = payload.required
        update_fields.append("required")
    if update_fields:
        item.save(update_fields=update_fields)
    return 200, _serialize_checklist_item(item)


@router.delete(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
    response={204: None, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def delete_checklist_item(request: HttpRequest, class_id: int, problem_id: int, item_id: int):
    """열린·숨긴 문제의 마지막 필수 항목은 지울 수 없다(#440) —
    `assert_required_item_floor`와 같은 이유, `update_checklist_item`과
    같은 규율(초안은 예외)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    item = _get_owned_checklist_item_or_404(problem, item_id)
    assert_class_mutable(class_obj)

    if item.required:
        remaining = problem.checklist_items.filter(required=True).exclude(id=item.id).count()
        assert_required_item_floor(problem, remaining_required_count=remaining)

    item.delete()
    return 204, None


# --- 실시간 신호 SSE (ADR-0046, #379) --------------------------------------------
#
# 이 엔드포인트는 배포 환경에서는 API 서버(동기 gunicorn)가 아니라 같은
# backend 이미지를 ASGI 로 띄우는 별도 이벤트 서비스가 연다 — urls.py 는
# 하나뿐이라(같은 코드) 어디서든 라우팅되지만, 실제로 이 경로를 여는 것은
# 강의실 BFF 뿐이고 BFF 는 이벤트 서비스의 포트로만 이 요청을 보낸다.

#: keep-alive 주석 사이의 최대 대기 — 프록시가 유휴 연결을 끊지 않게 한다
#: (모듈 상단 참고 없음, ADR-0046 "주기적인 keep-alive 주석"). fake 버스는
#: 이 값과 무관하게 즉시 돌아온다(`core.events.FakeEventBus`).
_SSE_KEEPALIVE_SECONDS = 15.0


def _format_sse_event(event: Event) -> bytes:
    return f"event: {event.kind}\ndata: {json.dumps(event.payload)}\n\n".encode("utf-8")


async def _stream_events_for(recipient_id: int):
    """**반드시 async 제너레이터다.** 동기 제너레이터로 두면 Django의 ASGI
    핸들러가 "StreamingHttpResponse must consume synchronous iterators in
    order to serve them asynchronously" 경고와 함께 완전히 다른(뒤로
    미뤄지는) 소비 경로를 타 실제로는 아무것도 실시간으로 나가지 않는다 —
    dev 스택에서 실제 요청으로 직접 확인했다(연결은 200 으로 열리지만
    keep-alive 조차 15초·20초 뒤에도 도착하지 않았다). `bus.subscribe`·
    `poll`은 동기 계약(Redis 클라이언트가 동기다)이라 그대로 두고,
    블로킹 호출만 `asyncio.to_thread`로 이벤트 루프 밖에서 돈다."""

    bus = get_event_bus()
    with bus.subscribe(recipient_id) as subscription:
        while True:
            events = await asyncio.to_thread(subscription.poll, timeout=_SSE_KEEPALIVE_SECONDS)
            if not events:
                yield b": keep-alive\n\n"
                continue
            for event in events:
                yield _format_sse_event(event)


@router.get("/events/stream", auth=jwt_auth)
async def stream_events(request: HttpRequest):
    """인증된 사용자 자신에게 온 신호만 흘린다(ADR-0046) — 다른 사용자의
    신호는 이 함수에 닿지도 않는다(`core.events`가 recipient_id 로 이미
    갈라 둔다). 인증 없는 요청은 `auth=jwt_auth`가 ninja 기본 401로 거절한다
    — 이 함수 몸통까지 오지 않는다.

    `StreamingHttpResponse`를 그대로 돌려준다 — django-ninja는 결과가 이미
    `HttpResponseBase`면 응답 스키마 직렬화를 건너뛰고 그대로 내보낸다."""

    response = StreamingHttpResponse(
        _stream_events_for(request.auth_user.id), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    # nginx 류 리버스 프록시가 이 응답을 버퍼링하지 않게 하는 표준 신호다 —
    # 저장소 밖의 TLS 종단 프록시가 실제로 이걸 지키는지는 사람의 바깥
    # 작업이지만(CLAUDE.md), 애플리케이션 쪽에서 낼 수 있는 신호는 여기서 낸다.
    response["X-Accel-Buffering"] = "no"
    return response
