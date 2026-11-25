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

import json
import logging
import time

from collections.abc import Mapping
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import connections, transaction
from django.db.models import Count, Max
from django.http import HttpRequest, StreamingHttpResponse
from django.utils import timezone
from notifications.models import NotificationType
from notifications.services import notify_safely
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import SocialAccount
from core.clock import Clock
from core.contest_catalog import EntryAsset, contest_catalog
from core.crypto import encrypt
from core.events import Event, EventBusDisconnected, get_event_bus
from core import privacy_policy
from core.keyset import decode_cursor, encode_cursor
from core.llm_scoring import LLMKeyCheckStatus
from core.model_context import context_window_tokens
from core.observability import tag_error_scope
from core.quality_review import mask_hidden_quality_items
from policies.services import get_current_policy
from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename, safe_download_base_name
from submissions.models import (
    Submission,
    SubmissionAsset,
    REPOSITORY_URL_SHAPES_MESSAGE,
    parse_github_submission_url,
)
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION

from .departures import is_left, left_member_ids
from .models import (
    ANTHROPIC_KEY_FIELDS,
    OPENAI_KEY_FIELDS,
    LateStatus,
    ChecklistGrade,
    ChecklistItem,
    Class,
    ClassMember,
    ClassroomScore,
    ClassroomScoreCorrection,
    ClassroomSubmission,
    ClassScoringKeyMissingAlert,
    ClassTemplate,
    CoInstructorInvite,
    OwnershipTransfer,
    Problem,
    ProblemTemplate,
    key_fields_for,
)
from .contest_entries import (
    EntryMarks,
    entry_marks,
    contest_entry_form,
    contest_entry_out,
    prepare_contest_entry,
    request_contest_entry,
)
from .contest_problems import contest_state, import_contest_problem
from .schemas import STAGED_VERDICT_KEYS
from .schemas import (
    MyQualityOut,
    QualityBoardOut,
    QualityEstimateOut,
    QualityItemOut,
    ClassroomBonusScoreIn,
    ClassroomBonusScoreOut,
    QualityRankRowOut,
    QualityRunOut,
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemSavedOut,
    GradabilityWarningOut,
    ImportableContestOut,
    ImportableContestPageOut,
    ImportContestIn,
    ProblemContestOut,
    ChecklistItemPatchIn,
    ChecklistReorderIn,
    ClassIn,
    ClassOut,
    GradingMethodOptionOut,
    ClassPatchIn,
    ClassroomChecklistVerdictOut,
    ClassroomHiddenSummaryOut,
    ClassroomGridCellOut,
    ClassroomGridMemberOut,
    ClassroomInstructorSubmissionOut,
    ClassroomMyProblemsOut,
    ClassroomProblemListItemOut,
    ClassroomProblemMineOut,
    ClassroomProblemStatsOut,
    ClassroomProblemSubmissionsOut,
    ClassroomAttemptChecklistItemOut,
    ClassroomAttemptPageOut,
    ClassroomAttemptVerdictsOut,
    ClassroomAttemptRowOut,
    ClassroomRecentAttemptOut,
    ClassroomRosterGridOut,
    ClassroomScoreOut,
    SubmissionRejectionOut,
    ClassroomSubmissionIn,
    ClassroomSubmissionOut,
    ContestEntryFormOut,
    ClassroomSyntaxCheckFindingOut,
    ClassroomSyntaxCheckOut,
    ErrorOut,
    CoInstructorAcceptIn,
    CoInstructorAcceptOut,
    CoInstructorInviteOut,
    CoInstructorInvitePreviewOut,
    ClassInstructorOut,
    InstructorNameIn,
    PendingCoInstructorInviteOut,
    ImportableProblemOut,
    FormerClassOut,
    JoinedClassOut,
    JoinIn,
    JoinLinkOut,
    JoinPreviewOut,
    JoinResultOut,
    MemberOut,
    MemberRenameIn,
    MemberRenameOut,
    OpenAIKeyIn,
    ScoringVendorIn,
    VendorKeyOut,
    CompatibleServerIn,
    ProblemCopyIn,
    ProblemIn,
    ProblemOut,
    ProblemPatchIn,
    ProblemReorderIn,
    ProblemTemplateChecklistItemOut,
    template_checklist_item_out,
    ProblemTransitionOut,
    PublishedTemplateSummaryOut,
    ScoringCalculatorOut,
    ScoringCostAttemptOut,
    ScoringCostEstimateOut,
    ScoringCostRowOut,
    ScoringModelCatalogOut,
    ScoringModelOut,
    OwnershipTransferIn,
    PendingOwnershipTransferOut,
    ZipGitHistoryWarningOut,
)
from .git_history_hint import zip_git_history_item_ids
from .gradability_hint import gradability_warnings
from . import agent_grading, pending_scoring, quality, score_corrections
from .score_reuse import score_reused
from .events import (
    publish_attempt_submitted,
    publish_instructors_changed,
    publish_participation_changed,
    publish_problems_changed,
)
from .current_score import CurrentClassroomScore, current_score, current_score_prefetch
from .instructor_scope import OWNER_ONLY_MESSAGE, class_scope, owned_problem_or_404, problem_scope
from .instructors import active_participant_q, classes_owned_by, classes_taught_by, instructor_display_name_of, instructor_user_ids, is_instructor, is_owner
from .participation import (
    SUBMIT_BLOCKED_ARCHIVED,
    SUBMIT_BLOCKED_EXPELLED,
    SUBMIT_BLOCKED_LEFT,
    SUBMIT_BLOCKED_HIDDEN,
    instructor_can_submit,
    participant_membership_blocked_reason,
    participant_submit_blocked_reason,
    visible_problems_queryset,
)
from . import class_authoring, co_instructors, ownership_transfers, problem_authoring
from .problem_transitions import available_transitions, execute_transition
from .scoring import check_scoring_key, enqueue_scoring
from .scoring_key_missing import alert_missing_key_safely, close_open_alert
from . import rule_derivation, scoring_calculator, scoring_cost
from .scoring_model_catalog import cached_scoring_model_catalog, get_scoring_model_catalog, remember_model_ids
from . import scoring_connection
from .scoring_models import (
    DEFAULT_ANTHROPIC_SCORING_MODEL,
    DEFAULT_SCORING_MODEL,
    is_claude_model_id,
    is_reasoning_model_id,
)
from .submission_target_refs import source_target_ref
from .services import copy_class, copy_problem_to_class, instructor_classes
from .verdicts import verdict_of

logger = logging.getLogger(__name__)

router = Router(tags=["classroom"])

#: 마스킹은 복호화가 아니라 저장 시점에 남긴 마지막 네 자리로만 만든다 —
#: `Class.openai_api_key_encrypted`를 다시 풀지 않는다(#284, 파일 상단 라우터
#: docstring과 같은 이유: 복호화는 채점 요청을 보낼 때만 한다).
_KEY_MASK_PREFIX = "••••••••"


def _sends_reasoning_effort(class_obj: Class, model_id: str, *, marked_reasoning: bool) -> bool:
    """화면이 「추론 강도」 칸을 보일지 — 채점 요청에 그 값을 실을 때만. 호환 서버는 이름으로 알 수
    없어 「추론 모델」 스위치(`marked_reasoning`, #602)를 따른다(`ScoringConnection.
    sends_reasoning_effort` 와 같은 판단)."""

    if class_obj.scoring_connection_kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        return marked_reasoning
    if class_obj.scoring_connection_kind == Class.ScoringConnectionKind.ANTHROPIC_KEY:
        return is_claude_model_id(model_id)
    return is_reasoning_model_id(model_id)


#: 시도 목록이 채점과 함께 불러올 때 빼는 칸 — 채점 프롬프트는 제출 소스를 품어 시도마다 수십 KB 다.
#: 달성률·판정 표시는 `reasoning`·`syntax_check_result` 만 읽는다(#819: prod 클래스 상세가 시도
#: 158개의 프롬프트 4MB 를 끌어와 100~250ms 걸렸다). 프롬프트가 필요한 곳(`mcp_report_tools`)은 따로 읽는다.
_SCORE_PROMPT = ("classroom_score__prompt",)
#: 통과 판정(`Problem.is_score_passed`)에 드는 칸만 — 집계가 시도를 통째로 만들지 않게 한다(#819).
_PASS_JUDGMENT_FIELDS = (
    "problem_id",
    "member_id",
    "classroom_score__reasoning",
    "classroom_score__syntax_check_result",
    # 현재 점수(#1317)가 원래 점수에서 함께 읽는 셋 — 빼면 시도마다 지연 질의가 난다.
    "classroom_score__model_version",
    "classroom_score__unseen_files",
    "classroom_score__created_at",
)


def _mask_from_last4(last4: str) -> str:
    return f"{_KEY_MASK_PREFIX}{last4}"


def _vendor_key_out(class_obj: Class, kind: str) -> VendorKeyOut | None:
    """넣어 둔 벤더 키 하나(#1269) — 끝 네 자리와 상태만, 쓰고 있지 않은 쪽 키도 싣는다."""

    stored = class_obj.stored_vendor_key(kind)
    if stored is None:
        return None
    last4, status = stored
    return VendorKeyOut(
        masked=_mask_from_last4(last4), status=status, switchable=class_obj.vendor_key_switchable(kind)
    )


def _published_template_summary(template, *, viewer_id: int | None) -> PublishedTemplateSummaryOut | None:
    if template is None:
        return None
    return PublishedTemplateSummaryOut(
        share_code=template.share_code,
        publisher_display_name=template.publisher_display_name,
        created_at=template.created_at,
        # 내리기는 공개한 사람만 한다(`takedown_own_template`) — 다른 강사에게는 단추 대신 공개자만 보인다(#1446).
        can_take_down=viewer_id is not None and template.published_by_id == viewer_id,
    )


def _live_class_template(class_obj: Class) -> ClassTemplate | None:
    return class_obj.templates.filter(taken_down_at__isnull=True).first()


def _live_problem_template(problem: Problem) -> ProblemTemplate | None:
    return problem.templates.filter(taken_down_at__isnull=True).first()


def _serialize_class(
    class_obj: Class, *, viewer_id: int, row_stats: dict | None = None, claude_selectable: bool | None = None
) -> ClassOut:
    """`viewer_id`는 부른 사람 — 그 사람이 소유자인지 공동 강사인지(`role`)를 싣는다(#561)."""

    has_key = class_obj.has_scoring_key()
    compatible = has_key and class_obj.scoring_connection_kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER
    viewer_is_owner = is_owner(class_obj, viewer_id)
    if row_stats is None:
        row_stats = _class_row_stats([class_obj])[class_obj.id]
    return ClassOut(
        id=class_obj.id,
        name=class_obj.name,
        instructor_display_name=class_obj.instructor_display_name,
        my_instructor_display_name=instructor_display_name_of(class_obj, viewer_id),
        join_code=class_obj.join_code,
        created_at=class_obj.created_at,
        default_model=class_obj.default_model,
        default_model_is_reasoning=_sends_reasoning_effort(
            class_obj, class_obj.default_model, marked_reasoning=class_obj.default_model_marked_reasoning
        ),
        default_reasoning_effort=class_obj.default_reasoning_effort,
        has_openai_key=has_key,
        openai_key_masked=(
            _mask_from_last4(getattr(class_obj, class_obj.active_key_fields().last4))
            if has_key and not compatible
            else None
        ),
        openai_key_status=class_obj.active_key_status() if has_key else None,
        scoring_connection_kind=class_obj.scoring_connection_kind,
        openai_key=_vendor_key_out(class_obj, Class.ScoringConnectionKind.OPENAI_KEY),
        anthropic_key=_vendor_key_out(class_obj, Class.ScoringConnectionKind.ANTHROPIC_KEY),
        scoring_method=class_obj.scoring_method,
        quality_method=class_obj.quality_method,
        grading_method_options=_grading_method_options(class_obj),
        agent_models=agent_grading.agent_models(class_obj),
        oversize_policy=class_obj.oversize_policy,
        oversize_agent_model=class_obj.oversize_agent_model,
        anthropic_key_selectable=(
            privacy_policy.anthropic_key_connection_open() if claude_selectable is None else claude_selectable
        ),
        # 공동 강사는 종류와 호스트만 읽는다(#601) — 주소 전체·인증 값 마스킹은 소유자에게만.
        scoring_server_host=scoring_connection.server_host(class_obj.scoring_server_url) if compatible else None,
        scoring_server_url=class_obj.scoring_server_url if compatible and viewer_is_owner else None,
        scoring_auth_masked=(
            _mask_from_last4(class_obj.openai_api_key_last4)
            if compatible and viewer_is_owner and class_obj.openai_api_key_last4
            else None
        ),
        scoring_quota_exhausted=has_key and class_obj.scoring_quota_exhausted_at is not None,
        scoring_server_unreachable=(
            has_key and compatible and class_obj.scoring_server_unreachable_at is not None
        ),
        scoring_connection_verified_at=class_obj.scoring_connection_verified_at if has_key else None,
        archived=class_obj.archived_at is not None,
        token_usage_total=class_obj.token_usage_total,
        token_usage_estimated=class_obj.token_usage_estimated,
        has_submissions=ClassroomSubmission.objects.filter(problem__classroom=class_obj).exists(),
        published_template=_published_template_summary(_live_class_template(class_obj), viewer_id=viewer_id),
        role="owner" if viewer_is_owner else "co_instructor",
        pending_ownership_transfer=_pending_ownership_transfer_out(class_obj, viewer_id),
        signal_rev=class_obj.signal_rev,
        **row_stats,
    )


def _grading_method_options(class_obj: Class) -> list[GradingMethodOptionOut]:
    reason = agent_grading.unavailable_reason(class_obj)
    return [
        GradingMethodOptionOut(value="single", selectable=True),
        GradingMethodOptionOut(value="agent", selectable=reason is None, unavailable_reason=reason),
    ]


def _pending_ownership_transfer_out(class_obj: Class, viewer_id: int) -> PendingOwnershipTransferOut | None:
    pending = ownership_transfers.pending_for(class_obj)
    if pending is None:
        return None
    transfer, recipient_row = pending
    return PendingOwnershipTransferOut(
        id=transfer.id,
        recipient_co_instructor_id=recipient_row.id if recipient_row is not None else None,
        recipient_display_name=recipient_row.display_name if recipient_row is not None else "",
        recipient_is_me=transfer.recipient_id == viewer_id,
        requested_at=transfer.requested_at,
        expires_at=transfer.expires_at,
    )


def _serialize_checklist_item(item: ChecklistItem, *, with_rule: bool = True) -> ChecklistItemOut:
    """`with_rule=False` 는 참여자 응답이다 — 기계 확인 규칙(#1283)을 싣지 않는다."""

    return ChecklistItemOut(
        id=item.id,
        label=item.label,
        grade=item.grade,
        required=item.required,
        points=item.points,
        order=item.order,
        hidden=item.hidden,
        machine_rule=item.machine_rule if with_rule else None,
        **(_derived_fields(item) if with_rule else {}),
    )


def _derived_fields(item: ChecklistItem) -> dict[str, str | dict | None]:
    """도출(#1293) — 강사 응답에만, 읽기 전용."""

    current = rule_derivation.current_derivation(item)
    if current is None:
        return {}
    kind, rule = current
    return {"derived_kind": kind, "derived_rule": rule}


def _serialize_saved_checklist_item(item: ChecklistItem, *, text_changed: bool = True) -> ChecklistItemSavedOut:
    """방금 더하거나 고친 항목 — MCP 와 같은 `gradability_warnings()` 로 가린다(#810). 저장은 막지 않는다.
    문구를 건드리지 않은 고침(필수 켬끔)은 가리지 않는다 — 문구를 안 고쳤는데 다시 나무라지 않는다."""

    return ChecklistItemSavedOut(
        id=item.id,
        label=item.label,
        grade=item.grade,
        required=item.required,
        points=item.points,
        order=item.order,
        hidden=item.hidden,
        machine_rule=item.machine_rule,
        **_derived_fields(item),
        gradability_warnings=gradability_warnings([item]) if text_changed else [],
    )


def _active_member_ids(class_obj: Class) -> set[int]:
    """달성률의 분모를 이루는 참여자 id — 강사(지금 강사인 사람 전원)와 내보내진 사람은
    뺀다(#289, CONTEXT.md 「달성률」·「공동 강사」). 규칙은 `_active_member_ids_by_class` 하나다(#664)."""

    return _active_member_ids_by_class([class_obj.id])[class_obj.id]


def _problem_pass_stats(
    problem: Problem, active_member_ids: set[int], *, submissions=None
) -> tuple[int, int, float | None]:
    """(passed_count, member_count, pass_rate) — `_problem_stats` 에서 「완벽」만 뺀 것."""

    passed_count, _perfect_count, member_count, pass_rate = _problem_stats(
        problem, active_member_ids, submissions=submissions
    )
    return passed_count, member_count, pass_rate


def _pass_rate(passed_count: int, member_count: int, submissions) -> float | None:
    """달성률 — 참여자가 없거나 채점된 시도가 하나도 없으면 `None` 이다(#1400): 채점 대기를 0% 로
    말하지 않는다. 실패 상한의 자동 점수는 채점된 것이 아니다."""

    if not member_count:
        return None
    if not passed_count:
        scores = (current_score(submission) for submission in submissions)
        if not any(s is not None and s.model_version != PLATFORM_FAILURE_MODEL_VERSION for s in scores):
            return None
    return passed_count / member_count


def _problem_stats(
    problem: Problem, active_member_ids: set[int], *, submissions=None
) -> tuple[int, int | None, int, float | None]:
    """(passed_count, perfect_count, member_count, pass_rate) — 분모는 `active_member_ids`의 크기,
    분자는 그중 이 문제를 한 번이라도 통과한 사람 수다(#289). `perfect_count` 는 그중 한 번이라도
    「완벽」(`Problem.is_score_perfect`, #962)을 받은 사람 수이고, 심화 항목이 없는 문제는 `None` 이다.
    같은 시도 묶음을 한 번 훑어 둘을 함께 센다 — 질의는 늘지 않는다. 매번 지금의
    체크리스트 기준으로 다시 셈한다 — `Problem.is_score_passed`(#436)가
    그렇게 되어 있어 여기서는 한 번 불러온 체크리스트만 그대로 넘기면
    된다."""

    member_count = len(active_member_ids)
    checklist_items = list(problem.checklist_items.all())
    has_advanced = Problem.has_advanced_items(checklist_items)
    if not active_member_ids:
        return 0, (0 if has_advanced else None), 0, None

    if submissions is None:
        submissions = ClassroomSubmission.objects.filter(
            problem=problem, member_id__in=active_member_ids
        ).select_related("classroom_score").prefetch_related(current_score_prefetch()).defer(*_SCORE_PROMPT)

    passed_member_ids: set[int] = set()
    perfect_member_ids: set[int] = set()
    # 필수 항목이 없으면 통과할 수 있는 시도가 없다.
    has_required = any(item.required for item in checklist_items)
    for submission in submissions if has_required else ():
        if submission.member_id in passed_member_ids and (
            not has_advanced or submission.member_id in perfect_member_ids
        ):
            continue
        score = current_score(submission)
        if problem.is_score_passed(score, checklist_items=checklist_items):
            passed_member_ids.add(submission.member_id)
            if has_advanced and problem.is_score_perfect(score, checklist_items=checklist_items):
                perfect_member_ids.add(submission.member_id)

    return (
        len(passed_member_ids),
        (len(perfect_member_ids) if has_advanced else None),
        member_count,
        _pass_rate(len(passed_member_ids), member_count, submissions),
    )


# --- 집계 필드 (#632, 시안 v2) ------------------------------------------------
#
# 클래스 목록·문제 목록·격자가 한 번에 낸다 — 질의 수가 클래스·문제·멤버 수에
# 비례하지 않는다. 「누구를 세는가」는 달성률과 같다(강사 전원·내보낸 사람 제외) —
# 참여자 규칙은 `_active_member_ids_by_class` 하나이고 클래스 하나짜리 `_active_member_ids`
# 는 그것을 부른다(#664). 시도에 거는 같은 규칙(`_participant_submissions`)이 어긋나지
# 않는지는 시험(`test_classroom_aggregates`)이 지킨다.


def _participant_submissions():
    """강사 본인·내보낸 참여자의 것이 아닌 시도 — `_active_member_ids`와 같은 사람들."""

    return ClassroomSubmission.objects.filter(active_participant_q(member="member", classroom="problem__classroom"))


def _participant_submission_marks(key: str, **filters) -> dict[int, tuple[object, int]]:
    """`key` → (참여자의 마지막 시도 시각, 참여자 시도 수) — 질의 하나(#632·#674)."""

    rows = (
        _participant_submissions()
        .filter(**filters)
        .order_by()
        .values(key)
        .annotate(last=Max("created_at"), n=Count("id"))
        .values_list(key, "last", "n")
    )
    return {k: (last, n) for k, last, n in rows}


def _last_submitted_by(key: str, **filters) -> dict[int, object]:
    return {k: last for k, (last, _n) in _participant_submission_marks(key, **filters).items()}


def _active_member_ids_by_class(class_ids: list[int]) -> dict[int, set[int]]:
    """클래스 id → 참여 중인 참여자 id(강사 전원·내보낸 사람 제외) — 질의 하나. 클래스 행의
    `member_count` 와 가입 미리보기의 `member_count`(#659·#664)가 이것을 센다."""

    active_ids: dict[int, set[int]] = {cid: set() for cid in class_ids}
    for member_id, classroom_id in (
        ClassMember.objects.filter(active_participant_q(classroom="classroom"), classroom_id__in=class_ids)
        .order_by()
        .values_list("id", "classroom_id")
    ):
        active_ids[classroom_id].add(member_id)
    return active_ids


def _class_row_stats(classes: list[Class]) -> dict[int, dict]:
    """클래스 행 수치 — 클래스 수와 무관하게 질의 여섯 개."""

    class_ids = [c.id for c in classes]
    active_ids = _active_member_ids_by_class(class_ids)

    problems_by_class: dict[int, list[Problem]] = {cid: [] for cid in class_ids}
    for problem in Problem.objects.filter(classroom_id__in=class_ids).prefetch_related("checklist_items"):
        problems_by_class[problem.classroom_id].append(problem)

    submissions_by_problem: dict[int, list[ClassroomSubmission]] = {}
    for submission in (
        _participant_submissions()
        .filter(problem__classroom_id__in=class_ids, problem__status=Problem.Status.OPEN)
        .select_related("classroom_score").prefetch_related(current_score_prefetch())
        # 달성률은 누가 어느 문제에서 어떤 판정을 받았나만 본다(#819) — 부모 행·프롬프트·정렬은 필요 없다.
        .only(*_PASS_JUDGMENT_FIELDS)
        .order_by()
    ):
        submissions_by_problem.setdefault(submission.problem_id, []).append(submission)

    last_by_class = _last_submitted_by("problem__classroom_id", problem__classroom_id__in=class_ids)
    scored_by_class = dict(
        ClassroomScore.objects.filter(submission__problem__classroom_id__in=class_ids)
        .order_by()
        .values("submission__problem__classroom_id")
        .annotate(n=Count("id"))
        .values_list("submission__problem__classroom_id", "n")
    )

    stats: dict[int, dict] = {}
    for cid in class_ids:
        rates: list[float | None] = []
        for problem in problems_by_class[cid]:
            if problem.status != Problem.Status.OPEN:
                continue
            _passed_count, member_count, pass_rate = _problem_pass_stats(
                problem, active_ids[cid], submissions=submissions_by_problem.get(problem.id, [])
            )
            if member_count:
                rates.append(pass_rate)
        # 열린 문제 전부에 채점된 시도가 없으면 평균도 비운다. 하나라도 있으면 나머지는
        # 아직 아무도 못 푼 몫(0)으로 센다(#1400).
        graded = any(rate is not None for rate in rates)
        stats[cid] = {
            "member_count": len(active_ids[cid]),
            "problem_count": len(problems_by_class[cid]),
            "average_pass_rate": (sum(rate or 0 for rate in rates) / len(rates)) if graded else None,
            "last_submitted_at": last_by_class.get(cid),
            "scored_attempt_count": scored_by_class.get(cid, 0),
        }
    return stats


def _joined_progress(memberships: list[ClassMember]) -> dict[int, tuple[int, int]]:
    """멤버십 id → (내가 통과한 열린 문제 수, 열린 문제 수) — 질의 셋."""

    class_ids = {m.classroom_id for m in memberships}
    open_problems: dict[int, list[Problem]] = {cid: [] for cid in class_ids}
    for problem in Problem.objects.filter(
        classroom_id__in=class_ids, status=Problem.Status.OPEN
    ).prefetch_related("checklist_items"):
        open_problems[problem.classroom_id].append(problem)
    problems_by_id = {p.id: p for plist in open_problems.values() for p in plist}

    passed_by_member: dict[int, set[int]] = {}
    for submission in ClassroomSubmission.objects.filter(
        member_id__in=[m.id for m in memberships], problem_id__in=problems_by_id
    ).select_related("classroom_score").prefetch_related(current_score_prefetch()).defer(*_SCORE_PROMPT):
        problem = problems_by_id[submission.problem_id]
        if problem.is_score_passed(current_score(submission)):
            passed_by_member.setdefault(submission.member_id, set()).add(submission.problem_id)

    return {
        m.id: (len(passed_by_member.get(m.id, set())), len(open_problems[m.classroom_id]))
        for m in memberships
    }


def _problem_ids_blocking_deletion(class_obj: Class) -> set[int]:
    """지금 강사인 사람이 아닌 누군가의 시도가 하나라도 달린 문제 id 집합(#431,
    ADR-0050 — ADR-0055 대로 떠난 공동 강사의 시도는 내보낸 참여자의 것이라 막는다)
    — **내보낸 참여자의 시도도 포함한다**(`member__expelled_at`을
    보지 않는다, ADR-0050의 경계: 내보내면 지울 수 있게 되는 우회를 막는다).
    목록 화면(`list_problems`/`reorder_problems`)이 문제마다 따로 질의하지
    않도록 클래스 전체를 한 번에 묻는다 — `_active_member_ids`와 같은 배치
    관용구다."""

    return set(
        ClassroomSubmission.objects.filter(problem__classroom=class_obj)
        .exclude(member__user_id__in=instructor_user_ids(class_obj))
        .values_list("problem_id", flat=True)
    )


def _problem_deletable(
    problem: Problem, class_obj: Class, *, blocking_problem_ids: set[int] | None = None
) -> bool:
    """이 문제를 지금 지울 수 있는가(#430/#431, ADR-0050) — 강사 자신이 아닌
    누군가의 시도가 하나도 없을 때 참이다.

    강사 판정은 `member__user_id ∈ instructor_user_ids(class_obj)`로 한다 — 「그
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
        .exclude(member__user_id__in=instructor_user_ids(class_obj))
        .exists()
    )


def _serialize_problem(
    problem: Problem,
    class_obj: Class,
    *,
    active_member_ids: set[int] | None = None,
    blocking_problem_ids: set[int] | None = None,
    submission_marks_by_problem: dict[int, tuple[object, int]] | None = None,
    submissions_by_problem: dict[int, list[ClassroomSubmission]] | None = None,
    live_template_by_problem: dict[int, ProblemTemplate] | None = None,
    viewer_id: int | None = None,
) -> ProblemOut:
    if submission_marks_by_problem is None:
        submission_marks_by_problem = _participant_submission_marks("problem_id", problem_id=problem.id)
    last_submitted_at, participant_attempt_count = submission_marks_by_problem.get(problem.id, (None, 0))
    if active_member_ids is None:
        active_member_ids = _active_member_ids(class_obj)
    passed_count, perfect_count, member_count, pass_rate = _problem_stats(
        problem,
        active_member_ids,
        submissions=None if submissions_by_problem is None else submissions_by_problem.get(problem.id, []),
    )
    live_template = (
        _live_problem_template(problem)
        if live_template_by_problem is None
        else live_template_by_problem.get(problem.id)
    )
    effective_model = problem.effective_model()
    effective_reasoning_effort = problem.effective_reasoning_effort()
    checklist_items = list(problem.checklist_items.all())
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
        effective_model_is_reasoning=_sends_reasoning_effort(
            class_obj, effective_model, marked_reasoning=problem.effective_model_marked_reasoning()
        ),
        model_is_reasoning=problem.model_marked_reasoning,
        reasoning_effort=problem.reasoning_effort,
        effective_reasoning_effort=effective_reasoning_effort,
        scoring_model_rejected=problem.scoring_model_rejected_at is not None,
        grading_strictness=problem.grading_strictness,
        grading_guideline_text=problem.grading_guideline_text,
        syntax_check_enabled=problem.syntax_check_enabled,
        quality_public=problem.quality_public,
        checklist_items=[_serialize_checklist_item(i) for i in checklist_items],
        passed_count=passed_count,
        member_count=member_count,
        pass_rate=pass_rate,
        perfect_count=perfect_count,
        published_template=_published_template_summary(live_template, viewer_id=viewer_id),
        deletable=_problem_deletable(problem, class_obj, blocking_problem_ids=blocking_problem_ids),
        available_transitions=[
            ProblemTransitionOut(name=t.name, to_state=t.to_state, blocked_reason=t.blocked_reason)
            for t in available_transitions(problem, class_obj)
        ],
        contest=_contest_out(problem),
        instructor_note=problem.instructor_note,
        last_submitted_at=last_submitted_at,
        participant_attempt_count=participant_attempt_count,
        zip_git_history_warning=_zip_git_history_warning(problem, checklist_items),
        recommended_due_at=problem.recommended_due_at,
        due_at=problem.due_at,
    )


def _zip_git_history_warning(problem: Problem, checklist_items: list) -> ZipGitHistoryWarningOut | None:
    item_ids = zip_git_history_item_ids(problem.submission_formats, checklist_items)
    return ZipGitHistoryWarningOut(checklist_item_ids=item_ids) if item_ids else None


def _contest_out(problem: Problem) -> ProblemContestOut | None:
    state = contest_state(problem)
    return ProblemContestOut(**state) if state is not None else None


def _attempt_perfect(problem: Problem, score, checklist_items) -> bool | None:
    """시도 하나의 「완벽」(#962) — 심화 항목이 없는 문제는 `None`(완벽이 없다)."""

    if not Problem.has_advanced_items(checklist_items):
        return None
    return problem.is_score_perfect(score, checklist_items=checklist_items)


def _perfect_ever(submissions, problem: Problem, checklist_items) -> bool | None:
    """시도 전체에 대한 OR — 어느 시도든 한 번 완벽이면 문제는 완벽이다(#962, 대표 결정 3)."""

    if not Problem.has_advanced_items(checklist_items):
        return None
    return any(
        problem.is_score_perfect(current_score(s), checklist_items=checklist_items)
        for s in submissions
    )


def _serialized_perfect(serialized_submissions, checklist_items) -> bool | None:
    """이미 직렬화한 시도들(`ClassroomSubmissionOut`)에서 문제의 「완벽」 OR — 다시 세지 않는다."""

    if not Problem.has_advanced_items(checklist_items):
        return None
    return any(s.perfect for s in serialized_submissions)


def _serialize_problem_mine(
    problem: Problem, *, passed: bool = False, perfect: bool | None = None
) -> ClassroomProblemMineOut:
    checklist_items = list(problem.checklist_items.all())
    return ClassroomProblemMineOut(
        id=problem.id,
        classroom_id=problem.classroom_id,
        title=problem.title,
        description=problem.description,
        submission_formats=problem.submission_formats,
        contest=_contest_out(problem),
        instructor_note=problem.instructor_note,
        grading_strictness=problem.grading_strictness,
        grading_guideline_text=problem.grading_guideline_text,
        syntax_check_enabled=problem.syntax_check_enabled,
        # 숨은 항목(#906)은 참여자(「참여자로 보기」의 강사 포함)에게 내용 없이 개수만.
        checklist_items=[_serialize_checklist_item(i, with_rule=False) for i in checklist_items if not i.hidden],
        hidden_checklist_item_count=sum(1 for i in checklist_items if i.hidden),
        passed=passed,
        perfect=perfect,
        zip_git_history_warning=_zip_git_history_warning(problem, checklist_items),
        recommended_due_at=problem.recommended_due_at,
        due_at=problem.due_at,
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


def _staged_verdict_fields(entry: Mapping[str, object]) -> dict[str, object]:
    """저장된 staged 판정 항목(#1283·#1284)의 출처·근거 인용·기계 근거·의심. single_call 항목에는 없어 빈 dict."""

    fields: dict[str, object] = {}
    for key in STAGED_VERDICT_KEYS:
        if key in entry:
            fields[key] = entry[key]
    return fields


def _serialize_score(
    score: CurrentClassroomScore, *, hidden_items: Mapping[int, str] | None = None
) -> ClassroomScoreOut:
    """`hidden_items`(숨은 항목 id → 등급)를 주면 참여자 응답이다(#906) — 그 항목의 근거를 빼고 개수·충족 수만 남긴다."""

    hidden = hidden_items or {}
    judged = {item_id for item_id, grade in hidden.items() if grade != ChecklistGrade.BONUS}
    return ClassroomScoreOut(
        model_version=score.model_version,
        is_platform_failure=score.model_version == PLATFORM_FAILURE_MODEL_VERSION,
        reasoning=[
            ClassroomChecklistVerdictOut(
                checklist_item_id=r["checklist_item_id"],
                is_met=r["is_met"],
                verdict=verdict_of(r),
                reasoning=r["reasoning"],
                # staged 의 출처·근거·의심(#1284)은 강사 응답에만 — 참여자 응답은 예전 그대로다.
                **(_staged_verdict_fields(r) if hidden_items is None else {}),
            )
            for r in score.reasoning
            if r["checklist_item_id"] not in hidden
        ],
        syntax_check=_serialize_syntax_check(score.syntax_check_result),
        created_at=score.created_at,
        reused=hidden_items is None and not score.corrected and score_reused(score.original),
        corrected=score.corrected,
        unseen_files=score.unseen_files,
        hidden_summary=(
            None
            if hidden_items is None
            else ClassroomHiddenSummaryOut(
                total=len(judged),
                met=sum(1 for r in score.reasoning if r["checklist_item_id"] in judged and r["is_met"] is True),
            )
        ),
    )


def _hidden_items_of(checklist_items) -> dict[int, str]:
    """체크리스트의 숨은 항목 id → 등급(#906)."""

    return {i.id: i.grade for i in checklist_items if i.hidden}


def _pending_reason(score, class_obj: Class, problem: Problem, submission=None) -> str | None:
    """아직 채점되지 않은 시도가 왜 멈춰 있는지(#346, #355, #403, #434) —
    참여자·강사 화면 모두 이 값 하나를 읽어 다르게 그린다.
    `classroom.pending_scoring.pending_reason`에 그대로 맡긴다 — 스캔 후보
    (`scoring.pending_submissions`)가 거르는 것과 **같은 기준**이어야 한다는
    불변식이 이제 그 모듈 하나에 산다. 둘이 겹치면 키(없음·거부) → 모델
    거부 순서로 하나만 말한다. **키가 거부된 것과 아예 없는
    것, 그리고 모델이 거부된 것을 참여자 화면에서는 구별하지 않는다**
    (#355 AC, #403 AC "참여자에게는 기존 「채점하지 못함」 안내를 보인다")
    — 강사의 계정·설정 문제가 참여자에게 새어 나가지 않는다, 강사 전용
    화면(설정·시도 목록·클래스 상세 배너)만 다르게 말한다."""

    # 반려(#1311)는 시도마다다 — 질의가 `pending_scoring.with_rejection` 으로 단 값을 읽는다.
    return pending_scoring.pending_reason(score, class_obj, problem, rejected=_rejection_of(submission) is not None)


def _rejection_of(submission) -> SubmissionRejectionOut | None:
    """반려된 시도의 사유(#1311) — `with_rejection` 이 단 `rejection_error` 를 읽는다. 채점된 시도는 늘 `None`."""

    if submission is None or current_score(submission) is not None:
        return None
    parsed = pending_scoring.parse_rejection(getattr(submission, "rejection_error", None))
    return None if parsed is None else SubmissionRejectionOut(source_chars=parsed[0], limit_chars=parsed[1])


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
    score = current_score(submission)
    pending_reason = _pending_reason(score, class_obj, problem, submission)
    if checklist_items is None:
        checklist_items = list(problem.checklist_items.all())
    # 참여자(그리고 「참여자로 보기」의 강사) 응답 — 숨은 항목은 근거 없이 개수·충족 수만(#906).
    hidden_items = _hidden_items_of(checklist_items)
    return ClassroomSubmissionOut(
        id=submission.id,
        problem_id=submission.problem_id,
        attempt_number=submission.attempt_number,
        submission_format=asset.kind,
        value=asset.submitted_url,
        commit_sha=asset.repository_commit_sha or None,
        download_url=download_url,
        created_at=submission.created_at,
        status="scored" if score is not None else "pending",
        score=_serialize_score(score, hidden_items=hidden_items) if score is not None else None,
        passed=problem.is_score_passed(score, checklist_items=checklist_items),
        perfect=_attempt_perfect(problem, score, checklist_items),
        pending_reason=pending_reason,
        rejection=_rejection_of(submission),
        contest_entry=contest_entry_out(submission),
        late=problem.lateness(submission.created_at),
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
    marks: EntryMarks | None = None,
) -> ClassroomInstructorSubmissionOut:
    download_url = (
        _instructor_source_download_url(
            asset, member=submission.member, attempt_number=submission.attempt_number
        )
        if asset.kind == SubmissionAsset.Kind.SOURCE
        else None
    )
    score = current_score(submission)
    return ClassroomInstructorSubmissionOut(
        id=submission.id,
        problem_id=submission.problem_id,
        member_id=submission.member_id,
        member_display_name=submission.member.display_name,
        attempt_number=submission.attempt_number,
        submission_format=asset.kind,
        value=asset.submitted_url,
        commit_sha=asset.repository_commit_sha or None,
        download_url=download_url,
        created_at=submission.created_at,
        status="scored" if score is not None else "pending",
        score=_serialize_score(score) if score is not None else None,
        passed=problem.is_score_passed(score, checklist_items=checklist_items),
        perfect=_attempt_perfect(problem, score, checklist_items),
        pending_reason=_pending_reason(score, class_obj, problem, submission),
        rejection=_rejection_of(submission),
        contest_entry=contest_entry_out(submission),
        is_current_contest_entry=marks is not None and submission.id in marks.current,
        late=problem.lateness(submission.created_at),
    )


# --- Class -------------------------------------------------------------------


@router.post("/classes", response={201: ClassOut, 422: ErrorOut}, auth=jwt_auth)
def create_class(request: HttpRequest, payload: ClassIn):
    # 범위 밖이다 — 아직 없는 자원에는 열 문이 없다(`instructor_scope`의
    # class_scope/problem_scope는 이미 있는 클래스를 여는 문이다). 금칙어 검사는
    # `class_authoring.create_class`가 한다(연결된 앱과 한 벌, #516).
    class_obj = class_authoring.create_class(request.auth_user.id, payload)
    return 201, _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.get("/classes", response={200: list[ClassOut]}, auth=jwt_auth)
def list_my_classes(request: HttpRequest):
    """「내 클래스」— 본인이 강사인 것만. 남의 클래스는 여기 나오지 않는다."""

    classes = list(instructor_classes(request.auth_user.id))
    row_stats = _class_row_stats(classes)
    # 시계(DB 한 번)는 목록에서 한 번만 읽는다 — 클래스 수만큼 늘지 않게.
    selectable = privacy_policy.anthropic_key_connection_open()
    return 200, [
        _serialize_class(c, viewer_id=request.auth_user.id, row_stats=row_stats[c.id], claude_selectable=selectable)
        for c in classes
    ]


@router.get("/classes/joined", response={200: list[JoinedClassOut]}, auth=jwt_auth)
def list_joined_classes(request: HttpRequest):
    """「내 클래스」— 본인이 참여자로 들어간 것만(#328). 본인이 강사인
    클래스는 강사 본인도 `ClassMember` 행을 가질 수 있지만(models.py
    `ClassMember` docstring) 여기서는 뺀다 — 그 클래스는 이미
    `list_my_classes`가 「연 것」으로 보여주므로, 여기까지 포함하면 첫
    화면에 같은 클래스가 두 자리에 겹쳐 나온다."""

    memberships = (
        ClassMember.objects.filter(user_id=request.auth_user.id)
        .exclude(classroom__in=classes_taught_by(request.auth_user.id))
        .select_related("classroom")
        .order_by("-joined_at")
    )
    memberships = list(memberships)
    progress = _joined_progress(memberships)
    left_ids = left_member_ids(memberships)
    return 200, [
        JoinedClassOut(
            id=m.classroom.id,
            name=m.classroom.name,
            instructor_display_name=m.classroom.instructor_display_name,
            joined_at=m.joined_at,
            archived=m.classroom.archived_at is not None,
            expelled=m.expelled_at is not None,
            left=m.id in left_ids,
            passed_count=progress[m.id][0],
            open_problem_count=progress[m.id][1],
        )
        for m in memberships
    ]


@router.get("/classes/former-instructor", response={200: list[FormerClassOut]}, auth=jwt_auth)
def list_former_instructor_classes(request: HttpRequest):
    """한때 이 사람이 강사(공동 강사·넘겨준 소유자)였다가 지금은 아닌 클래스(#1465 2). 증거는 **그 사람이 수락한
    초대**와 **그 사람이 오간 수락된 소유권 이전**뿐이다 — 초대를 받기만 했거나 처음부터 관계 없던 사람은 빈 목록이라
    남의 클래스의 존재가 새지 않는다(#278). 지금도 강사인 클래스는 뺀다."""

    user_id = request.auth_user.id
    touched = (
        set(
            CoInstructorInvite.objects.filter(accepted_by_id=user_id, accepted_at__isnull=False).values_list(
                "classroom_id", flat=True
            )
        )
        | set(
            OwnershipTransfer.objects.filter(accepted_at__isnull=False, requested_by_id=user_id).values_list(
                "classroom_id", flat=True
            )
        )
        | set(
            OwnershipTransfer.objects.filter(accepted_at__isnull=False, recipient_id=user_id).values_list(
                "classroom_id", flat=True
            )
        )
    )
    taught = set(classes_taught_by(user_id).values_list("id", flat=True))
    return 200, [FormerClassOut(id=class_id) for class_id in sorted(touched - taught)]


@router.get("/classes/{class_id}", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def get_class(request: HttpRequest, class_id: int):
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.patch(
    "/classes/{class_id}",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def update_class(request: HttpRequest, class_id: int, payload: ClassPatchIn):
    # 클래스 설정은 보관 뒤에도 고칠 수 있다(`classroom.participation`
    # 모듈 docstring 「열어 두는 것」) — write=False, 소유권·존재만 본다.
    scope = class_scope(class_id, request.auth_user.id, write=False, owner=False)
    if class_authoring.touches_owner_only_fields(payload):
        # 강사 이름 칸은 소유자의 이름이다(#561) —
        # 클래스 이름·모델 같은 나머지 칸은 강사 누구나.
        scope.require_owner()
    class_obj = scope.class_obj
    class_authoring.update_class(class_obj, payload)
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.put(
    "/classes/{class_id}/openai-key",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
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

    # 클래스 설정과 같은 이유로 보관 뒤에도 키는 고칠 수 있다(`update_class`
    # 와 같은 판단, `classroom.participation` 「열어 두는 것」). 키는 소유자의 비용이라
    # 소유자 전용이다(ADR-0055).
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    return 200, _save_vendor_key(request, class_obj, payload.api_key, kind=Class.ScoringConnectionKind.OPENAI_KEY)


@router.put(
    "/classes/{class_id}/anthropic-key",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def set_class_anthropic_key(request: HttpRequest, class_id: int, payload: OpenAIKeyIn):
    """채점 연결을 「Claude(Anthropic) 키」로 저장한다(#795, ADR-0066) — OpenAI 키 저장과 같은 규율:
    소유자 전용(ADR-0055), 암호화 저장·끝 네 자리, 저장 전 `GET /v1/models` 로 한 번 확인(401·403 만
    거절, 닿지 못하면 「미검증」으로 저장, #681). 이전 연결(OpenAI 키·호환 서버)의 값은 덮여 지워진다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    return 200, _save_vendor_key(request, class_obj, payload.api_key, kind=Class.ScoringConnectionKind.ANTHROPIC_KEY)


#: 연결 종류별 새 기본 모델 — 지금 기본 모델을 그 연결이 받지 않을 때만 바꾼다(#795).
_DEFAULT_MODEL_FOR_KIND = {
    Class.ScoringConnectionKind.OPENAI_KEY: DEFAULT_SCORING_MODEL,
    Class.ScoringConnectionKind.ANTHROPIC_KEY: DEFAULT_ANTHROPIC_SCORING_MODEL,
}


def _save_vendor_key(request: HttpRequest, class_obj: Class, api_key: str, *, kind: str) -> ClassOut:
    # 방침 개정 시행일 전에는 Claude 키 연결을 저장할 수 없다(#803) — 제출 소스가 고지 없이 국외로 나가지 않게.
    if kind == Class.ScoringConnectionKind.ANTHROPIC_KEY and not privacy_policy.anthropic_key_connection_open():
        raise HttpError(
            422, f"Claude(Anthropic) 키 연결은 {privacy_policy.anthropic_key_connection_opens_label()}부터 쓸 수 있습니다."
        )
    raw_key = api_key.strip()
    if not raw_key:
        raise HttpError(422, "채점 키를 입력해주세요.")

    check_result = check_scoring_key(api_key=raw_key, kind=kind)
    if check_result == LLMKeyCheckStatus.REJECTED:
        raise HttpError(422, "이 채점 키를 벤더가 거절했습니다 — 키를 다시 확인해 저장해주세요.")

    # 두 키는 따로 산다(#1269). 저장한 키로 채점이 넘어가는 것은 그 벤더가 이미 고른 쪽이거나, 지금 연결로는
    # 채점할 수 없을 때(키 없음·거부됨)뿐이다 — 쉬는 쪽 키를 바꿔 넣는다고 스위치가 넘어가 기본 모델·문제별
    # 모델이 바뀌지 않게. 호환 서버 연결 동안 OpenAI 키를 저장하면 같은 칸을 덮으므로(#601) OpenAI 로 넘어간다.
    current_kind = class_obj.scoring_connection_kind
    selects = (
        current_kind == kind
        or class_obj.scoring_key_unusable(ignore_pause=True)
        or (
            kind == Class.ScoringConnectionKind.OPENAI_KEY
            and current_kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER
        )
    )
    fields = key_fields_for(kind)
    setattr(class_obj, fields.encrypted, encrypt(raw_key))
    setattr(class_obj, fields.last4, raw_key[-4:])
    setattr(
        class_obj,
        fields.status,
        Class.ScoringKeyStatus.VERIFIED if check_result == LLMKeyCheckStatus.VALID else Class.ScoringKeyStatus.UNVERIFIED,
    )
    if not selects:
        _save_scoring_connection(request, class_obj, connection_changed=False)
        return _serialize_class(class_obj, viewer_id=request.auth_user.id)
    # 벤더가 키를 받았을 때만 「확인」이다(#671) — 닿지 못해 미검증으로 저장한 키는 아직 확인된 적
    # 없는 새 연결이라 옛 연결의 확인 시각을 물려받지 않는다.
    class_obj.scoring_connection_verified_at = Clock.now() if check_result == LLMKeyCheckStatus.VALID else None
    # 크레딧이 바닥나 멈춰 있었다면(#586) 다시 저장하는 것이 「충전했다」는 신호다 — 키 확인은
    # 크레딧을 보지 않으므로(`/v1/models`) 여기서 풀고, 다음 tick 의 채점이 실제로 확인한다.
    # 아직 바닥이면 그 채점이 다시 멈추고 다시 알린다.
    class_obj.scoring_quota_exhausted_at = None
    class_obj.scoring_server_unreachable_at = None
    # 키를 저장하면 연결이 그 종류로 바뀌고 호환 서버 주소는 지운다(#601, #795).
    class_obj.scoring_connection_kind = kind
    class_obj.scoring_server_url = ""
    # 벤더가 OpenAI ↔ Claude 로 바뀌면 지금 기본 모델은 새 키로 쓸 수 없다 — 그 연결의 기본 모델로
    # 옮긴다(#795). 호환 서버에서 오는 이름은 어느 벤더 것인지 알 수 없어 그대로 둔다(예전과 같다).
    extra = {}
    if is_claude_model_id(class_obj.default_model) != (kind == Class.ScoringConnectionKind.ANTHROPIC_KEY):
        class_obj.default_model = _DEFAULT_MODEL_FOR_KIND[kind]
        extra["default_model"] = class_obj.default_model
    # 벤더 확인을 기다리는 사이 소유권이 넘어갔을 수 있다(#564) — 넘긴 사람의 키가 새 소유자의
    # 클래스에 남지 않게, 저장은 「지금도 부른 사람이 소유자인가」를 조건으로 한 번에 한다.
    _save_scoring_connection(request, class_obj, vendor_kind=kind, **extra)
    return _serialize_class(class_obj, viewer_id=request.auth_user.id)


def _return_foreign_problem_models_to_default(class_obj: Class, kind: str) -> None:
    """문제마다 따로 고른 모델 중 새 연결이 받지 않는 벤더의 것은 클래스 기본으로 되돌린다(#796) —
    그대로 두면 채점 때 「알 수 없는 채점 모델」로 영구 실패한다. 모델을 바꾼 것과 같게 그 문제의
    「모델 거부」 표지도 푼다. 호환 서버는 모델 이름을 거르지 않아 이 함수를 부르지 않는다."""

    want_claude = kind == Class.ScoringConnectionKind.ANTHROPIC_KEY
    stale = [
        problem_id
        for problem_id, model in class_obj.problems.exclude(model="").values_list("id", "model")
        if is_claude_model_id(model) != want_claude
    ]
    if stale:
        Problem.objects.filter(id__in=stale).update(
            model="", model_marked_reasoning=False, scoring_model_rejected_at=None
        )


def _save_scoring_connection(
    request: HttpRequest,
    class_obj: Class,
    *,
    vendor_kind: str | None = None,
    connection_changed: bool = True,
    **extra: object,
) -> None:
    """`extra` 는 연결과 함께 바뀌는 다른 칸(벤더가 바뀌어 옮긴 기본 모델) — 바뀐 칸만 싣는다(다른 강사가
    그사이 고친 값을 덮지 않게). `connection_changed` 가 거짓이면(쉬는 쪽 키만 바꿔 넣음, #1269) 지금 연결의
    멈춤·확인 시각은 건드리지 않는다."""

    if connection_changed:
        # 호환 서버에 닿지 않아 멈춰 있었다면(#603) 다시 저장이 「고쳤다」는 신호다 — 저장 전
        # 확인이 이미 그 서버에 닿았다.
        extra.update(
            scoring_quota_exhausted_at=None,
            scoring_server_unreachable_at=None,
            scoring_connection_verified_at=class_obj.scoring_connection_verified_at,
        )
    key_columns = {
        name: getattr(class_obj, name)
        for fields in (OPENAI_KEY_FIELDS, ANTHROPIC_KEY_FIELDS)
        for name in (fields.encrypted, fields.last4, fields.status)
    }
    with transaction.atomic():
        saved = classes_owned_by(request.auth_user.id).filter(id=class_obj.id).update(
            scoring_connection_kind=class_obj.scoring_connection_kind,
            scoring_server_url=class_obj.scoring_server_url,
            **key_columns,
            **extra,
        )
        if not saved:
            raise HttpError(403, OWNER_ONLY_MESSAGE)
        if connection_changed:
            # 연결이 바뀌었다 — 열린 「연결 없음」 기록을 닫아, 다시 멈추면 다시 알린다(#1389). 위 UPDATE 가 이미
            # `Class` 행을 잠갔다(`classroom.scoring_key_missing` 의 잠금 규칙 ②).
            close_open_alert(class_obj.id, ClassScoringKeyMissingAlert.ClosedReason.OWNER)
        if vendor_kind is not None:
            _return_foreign_problem_models_to_default(class_obj, vendor_kind)


_VENDOR_KEY_LABELS = {
    Class.ScoringConnectionKind.OPENAI_KEY: "OpenAI 키",
    Class.ScoringConnectionKind.ANTHROPIC_KEY: "Claude(Anthropic) 키",
}


@router.put(
    "/classes/{class_id}/scoring-vendor",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def set_class_scoring_vendor(request: HttpRequest, class_id: int, payload: ScoringVendorIn):
    """채점 벤더 스위치(#1269) — 넣어 둔 OpenAI·Claude 키 가운데 어느 쪽으로 채점할지 고른다. 소유자 전용
    (ADR-0055). 키가 없거나 거부된 쪽으로는 넘어가지 않는다(422). 벤더에 묻지 않는다 — 키는 저장할 때 확인했다.

    넘어가면 키를 저장해 벤더가 바뀔 때(#795·#796)와 같다: 기본 모델이 그 벤더 것이 아니면 그 벤더의 기본
    모델로 옮기고, 문제별로 고른 다른 벤더 모델은 클래스 기본으로 되돌린다. 점수가 있는 제출은 다시 채점하지
    않는다(채점 대기는 점수 없는 제출만 집는다 — `classroom.pending_scoring`)."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    kind = payload.kind
    current_kind = class_obj.scoring_connection_kind
    if kind == current_kind:
        return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)
    if kind == Class.ScoringConnectionKind.ANTHROPIC_KEY and not privacy_policy.anthropic_key_connection_open():
        raise HttpError(
            422, f"Claude(Anthropic) 키 연결은 {privacy_policy.anthropic_key_connection_opens_label()}부터 쓸 수 있습니다."
        )
    if not class_obj.vendor_key_switchable(kind):
        raise HttpError(422, f"넣어 둔 {_VENDOR_KEY_LABELS[kind]}가 없거나 벤더가 거절한 키입니다 — 키를 먼저 저장해주세요.")

    class_obj.scoring_connection_kind = kind
    if current_kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        # 호환 서버의 주소·인증 값(OpenAI 키 칸)은 키 저장 때처럼 지운다(#601) — 남기면 OpenAI 키로 읽힌다.
        class_obj.scoring_server_url = ""
        class_obj.openai_api_key_encrypted = ""
        class_obj.openai_api_key_last4 = ""
        class_obj.openai_api_key_status = Class.ScoringKeyStatus.UNVERIFIED
    # 다른 키로 넘어갔으니 옛 연결의 확인 시각·크레딧 멈춤은 물려받지 않는다(#671, #586).
    class_obj.scoring_quota_exhausted_at = None
    class_obj.scoring_server_unreachable_at = None
    class_obj.scoring_connection_verified_at = None
    extra = {}
    if is_claude_model_id(class_obj.default_model) != (kind == Class.ScoringConnectionKind.ANTHROPIC_KEY):
        class_obj.default_model = _DEFAULT_MODEL_FOR_KIND[kind]
        extra["default_model"] = class_obj.default_model
    _save_scoring_connection(request, class_obj, vendor_kind=kind, **extra)
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


def _delete_vendor_key(request: HttpRequest, class_obj: Class, kind: str) -> ClassOut:
    """넣어 둔 벤더 키 하나를 지운다(#1269). 지금 채점하는 쪽 키를 지우면 그 클래스는 키 없음이 된다(다른 쪽
    키로 저절로 넘어가지 않는다 — 넘기는 것은 스위치다). 호환 서버 연결 동안 OpenAI 칸은 서버의 인증 값이라
    OpenAI 키 지우기는 아무것도 하지 않는다."""

    if class_obj.stored_vendor_key(kind) is None:
        return _serialize_class(class_obj, viewer_id=request.auth_user.id)
    fields = key_fields_for(kind)
    setattr(class_obj, fields.encrypted, "")
    setattr(class_obj, fields.last4, "")
    setattr(class_obj, fields.status, Class.ScoringKeyStatus.UNVERIFIED)
    active = class_obj.scoring_connection_kind == kind
    if active:
        class_obj.scoring_connection_verified_at = None
        class_obj.scoring_quota_exhausted_at = None
        class_obj.scoring_server_unreachable_at = None
    _save_scoring_connection(request, class_obj, connection_changed=active)
    return _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.delete(
    "/classes/{class_id}/openai-key",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def delete_class_openai_key(request: HttpRequest, class_id: int):
    # 키 저장과 같다 — 보관 뒤에도 열어 두고, 소유자 전용이다(ADR-0055).
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    return 200, _delete_vendor_key(request, class_obj, Class.ScoringConnectionKind.OPENAI_KEY)


@router.delete(
    "/classes/{class_id}/anthropic-key",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def delete_class_anthropic_key(request: HttpRequest, class_id: int):
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    return 200, _delete_vendor_key(request, class_obj, Class.ScoringConnectionKind.ANTHROPIC_KEY)


@router.put(
    "/classes/{class_id}/compatible-server",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def set_class_compatible_server(request: HttpRequest, class_id: int, payload: CompatibleServerIn):
    """채점 연결을 「호환 서버」로 저장한다(#601, ADR-0058) — 소유자 전용(ADR-0055).

    저장 전에 안전한 바깥 호출로 그 서버의 모델 목록을 한 번 받아 닿는지·인증이 맞는지 본다.
    거부·실패는 이유별 한 문장으로 422 이고, DB 의 기존 연결은 그대로 남는다. 인증 값은 OpenAI
    키와 같은 칸에 암호화해 두고 끝 네 자리만 보인다 — 넣어 둔 OpenAI 키는 덮여 지워지고, Claude 키
    (#1269)는 따로 살아 남는다. 응답 어디에도 인증 값 원문을 싣지 않는다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj

    server_url = scoring_connection.normalize_server_url(payload.server_url)
    auth_value = payload.auth_value.strip()
    try:
        model_ids = scoring_connection.probe_compatible_server(server_url, auth_value)
    except scoring_connection.CompatibleServerRefused as exc:
        raise HttpError(422, exc.message) from None

    class_obj.scoring_connection_kind = Class.ScoringConnectionKind.COMPATIBLE_SERVER
    class_obj.scoring_server_url = server_url
    class_obj.openai_api_key_encrypted = encrypt(auth_value) if auth_value else ""
    class_obj.openai_api_key_last4 = auth_value[-4:] if auth_value else ""
    class_obj.openai_api_key_status = Class.ScoringKeyStatus.VERIFIED
    class_obj.scoring_quota_exhausted_at = None
    class_obj.scoring_server_unreachable_at = None
    # 저장 전 확인(모델 목록·인증)을 서버가 받아들였다(#671).
    class_obj.scoring_connection_verified_at = Clock.now()
    _save_scoring_connection(request, class_obj)

    connection = scoring_connection.connection_for(class_obj)
    if connection is not None:
        remember_model_ids(connection, model_ids)
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.post("/classes/{class_id}/copy", response={201: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def copy_class_view(request: HttpRequest, class_id: int):
    """지난 기수로 다음 기수를 연다(#293) — 문제·체크리스트·채점 설정이
    순서 그대로 따라오고, 참여자·제출물·Score·OpenAI 키는 따라오지 않는다
    (`services.copy_class` docstring 참고)."""

    # 원본이 보관됐어도 복사해서 새로 여는 것은 막지 않는다(`classroom.
    # participation` 「열어 두는 것」의 "복사해서 새로 열기") — 새 클래스가
    # 결과물이지 원본을 바꾸지 않는다.
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    new_class = copy_class(class_obj, request.auth_user.id)
    return 201, _serialize_class(new_class, viewer_id=request.auth_user.id)


@router.get(
    "/classes/{class_id}/scoring-models",
    response={200: ScoringModelCatalogOut, 404: ErrorOut},
    auth=jwt_auth,
)
def list_class_scoring_models(request: HttpRequest, class_id: int):
    """「클래스 설정」과 문제 만들기·편집이 선택지를 채우는 자리(#401) —
    예전 전역 `GET /scoring-models`(#285)를 대신한다: 키가 클래스에 있으므로
    "이 클래스의 키로 실제로 쓸 수 있는 모델"은 클래스 기준으로만 답할 수
    있다. 남의 클래스는 404다(`instructor_scope.class_scope`와 같은 규율)."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    catalog = get_scoring_model_catalog(class_obj)
    # 「에이전트」 방식 클래스는 에이전트가 받는 모델만 고른다(#1311) — OpenAI 의 gpt-5-mini 아래는 빠진다.
    agent_only = agent_grading.uses_agent(class_obj, "scoring")
    vendor = scoring_connection.agent_vendor_of(class_obj)
    return 200, ScoringModelCatalogOut(
        models=[
            ScoringModelOut(
                id=c.id,
                label=c.label,
                context_window=c.context_window,
                is_reasoning_model=c.is_reasoning_model,
            )
            for c in catalog.models
            if not agent_only or agent_grading.agent_model_allowed(vendor, c.id)
        ],
        source=catalog.source,
        unavailable_reason=catalog.unavailable_reason,
    )


def _cost_attempt_out(cost: scoring_cost.AttemptCost, unit: str) -> ScoringCostAttemptOut:
    return ScoringCostAttemptOut(krw=cost.krw if unit == "krw" else None, tokens=cost.total_tokens)


def scoring_cost_estimate(class_obj: Class, problem: Problem | None = None) -> scoring_cost.CostEstimate:
    """이 클래스(와 문제)의 예상 채점 비용(#591) — 화면 API 와 연결된 앱이 같은 값을 읽는다.
    줄은 이 키로 쓸 수 있는 모델(`cached_scoring_model_catalog` — 벤더에 묻지 않는다, #982)만, 지금 설정(클래스 기본값과
    이 문제가 실제로 쓸 모델)은 단가를 몰라도 한 줄을 받는다."""

    current = [class_obj.default_model]
    if problem is not None:
        current.append(problem.effective_model())
    if class_obj.scoring_connection_kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        # 호환 서버는 단가를 모른다(#604) — 지금 설정만, 채점 요청에 실을 강도로 토큰을 센다.
        settings = [
            (
                class_obj.default_model,
                _sent_effort(
                    class_obj,
                    class_obj.default_model,
                    class_obj.default_reasoning_effort,
                    marked_reasoning=class_obj.default_model_marked_reasoning,
                ),
            )
        ]
        if problem is not None:
            model = problem.effective_model()
            settings.append(
                (
                    model,
                    _sent_effort(
                        class_obj,
                        model,
                        problem.effective_reasoning_effort(),
                        marked_reasoning=problem.effective_model_marked_reasoning(),
                    ),
                )
            )
        return scoring_cost.estimate(
            class_obj,
            participant_count=len(_active_member_ids(class_obj)),
            catalog_model_ids=[],
            current_model_ids=current,
            problem=problem,
            token_settings=settings,
        )
    return scoring_cost.estimate(
        class_obj,
        participant_count=len(_active_member_ids(class_obj)),
        catalog_model_ids=[c.id for c in cached_scoring_model_catalog(class_obj).models],
        current_model_ids=current,
        problem=problem,
    )


def _sent_effort(class_obj: Class, model_id: str, effort: str | None, *, marked_reasoning: bool) -> str | None:
    """채점 요청에 실을 추론 강도 — 싣지 않으면 `None`(호환 서버의 토큰 어림이 출력을 이것으로 고른다)."""

    if not _sends_reasoning_effort(class_obj, model_id, marked_reasoning=marked_reasoning):
        return None
    return effort or "low"


def _serialize_scoring_cost(estimate: scoring_cost.CostEstimate) -> ScoringCostEstimateOut:
    unit = estimate.unit
    return ScoringCostEstimateOut(
        unit=unit,
        basis=estimate.basis,
        sample_count=estimate.sample_count,
        min_sample_count=scoring_cost.MIN_SAMPLE_COUNT,
        avg_prompt_chars=estimate.avg_prompt_chars,
        avg_input_tokens=(
            scoring_cost.tokens_for_chars(estimate.avg_prompt_chars)
            if estimate.avg_prompt_chars is not None
            else None
        ),
        participant_count=estimate.participant_count,
        attempts_per_participant=estimate.attempts_per_participant,
        attempts_per_participant_measured=estimate.attempts_per_participant_measured,
        source_size_bands=list(scoring_cost.SOURCE_SIZE_BANDS),
        baseline_model_id=scoring_cost.BASELINE_MODEL,
        krw_per_usd=scoring_cost.KRW_PER_USD,
        rows=[
            ScoringCostRowOut(
                model_id=row.model_id,
                reasoning_effort=row.reasoning_effort,
                priced=row.priced,
                open_ended=row.open_ended,
                per_attempt=_cost_attempt_out(row.per_attempt, unit) if row.per_attempt is not None else None,
                per_problem_krw=row.per_problem_krw,
                per_problem_tokens=row.per_problem_tokens,
                ratio_to_baseline=row.ratio_to_baseline,
                by_source_size=[_cost_attempt_out(c, unit) for c in row.by_source_size],
            )
            for row in estimate.rows
        ],
    )


@router.get(
    "/classes/{class_id}/scoring-cost",
    response={200: ScoringCostEstimateOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_class_scoring_cost(request: HttpRequest, class_id: int, problem_id: int | None = None):
    """「클래스 설정 › 채점」과 「문제 설정 › 채점 모델」이 보이는 예상 채점 비용(#591).
    `problem_id` 를 주면 그 문제의 지난 시도부터 기준으로 삼는다. 남의 클래스·문제는 404다."""

    if problem_id is None:
        scope = class_scope(class_id, request.auth_user.id, write=False, owner=False)
        problem = None
    else:
        scope = problem_scope(class_id, problem_id, request.auth_user.id, write=False, owner=False)
        problem = scope.problem
    return 200, _serialize_scoring_cost(scoring_cost_estimate(scope.class_obj, problem))


def _spread_out(spread: scoring_calculator.Spread, scale: float = 1.0) -> dict[str, float | int | None]:
    return {
        "sample_count": spread.sample_count,
        "median": spread.median * scale if spread.median is not None else None,
        "p90": spread.p90 * scale if spread.p90 is not None else None,
    }


def _single_cell_out(cell: scoring_calculator.SingleCall) -> dict[str, object]:
    return {
        "input_tokens": cell.input_tokens,
        "output_tokens": cell.output_tokens,
        "usd": cell.usd,
        "krw": cell.usd * scoring_cost.KRW_PER_USD,
        "open_ended": cell.open_ended,
        "fits": cell.fits,
        "capacity_chars": cell.capacity_chars,
        "capacity_chars_hangul": cell.capacity_chars_hangul,
        "capacity_files": cell.capacity_files,
        "capacity_files_hangul": cell.capacity_files_hangul,
        "route": cell.route,
        "seconds": cell.seconds,
        "partial_krw": cell.partial_usd * scoring_cost.KRW_PER_USD,
    }


def serialize_scoring_calculator(calc: scoring_calculator.Calculation) -> dict[str, object]:
    """화면 API 와 연결된 앱(`get_problem`)이 같은 꼴로 읽는다."""

    krw = scoring_cost.KRW_PER_USD
    a = calc.assumptions
    return {
        "providers": [
            {
                "vendor": p.vendor,
                "has_key": p.has_key,
                "models": [
                    {
                        "id": m,
                        "input_usd_per_million": scoring_cost.PRICES[m].input_usd_per_million,
                        "output_usd_per_million": scoring_cost.PRICES[m].output_usd_per_million,
                        "context_tokens": context_window_tokens(m),
                    }
                    for m in p.models
                ],
            }
            for p in calc.providers
        ],
        "agent_vendors": list(calc.agent_vendors),
        "problems": [
            {
                "id": p.id,
                "title": p.title,
                "requirement_count": p.requirement_count,
                "instruction_chars": p.instruction_chars,
                "sample_count": p.sample_count,
                "sources": [{"key": s.key, "chars": s.chars, "measured": s.measured} for s in p.sources],
            }
            for p in calc.problems
        ],
        "selection": {
            "vendor": calc.selection.vendor,
            "method": calc.selection.method,
            "model_id": calc.selection.model_id,
            "reasoning_effort": calc.selection.reasoning_effort,
            "problem_id": calc.selection.problem_id,
            "source": calc.selection.source,
            "source_chars": calc.selection.source_chars,
        },
        "assumptions": {
            "source_chars": a.source_chars,
            "source_files": scoring_calculator.files_of_chars(a.source_chars),
            "source_chars_per_file": scoring_calculator.SOURCE_CHARS_PER_FILE,
            "requirements": a.requirements,
            "instruction_chars": a.instruction_chars,
            "requirements_from": a.requirements_from,
            "source_from": a.source_from,
        },
        "defaults": {
            "source_chars_median": scoring_calculator.ASSUMED_SOURCE_CHARS_MEDIAN,
            "source_chars_p90": scoring_calculator.ASSUMED_SOURCE_CHARS_P90,
            "requirements": scoring_calculator.ASSUMED_REQUIREMENTS,
        },
        "rows": [
            {
                "vendor": r.vendor,
                "model_id": r.model_id,
                "single": _single_cell_out(r.single),
                "agent": {
                    "available": r.agent.available,
                    "usd": r.agent.usd,
                    "krw": r.agent.usd * krw if r.agent.usd is not None else None,
                    "seconds": r.agent.seconds,
                    "measured_krw": _spread_out(r.agent.measured_usd, krw),
                    "measured_seconds": _spread_out(r.agent.measured_seconds),
                },
            }
            for r in calc.rows
        ],
        "staged": {
            "enabled": calc.staged,
            "threshold_chars": calc.two_step_threshold_chars,
            "budget_chars": calc.two_step_budget_chars,
        },
        "agent_limits": {
            "max_zip_bytes": calc.agent_limits.max_zip_bytes,
            "max_extracted_bytes": calc.agent_limits.max_extracted_bytes,
            "max_zip_entries": calc.agent_limits.max_zip_entries,
            "attempt_seconds": calc.agent_limits.attempt_seconds,
            "attempts": calc.agent_limits.attempts,
            "budget_usd": calc.agent_limits.budget_usd,
        },
        "oversize": {
            "policy": calc.oversize_policy,
            "agent_model": calc.oversize_agent_model,
            "agent_krw": calc.oversize_agent_usd * krw if calc.oversize_agent_usd is not None else None,
        },
        "min_sample_count": scoring_cost.MIN_SAMPLE_COUNT,
        "krw_per_usd": krw,
    }


@router.get(
    "/classes/{class_id}/scoring-calculator",
    response={200: ScoringCalculatorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_class_scoring_calculator(
    request: HttpRequest,
    class_id: int,
    vendor: str | None = None,
    method: str | None = None,
    model: str | None = None,
    problem_id: int | None = None,
    source: str | None = None,
    source_chars: int | None = None,
    requirements: int | None = None,
):
    """「클래스 설정 › 채점 방식」의 채점 비용 예상표(#1270·#1304). 빈 값·고를 수 없는 값은 지금 이 클래스의 조합·
    기본 가정으로 채운다(가정을 바꿔 본 값은 저장하지 않는다). 남의 클래스는 404다."""

    scope = class_scope(class_id, request.auth_user.id, write=False, owner=False)
    calc = scoring_calculator.calculate(
        scope.class_obj,
        vendor=vendor,
        method=method,
        model_id=model,
        problem_id=problem_id,
        source=source,
        overrides=scoring_calculator.Overrides(
            source_chars=source_chars,
            requirements=requirements,
        ),
    )
    return 200, serialize_scoring_calculator(calc)


@router.post(
    "/classes/{class_id}/join-link/regenerate",
    response={200: JoinLinkOut, 404: ErrorOut},
    auth=jwt_auth,
)
def regenerate_join_link(request: HttpRequest, class_id: int):
    """가입 링크를 다시 뽑는다(#279). 새 코드로 덮어쓰므로 이전 코드는 그
    순간부터 어떤 클래스도 가리키지 않는다 — 링크가 새어 나갔을 때 강사가
    쓸 수 있는 유일한 조치다."""

    # 보관된 클래스라도 링크 재발급 자체는 막지 않는다 — 가입은 `join_class`
    # 가 보관을 따로 막으므로 여기서 또 막을 이유가 없다.
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    class_authoring.regenerate_join_link(class_obj)
    return 200, JoinLinkOut(join_code=class_obj.join_code)


@router.post("/classes/{class_id}/archive", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def archive_class(request: HttpRequest, class_id: int):
    """수업이 끝나면 보관한다(#294) — 지우지 않는다. 새 가입·새 제출만
    닫히고, 지난 문제·제출물·판정·달성률은 계속 읽힌다(CONTEXT.md
    「Class」). 이미 보관된 클래스를 다시 보관해도 오류를 내지 않는다(멱등,
    `expel_member`와 같은 관용구)."""

    # 보관 자체를 여는 동작이라 보관 여부로 스스로를 막을 수 없다(이미
    # 보관됐어도 멱등하게 통과).
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    class_authoring.archive_class(class_obj)
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.post(
    "/classes/{class_id}/unarchive", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth
)
def unarchive_class(request: HttpRequest, class_id: int):
    """보관을 되돌린다(#294 AC "강사가 클래스를 보관하고 다시 되돌릴 수
    있다") — `archived_at`을 지우면 그대로 진행중이다, 보관 이력을 따로
    남기지 않는다."""

    # 보관을 되돌리는 동작 자체다(`classroom.participation` 「열어 두는
    # 것」의 "보관 되돌리기") — 보관 여부로 막으면 되돌릴 수 없게 된다.
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    class_authoring.unarchive_class(class_obj)
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


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

    # 클래스 삭제 자체다(`classroom.participation` 「열어 두는 것」) — 제출이
    # 있으면 아래에서 따로 거절하므로 보관 여부는 이 경로를 막지 않는다. 클래스의
    # 존폐는 소유자 몫이다(ADR-0055).
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    remove_class(class_obj)
    return 204, None


def ensure_class_deletable(class_obj: Class) -> None:
    """제출이 하나라도 있으면 화면과 같은 문장으로 거절한다 — 화면(`delete_class`)과
    연결된 앱의 두 단계 삭제(`classroom.mcp_destructive_tools`, #515)가 미리보기와
    실행 양쪽에서 이 판정 하나를 부른다."""

    if ClassroomSubmission.objects.filter(problem__classroom=class_obj).exists():
        raise HttpError(403, "제출이 있는 클래스는 지울 수 없습니다. 대신 보관해주세요.")


def remove_class(class_obj: Class) -> None:
    """클래스를 지운다(`delete_class` docstring의 규칙 그대로) — 화면과 연결된 앱이 함께 쓴다."""

    ensure_class_deletable(class_obj)
    class_obj.delete()


# --- Join (#280) -----------------------------------------------------------------


def _get_class_by_join_code_or_404(join_code: str) -> Class:
    """코드가 없거나(오타) 재발급으로 죽었거나 — 이유를 구별하지 않는다.
    둘 다 "이 링크는 더 이상 쓸 수 없다"로 같게 답하는 것이 곧 #279가 정한
    재발급의 효과다."""

    try:
        return Class.objects.get(join_code=join_code)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "이 가입 링크는 더 이상 사용할 수 없습니다.") from exc


def _suggested_name(auth_user) -> str | None:
    """이름 칸 기본값으로 쓸 제안 이름 — 로그인한 사람의 카카오 닉네임(#390). 가입
    미리보기와 공동 강사 초대 미리보기가 같은 값을 쓴다."""

    if auth_user is None:
        return None
    social_account = SocialAccount.objects.filter(user_id=auth_user.id).first()
    if social_account is not None and social_account.nickname:
        return social_account.nickname
    return None


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
    suggested_name = _suggested_name(auth_user)
    # 두 수치는 내 클래스 행과 같은 기준이다(#659) — 참여자 수는 가르치는 행의
    # `member_count`(강사 전원·내보낸 사람 제외, 같은 함수), 문제 수는 가입하면 보게 될
    # 열린 문제 수라 참여 중 행의 `open_problem_count` 와 같다. 초안은 강사만 보고 숨긴
    # 문제는 참여자 목록에서 빠지므로(CONTEXT.md 「Problem」) 가입할 사람에게 셀 것이 아니다.
    return 200, JoinPreviewOut(
        class_id=class_obj.id,
        class_name=class_obj.name,
        instructor_display_name=class_obj.instructor_display_name or None,
        instructor_display_names=co_instructors.instructor_names(class_obj),
        open_problem_count=class_obj.problems.filter(status=Problem.Status.OPEN).count(),
        member_count=len(_active_member_ids(class_obj)),
        archived=class_obj.archived_at is not None,
        already_joined=already_joined,
        suggested_name=suggested_name,
    )


# 이름 금칙어 검사는 `class_authoring.reject_banned_name` 하나다(#516) — 이 이름은
# 가입·이름 바꾸기와 `classroom.template_api` 가 그대로 부른다.
_reject_if_banned_name = class_authoring.reject_banned_name


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
    _reject_if_banned_name(payload.display_name)
    member, created = ClassMember.objects.get_or_create(
        classroom=class_obj,
        user_id=request.auth_user.id,
        defaults={"display_name": payload.display_name},
    )
    if created:
        # 격자의 새 행·달성률 분모 — 강사가 열어 둔 클래스 머리·격자·문제 목록이 다시 읽는다(#1471 ⑦).
        publish_instructors_changed(class_obj)
    return 200, JoinResultOut(
        class_id=class_obj.id, class_name=class_obj.name, display_name=member.display_name
    )


# --- 공동 강사 초대 (#561, CONTEXT.md 「공동 강사 초대」) -----------------------------


@router.post(
    "/classes/{class_id}/co-instructor-invites",
    response={201: CoInstructorInviteOut, 404: ErrorOut},
    auth=jwt_auth,
)
def create_co_instructor_invite(request: HttpRequest, class_id: int):
    """강사(소유자 또는 공동 강사)가 1회용 초대 링크를 하나 만든다 — 7일 뒤 만료되고, 여러 개를
    동시에 열어 둘 수 있다."""

    # 사람을 들이는 일은 클래스의 존폐 쪽이라 보관된 클래스에서도 연다(CONTEXT.md
    # 「공동 강사」) — write=False. 소유자 전용이 아니다(ADR-0055: 초대는 강사 누구나).
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    invite = co_instructors.create_invite(class_obj, request.auth_user.id)
    return 201, CoInstructorInviteOut(
        id=invite.id, token=invite.token, created_at=invite.created_at, expires_at=invite.expires_at
    )


@router.get(
    "/classes/{class_id}/instructors",
    response={200: list[ClassInstructorOut], 404: ErrorOut},
    auth=jwt_auth,
)
def list_class_instructors(request: HttpRequest, class_id: int):
    """클래스 관리 「강사」 영역의 강사 목록 — 강사 누구나 본다, 보관된 클래스에서도(#562)."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    return 200, [ClassInstructorOut(**row) for row in co_instructors.roster(class_obj, request.auth_user.id)]


@router.get(
    "/classes/{class_id}/co-instructor-invites",
    response={200: list[PendingCoInstructorInviteOut], 404: ErrorOut},
    auth=jwt_auth,
)
def list_pending_co_instructor_invites(request: HttpRequest, class_id: int):
    """아직 쓰이지 않은 공동 강사 초대 — 강사 누구나 본다(누가 만들었든), 보관된 클래스에서도
    (#562). 수락·만료·취소된 초대는 빠진다. 링크를 다시 복사할 수 있게 토큰도 싣는다 — 이
    클래스의 강사는 어차피 새 초대를 만들 수 있으므로 더 넓히는 것이 없다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    viewer_id = request.auth_user.id
    return 200, [
        PendingCoInstructorInviteOut(
            id=invite.id,
            token=invite.token,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            created_by_name=created_by_name,
            created_by_me=invite.created_by_id == viewer_id,
        )
        for invite, created_by_name in co_instructors.pending_invites(class_obj)
    ]


@router.post(
    "/classes/{class_id}/co-instructor-invites/{invite_id}/cancel",
    response={204: None, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def cancel_co_instructor_invite(request: HttpRequest, class_id: int, invite_id: int):
    """대기 중인 초대를 취소한다 — 강사 누구나, 누가 만든 초대든, 보관된 클래스에서도(#562).
    취소한 링크는 「취소된 초대」로 보이고 수락되지 않는다. 남의 클래스·다른 클래스의 초대는
    404, 이미 쓰였거나 만료·취소됐으면 409."""

    # 초대 만들기와 같은 이유로 write=False — 사람을 들이는 일은 보관과 무관하다.
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    co_instructors.cancel_invite(class_obj, invite_id)
    return 204, None


@router.patch(
    "/classes/{class_id}/instructors/me",
    response={200: ClassInstructorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def rename_my_instructor_name(request: HttpRequest, class_id: int, payload: InstructorNameIn):
    """부른 강사가 이 클래스에서 불릴 **자기** 강사 이름을 바꾼다(#565) — 소유자든 공동
    강사든, 보관된 클래스에서도(클래스 설정과 같은 쪽). 응답은 강사 목록의 그 사람 줄이다.

    클래스 설정(`PATCH /classes/{id}`)의 `instructor_display_name` 이 아니라 따로 둔 이유: 그
    칸은 읽을 때(`ClassOut`·참여자의 클래스 목록·연결된 앱)나 쓸 때나 **소유자의** 이름이다.
    공동 강사가 보낸 같은 칸을 「보는 사람의 자리」로 바꿔 쓰면 같은 이름의 칸이 쓰는 사람마다
    다른 사람을 가리키고, 써 넣은 값이 응답의 같은 칸에 돌아오지 않는다. 여기는 경로가 `me` 라
    다른 강사를 가리킬 자리 자체가 없다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    row = co_instructors.rename_myself(class_obj, request.auth_user.id, payload.display_name)
    return 200, ClassInstructorOut(**row)


@router.post(
    "/classes/{class_id}/instructors/me/leave",
    response={204: None, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def leave_class(request: HttpRequest, class_id: int):
    """공동 강사가 스스로 클래스를 떠난다(#563) — 보관된 클래스에서도. 떠난 뒤에는 그 클래스가
    목록에서 사라지고 강사 라우트가 404 다. 소유자는 409 — 넘기거나 보관·삭제한다."""

    # 사람이 드나드는 일은 보관과 무관하다(초대와 같다) — write=False.
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    co_instructors.leave(class_obj, request.auth_user.id)
    return 204, None


@router.post(
    "/classes/{class_id}/co-instructors/{co_instructor_id}/remove",
    response={204: None, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def remove_co_instructor(request: HttpRequest, class_id: int, co_instructor_id: int):
    """소유자가 공동 강사를 내보낸다(#563) — 소유자 전용, 보관된 클래스에서도. 떠나기와 같은
    정리를 한다(`classroom.co_instructors.depart`)."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    co_instructors.remove_by_owner(class_obj, co_instructor_id)
    return 204, None


# --- 소유권 이전 (#564, CONTEXT.md 「소유권 이전」) -----------------------------------
#
# 넷 다 보관과 무관하다(write=False) — 사람을 들이고 내보내고 넘기는 일은 클래스의 존폐 쪽이다.


@router.post(
    "/classes/{class_id}/ownership-transfers",
    response={201: PendingOwnershipTransferOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def request_ownership_transfer(request: HttpRequest, class_id: int, payload: OwnershipTransferIn):
    """소유자가 공동 강사 한 사람에게 소유권 이전을 요청한다 — 클래스마다 대기 하나, 7일 뒤 만료.
    이 클래스의 공동 강사 줄이 아니면 404, 이미 대기 중이면 409."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    ownership_transfers.request(class_obj, request.auth_user.id, payload.co_instructor_id)
    return 201, _pending_ownership_transfer_out(class_obj, request.auth_user.id)


@router.post(
    "/classes/{class_id}/ownership-transfers/{transfer_id}/cancel",
    response={204: None, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def cancel_ownership_transfer(request: HttpRequest, class_id: int, transfer_id: int):
    """소유자가 대기 중인 이전 요청을 취소한다. 끝난 요청이면 409."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    ownership_transfers.cancel(class_obj, request.auth_user.id, transfer_id)
    return 204, None


@router.post(
    "/classes/{class_id}/ownership-transfers/{transfer_id}/accept",
    response={200: ClassOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def accept_ownership_transfer(request: HttpRequest, class_id: int, transfer_id: int):
    """받는 공동 강사가 수락한다 — 그 순간 소유자가 되고, 넘긴 사람은 공동 강사로 남고, 채점 키가
    비워진다(`classroom.ownership_transfers.accept`). 응답은 새 소유자가 보는 클래스다."""

    # 받는 사람은 공동 강사다 — 소유자 전용 문이 아니라 「받는 사람인가」를 모듈이 본다(403).
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    class_obj = ownership_transfers.accept(class_obj, request.auth_user.id, transfer_id)
    return 200, _serialize_class(class_obj, viewer_id=request.auth_user.id)


@router.post(
    "/classes/{class_id}/ownership-transfers/{transfer_id}/decline",
    response={204: None, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def decline_ownership_transfer(request: HttpRequest, class_id: int, transfer_id: int):
    """받는 공동 강사가 거절한다. 아무것도 바뀌지 않고 요청만 끝난다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    ownership_transfers.decline(class_obj, request.auth_user.id, transfer_id)
    return 204, None


@router.get(
    "/co-instructor-invites/{token}",
    response={200: CoInstructorInvitePreviewOut, 404: ErrorOut},
    auth=None,
)
def preview_co_instructor_invite(request: HttpRequest, token: str):
    """초대 링크를 연 사람이 무엇을 수락하는지 본다 — 로그인하지 않아도 열린다(가입 링크
    미리보기와 같다). 쓰였거나 만료·취소된 초대도 404 로 숨기지 않고 그 상태를 말한다 —
    받은 사람이 초대한 사람에게 새 링크를 부탁할 수 있게."""

    invite = co_instructors.invite_or_404(token)
    class_obj = invite.classroom
    status = invite.status_at(Clock.now())
    auth_user = getattr(request, "auth_user", None)
    return 200, CoInstructorInvitePreviewOut(
        class_id=class_obj.id,
        class_name=class_obj.name,
        instructor_names=co_instructors.instructor_names(class_obj),
        status=status,
        status_message=co_instructors.not_pending_message(status),
        expires_at=invite.expires_at,
        archived=class_obj.archived_at is not None,
        already_instructor=auth_user is not None and is_instructor(class_obj, auth_user.id),
        suggested_name=_suggested_name(auth_user),
    )


@router.post(
    "/co-instructor-invites/{token}/accept",
    response={200: CoInstructorAcceptOut, 404: ErrorOut, 409: ErrorOut, 410: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def accept_co_instructor_invite(request: HttpRequest, token: str, payload: CoInstructorAcceptIn):
    """초대를 쓰고 그 클래스의 공동 강사가 된다 — 1회용이라 행을 잠그고 다시 확인한다
    (`classroom.co_instructors.accept_invite`). 이미 강사면 409 이고 초대는 남는다.
    참여자였던 사람도 수락할 수 있다 — 참여자 행은 그대로 두고 집계에서만 빠진다."""

    class_obj = co_instructors.accept_invite(token, request.auth_user.id, payload.display_name)
    return 200, CoInstructorAcceptOut(class_id=class_obj.id, class_name=class_obj.name)


# --- Member (#281) ---------------------------------------------------------------


def _serialize_member(member: ClassMember, class_obj: Class, *, left: bool | None = None) -> MemberOut:
    return MemberOut(
        id=member.id,
        display_name=member.display_name,
        joined_at=member.joined_at,
        expelled=member.expelled_at is not None,
        left=is_left(member) if left is None else left,
        is_instructor=is_instructor(class_obj, member.user_id),
    )


@router.get(
    "/classes/{class_id}/members", response={200: list[MemberOut], 404: ErrorOut}, auth=jwt_auth
)
def list_members(request: HttpRequest, class_id: int):
    """강사만 본다 — 참여자는 자기 클래스든 남의 클래스든 명단에 닿지
    못한다(#281 AC "참여자는 남의 명단을 볼 수 없다"), `instructor_scope.
    class_scope`가 강사가 아닌 모든 요청을 404로 돌리는 것과 같은 문이다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    return 200, _serialize_members(class_obj)


def _serialize_members(class_obj: Class) -> list[MemberOut]:
    """참여자 명단 — 화면(`list_members`)과 연결된 앱의 읽기 도구
    (`classroom.mcp_read_tools`, #513)가 함께 부른다."""

    members = list(class_obj.members.all())
    left_ids = left_member_ids(members)
    return [_serialize_member(m, class_obj, left=m.id in left_ids) for m in members]


@router.post(
    "/classes/{class_id}/members/{member_id}/expel",
    response={200: MemberOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def expel_member(request: HttpRequest, class_id: int, member_id: int):
    """행을 지우지 않는다 — 표시만 한다(#281). 이미 내보낸 사람을 다시
    내보내도 오류를 내지 않고 그대로 둔다(멱등)."""

    # 보관된 클래스에서도 명단 정리는 열어 둔다 — 새 가입·새 제출처럼 새
    # 활동을 만드는 것이 아니라 이미 있는 명단을 표시만 바꾸는 것이다.
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    member = class_member_or_404(class_obj, member_id)
    assert_member_expellable(class_obj, member)
    member = expel_class_member(member)
    return 200, _serialize_member(member, class_obj)


def class_member_or_404(class_obj: Class, member_id: int) -> ClassMember:
    """그 클래스의 참여자 한 명 — 화면(`expel_member`)과 연결된 앱(#515)이 같은 문장으로 찾는다."""

    try:
        return class_obj.members.get(id=member_id)
    except ClassMember.DoesNotExist as exc:
        raise HttpError(404, "참여자를 찾을 수 없습니다.") from exc


def assert_member_expellable(class_obj: Class, member: ClassMember) -> None:
    """강사(소유자·공동 강사)의 자기 참여자 행은 내보내지 않는다(#669) — 집계에서 이미 빠지므로
    내보낼 이유가 없고, 내보내면 그 강사가 자기 클래스에 다시 낼 길만 막힌다. 참여자였다가 공동
    강사가 된 사람도 강사다. 화면(`expel_member`)과 연결된 앱(#515)이 같은 문장으로 거절한다."""

    if is_instructor(class_obj, member.user_id):
        raise HttpError(403, "강사는 내보낼 수 없습니다.")


def expel_class_member(member: ClassMember) -> ClassMember:
    """내보낸다 — 행을 지우지 않고 표시만, 이미 내보낸 사람이면 그대로(`expel_member` docstring)."""

    if member.expelled_at is not None:
        return member
    # 조건부 갱신으로 최초 전이를 가린다(#1448 ④) — 두 강사가 동시에 내보내 둘 다 `expelled_at=None` 을
    # 읽었어도 행을 바꾼 쪽은 하나다. 진 쪽은 이긴 쪽이 남긴 시각을 읽어 돌려준다.
    first = ClassMember.objects.filter(id=member.id, expelled_at__isnull=True).update(expelled_at=timezone.now())
    member.refresh_from_db(fields=["expelled_at"])
    if first:
        # 내보내진 그 사람의 열린 제출 화면만 — 다른 참여자에게는 보내지 않는다(#1447 10-2).
        # 그 행·달성률 분모도 바뀐다 — 강사가 열어 둔 클래스 머리·격자·문제 목록이 같은 변경 번호로 다시 읽는다(#1471 ⑦).
        publish_participation_changed(member.classroom, member_user_ids=[member.user_id])
        # 처음 내보낼 때만 — 내보내진 사람에게 알린다(#1441-8). 알림이 실패해도 내보내기는 그대로다.
        notify_safely(
            recipient=member.user,
            notification_type=NotificationType.CLASSROOM_MEMBER_EXPELLED,
            context={"class_id": member.classroom_id, "class_name": member.classroom.name},
        )
    return member


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
    `ClassMemberDisplayName`을 그대로 쓴다. 금칙어 검사(spec #474, #475)도
    가입 때와 같다 — 가입할 때만 막으면 그 뒤에 사칭 이름으로 바꾸면
    그만이기 때문이다."""

    member = _get_member_or_404(class_id, request.auth_user.id)

    reason = participant_membership_blocked_reason(member.classroom, member)
    if reason == SUBMIT_BLOCKED_ARCHIVED:
        raise HttpError(403, "이 클래스는 보관되어 이름을 바꿀 수 없습니다.")
    if reason in (SUBMIT_BLOCKED_EXPELLED, SUBMIT_BLOCKED_LEFT):
        raise HttpError(403, "더 이상 이 클래스의 참여자가 아닙니다.")
    _reject_if_banned_name(payload.display_name)

    member.display_name = payload.display_name
    member.save(update_fields=["display_name"])

    return 200, MemberRenameOut(display_name=member.display_name)


# --- Roster grid (#290) -----------------------------------------------------------


def _last_attempt_late(problem: Problem, submissions: list[ClassroomSubmission]) -> LateStatus:
    """격자 칸·참여자 목록 줄의 「늦음」(#769) — **마지막 시도**의 권장 기한 뒤·마감 기한 뒤를 구분한다.
    통과 이력(`_cell_status`)과 달리 OR 가 아니다: 늦게 낸 뒤 제때 다시 낸 사람은
    늦지 않은 것이고, 반대로 제때 냈다가 늦게 다시 낸 사람은 늦은 것이다."""

    last = max((s.created_at for s in submissions), default=None)
    return problem.lateness(last) if last is not None else None


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
    본다) — 아니면 "scoring"(아직 뒤집힐 여지가 있다는 뜻이다). 전부 채점됐는데 하나도 통과가 없으면
    "attempted_not_passed". 시도 자체가 없으면 "not_submitted".

    통과 판정은 `Problem.is_score_passed`(#436)에 맡긴다 — 필수 항목·문법
    검사 설정을 이 함수가 다시 받지 않는다. `problem.checklist_items`가
    이미 `prefetch_related`로 불려 있어(호출부인 `get_roster_grid`) 문제
    수만큼 질의가 늘지 않는다."""

    if not submissions:
        return "not_submitted"
    if any(problem.is_score_passed(current_score(s)) for s in submissions):
        return "passed"
    if any(current_score(s) is None for s in submissions):
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

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    return 200, _build_roster_grid(class_obj)


def _build_roster_grid(class_obj: Class) -> ClassroomRosterGridOut:
    """명단 격자 한 벌 — 화면(`get_roster_grid`)과 연결된 앱의 읽기 도구
    (`classroom.mcp_read_tools`, #513)가 함께 부른다. 범위 확인은 부르는 쪽이
    먼저 끝낸다."""

    problems = list(class_obj.problems.prefetch_related("checklist_items").all())
    members = list(class_obj.members.all())
    active_member_ids = _active_member_ids(class_obj)

    submissions = ClassroomSubmission.objects.filter(
        problem__in=problems, member__in=members
    ).select_related("classroom_score").prefetch_related(current_score_prefetch()).defer(*_SCORE_PROMPT)
    submissions_by_key: dict[tuple[int, int], list[ClassroomSubmission]] = {}
    for submission in submissions:
        submissions_by_key.setdefault((submission.problem_id, submission.member_id), []).append(submission)

    problem_stats = []
    for problem in problems:
        passed_count, perfect_count, member_count, pass_rate = _problem_stats(problem, active_member_ids)
        problem_stats.append(
            ClassroomProblemStatsOut(
                id=problem.id,
                title=problem.title,
                status=problem.status,
                passed_count=passed_count,
                member_count=member_count,
                pass_rate=pass_rate,
                perfect_count=perfect_count,
                recommended_due_at=problem.recommended_due_at,
                due_at=problem.due_at,
            )
        )

    checklist_by_problem = {p.id: list(p.checklist_items.all()) for p in problems}
    marks = entry_marks(problems)
    member_rows = []
    left_ids = left_member_ids(members)
    for member in members:
        cells = [
            ClassroomGridCellOut(
                problem_id=problem.id,
                status=_cell_status(
                    submissions_by_key.get((problem.id, member.id), []),
                    class_obj,
                    problem,
                ),
                perfect=_perfect_ever(
                    submissions_by_key.get((problem.id, member.id), []), problem, checklist_by_problem[problem.id]
                ),
                contest_entry=marks.cell(
                    s.id for s in submissions_by_key.get((problem.id, member.id), [])
                ),
                late=_last_attempt_late(problem, submissions_by_key.get((problem.id, member.id), [])),
            )
            for problem in problems
        ]
        member_rows.append(
            ClassroomGridMemberOut(
                id=member.id,
                display_name=member.display_name,
                is_instructor=is_instructor(class_obj, member.user_id),
                expelled=member.expelled_at is not None,
                left=member.id in left_ids,
                cells=cells,
                joined_at=member.joined_at,
                last_submitted_at=max(
                    (s.created_at for problem in problems for s in submissions_by_key.get((problem.id, member.id), [])),
                    default=None,
                ),
            )
        )

    return ClassroomRosterGridOut(problems=problem_stats, members=member_rows)


#: 「최근 제출」 목록의 길이(#632) — 고정이다.
RECENT_ATTEMPTS_LIMIT = 10


@router.get(
    "/classes/{class_id}/recent-attempts",
    response={200: list[ClassroomRecentAttemptOut], 404: ErrorOut},
    auth=jwt_auth,
)
def list_recent_attempts(request: HttpRequest, class_id: int):
    """클래스의 최근 시도 열 건(#632) — 강사 전용. 강사 본인·내보낸 참여자의 시도는
    달성률과 같은 이유로 뺀다. 상태는 격자 칸의 낱말이다: 통과 이력이 아니라 **그 시도
    하나**의 결과(통과·미통과)이고, 아직 채점 전이면 「설정 필요」(`needs_setup`) 또는
    「채점 중」(`scoring`)이다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    attempts = list(_class_attempts_newest_first(class_obj)[:RECENT_ATTEMPTS_LIMIT])
    return 200, [_recent_attempt_row(class_obj, attempt) for attempt in attempts]


#: 「제출」 화면(#1317) 한 쪽의 줄 수.
CLASS_ATTEMPTS_PAGE_SIZE = 20


@router.get(
    "/classes/{class_id}/attempts",
    response={200: ClassroomAttemptPageOut, 404: ErrorOut},
    auth=jwt_auth,
)
def list_class_attempts(request: HttpRequest, class_id: int, page: int = 1):
    """클래스의 모든 시도(#1317 「제출」 화면) — 「최근 제출」과 같은 줄·같은 사람들·최신순이고, 쪽을 넘긴다. 줄마다
    「다시 채점」을 걸 수 있나(`correctable`)를 붙인다 — 범위는 `score_corrections.correctable` 하나가 정하고, 거는
    API 가 소유자만이라 공동 강사에게는 늘 거짓이다."""

    scope = class_scope(class_id, request.auth_user.id, write=False, owner=False)
    class_obj = scope.class_obj
    page = max(page, 1)
    start = (page - 1) * CLASS_ATTEMPTS_PAGE_SIZE
    window = list(_class_attempts_newest_first(class_obj)[start : start + CLASS_ATTEMPTS_PAGE_SIZE + 1])
    attempts = window[:CLASS_ATTEMPTS_PAGE_SIZE]
    verdicts = score_corrections.correctable(attempts) if scope.is_owner else {}
    rows = [
        ClassroomAttemptRowOut(
            **_recent_attempt_row(class_obj, attempt).model_dump(), correctable=verdicts.get(attempt.id, "") is None
        )
        for attempt in attempts
    ]
    return 200, ClassroomAttemptPageOut(rows=rows, page=page, has_next=len(window) > CLASS_ATTEMPTS_PAGE_SIZE)


@router.get(
    "/classes/{class_id}/attempts/{submission_id}/verdicts",
    response={200: ClassroomAttemptVerdictsOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_class_attempt_verdicts(request: HttpRequest, class_id: int, submission_id: int):
    """「제출」 화면 줄을 펼칠 때(#1334) 그 시도 하나의 현재 판정 — 문제별 제출 화면의 강사 응답과 같은 `_serialize_score`
    (정정으로 바뀐 점수는 정정 뒤 판정). 학생 소스·제출 값은 싣지 않는다. 범위는 목록과 같은 강사(소유자·공동 강사)와
    같은 참여자 집합이고, 그 밖은 404."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    attempt = _class_attempts_newest_first(class_obj).filter(id=submission_id).first()
    if attempt is None:
        raise HttpError(404, "제출을 찾을 수 없습니다.")
    score = current_score(attempt)
    return 200, ClassroomAttemptVerdictsOut(
        score=_serialize_score(score) if score is not None else None,
        checklist_items=[
            ClassroomAttemptChecklistItemOut(id=item.id, label=item.label) for item in attempt.problem.checklist_items.all()
        ],
    )


def _class_attempts_newest_first(class_obj: Class):
    return (
        _participant_submissions()
        .filter(problem__classroom_id=class_obj.id)
        .select_related("member", "problem", "classroom_score").prefetch_related(current_score_prefetch())
        .prefetch_related("problem__checklist_items")
        .order_by("-created_at", "-id")
    )


def _recent_attempt_row(class_obj: Class, attempt: ClassroomSubmission) -> ClassroomRecentAttemptOut:
    score = current_score(attempt)
    pending_reason = None
    if score is None:
        pending_reason = pending_scoring.blocking_reason(class_obj, attempt.problem)
        status = "needs_setup" if pending_reason is not None else "scoring"
    else:
        status = "passed" if attempt.problem.is_score_passed(score) else "attempted_not_passed"
        if score.model_version == PLATFORM_FAILURE_MODEL_VERSION:
            # 실패 상한 점수(#1316·#1317)는 학생이 못 넘은 것이 아니라 채점이 못 돈 것이다.
            status = "scoring_failed"
    return ClassroomRecentAttemptOut(
        id=attempt.id,
        member_id=attempt.member_id,
        member_display_name=attempt.member.display_name,
        problem_id=attempt.problem_id,
        problem_title=attempt.problem.title,
        attempt_number=attempt.attempt_number,
        status=status,
        submitted_at=attempt.created_at,
        late=attempt.problem.lateness(attempt.created_at),
        pending_reason=pending_reason,
        problem_model=attempt.problem.model,
    )


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

    class_obj = class_scope(class_id, request.auth_user.id, write=True, owner=False).class_obj
    problem = problem_authoring.create_problem(class_obj, payload)
    out = _serialize_problem(problem, class_obj, viewer_id=request.auth_user.id)
    out.gradability_warnings = [GradabilityWarningOut(**w) for w in gradability_warnings(problem.checklist_items.all())]
    return 201, out


@router.get(
    "/classes/{class_id}/problems", response={200: list[ProblemOut], 404: ErrorOut}, auth=jwt_auth
)
def list_problems(request: HttpRequest, class_id: int):
    """강사 본인의 클래스 문제 전부(초안 + 열림), 순서대로."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=False).class_obj
    return 200, _serialize_problem_list(class_obj, viewer_id=request.auth_user.id)


def _serialize_problem_list(class_obj: Class, viewer_id: int | None = None) -> list[ProblemOut]:
    """클래스의 문제 전부를 순서대로 — 화면(`list_problems`)과 연결된 앱의 읽기
    도구(`classroom.mcp_read_tools`, #513)가 함께 부른다."""

    return _serialize_problems(
        class_obj, class_obj.problems.prefetch_related("checklist_items").all(), viewer_id=viewer_id
    )


def _serialize_problems(class_obj: Class, problems, viewer_id: int | None = None) -> list[ProblemOut]:
    """문제 여럿을 한 번에(#679·#684) — 목록과 순서 바꾸기 응답이 함께 쓴다. 문제마다 따로 들던
    질의(제출 표식·달성률의 제출·살아 있는 템플릿)를 클래스 단위로 한 번씩 세어 넘기므로, 질의 수가
    문제 수와 무관하다. `problems` 는 체크리스트를 미리 불러 둔 것이어야 한다."""

    active_member_ids = _active_member_ids(class_obj)
    blocking_problem_ids = _problem_ids_blocking_deletion(class_obj)
    submission_marks = _participant_submission_marks("problem_id", problem__classroom_id=class_obj.id)
    submissions_by_problem: dict[int, list[ClassroomSubmission]] = {}
    for submission in ClassroomSubmission.objects.filter(
        problem__classroom_id=class_obj.id, member_id__in=active_member_ids
    ).select_related("classroom_score").prefetch_related(current_score_prefetch()).defer(*_SCORE_PROMPT):
        submissions_by_problem.setdefault(submission.problem_id, []).append(submission)
    # `_live_problem_template` 과 같은 답 — 살아 있는 템플릿은 `unique_live_problem_template_per_source`
    # 제약으로 문제당 하나뿐이라, 어느 순서로 고르든 같은 것이 나온다.
    live_template_by_problem: dict[int, ProblemTemplate] = {}
    for template in ProblemTemplate.objects.filter(
        source_problem__classroom_id=class_obj.id, taken_down_at__isnull=True
    ).order_by("-pk"):
        live_template_by_problem[template.source_problem_id] = template
    return [
        _serialize_problem(
            p,
            class_obj,
            active_member_ids=active_member_ids,
            blocking_problem_ids=blocking_problem_ids,
            submission_marks_by_problem=submission_marks,
            submissions_by_problem=submissions_by_problem,
            live_template_by_problem=live_template_by_problem,
            viewer_id=viewer_id,
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

    class_obj = class_scope(class_id, request.auth_user.id, write=True, owner=False).class_obj
    ordered = problem_authoring.reorder_problems(class_obj, payload.problem_ids)
    # 목록(`_serialize_problem_list`)과 같이 문제 행을 클래스 단위로 한 번에 센다(#679·#684).
    return 200, _serialize_problems(class_obj, ordered, viewer_id=request.auth_user.id)


#: 들여오기 목록 한 쪽의 크기(#548) — 공모전이 수백 개여도 시트가 한 번에 다 받지 않는다.
IMPORTABLE_CONTESTS_PAGE_SIZE = 20


@router.get(
    "/classes/{class_id}/importable-contests",
    response={200: ImportableContestPageOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def list_importable_contests(
    request: HttpRequest, class_id: int, q: str = "", after: str | None = None
):
    """새 문제 화면의 「공모전에서 들여오기」(#548) — 개최자가 「클래스에서 들여오기」를 허용한
    공개 중 · 마감 전 무료 공모전. 강의실은 공모전 앱을 모르므로 공유층 카탈로그가 답한다
    (ADR-0054). `q` 는 제목 검색, `after` 는 앞 쪽의 `next` — 마감 빠른 순으로 20개씩 준다."""

    class_scope(class_id, request.auth_user.id, write=False, owner=False)
    cursor = decode_cursor(after) if after else None
    if after and cursor is None:
        raise HttpError(422, "잘못된 목록 위치입니다. 처음부터 다시 불러 주세요.")
    rows = contest_catalog().list_importable(
        query=q[:100], after=cursor, limit=IMPORTABLE_CONTESTS_PAGE_SIZE + 1
    )
    page = rows[:IMPORTABLE_CONTESTS_PAGE_SIZE]
    has_more = len(rows) > IMPORTABLE_CONTESTS_PAGE_SIZE
    return 200, ImportableContestPageOut(
        items=[
            ImportableContestOut(
                contest_id=c.contest_id,
                title=c.title,
                deadline_at=c.deadline_at,
                requirement_count=c.requirement_count,
            )
            for c in page
        ],
        next=encode_cursor(page[-1].deadline_at, page[-1].contest_id) if has_more else None,
    )


@router.post(
    "/classes/{class_id}/problems/from-contest",
    response={201: ProblemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def import_contest_as_problem(request: HttpRequest, class_id: int, payload: ImportContestIn):
    """허용된 무료 공모전을 「공모전 문제」 초안으로 들여온다(#548, CONTEXT.md). 제목·설명·
    체크리스트는 그 공모전을 따라간다. 들여올 수 없으면(마감·허용 안 함·없음) 422."""

    class_obj = class_scope(class_id, request.auth_user.id, write=True, owner=False).class_obj
    problem = import_contest_problem(class_obj, payload.contest_id)
    return 201, _serialize_problem(problem, class_obj, viewer_id=request.auth_user.id)


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

    class_scope(class_id, request.auth_user.id, write=False, owner=False)

    problems = (
        Problem.objects.filter(classroom__in=classes_taught_by(request.auth_user.id))
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
                template_checklist_item_out(i)
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
    ).select_related("classroom_score").prefetch_related(current_score_prefetch()).defer(*_SCORE_PROMPT)
    submissions_by_problem: dict[int, list[ClassroomSubmission]] = {}
    for s in submissions:
        submissions_by_problem.setdefault(s.problem_id, []).append(s)

    def _list_items(problem_list: list[Problem]) -> list[ClassroomProblemListItemOut]:
        items = []
        for problem in problem_list:
            own = submissions_by_problem.get(problem.id, [])
            status = _cell_status(own, member.classroom, problem)
            items.append(
                ClassroomProblemListItemOut(
                    id=problem.id,
                    title=problem.title,
                    submission_formats=problem.submission_formats,
                    passed=status == "passed",
                    perfect=_perfect_ever(own, problem, list(problem.checklist_items.all())),
                    status=status,
                    attempt_count=len(own),
                    last_attempted_at=max((s.created_at for s in own), default=None),
                    recommended_due_at=problem.recommended_due_at,
                    due_at=problem.due_at,
                    late=_last_attempt_late(problem, own),
                )
            )
        return items

    return 200, ClassroomMyProblemsOut(
        class_name=member.classroom.name,
        instructor_display_names=co_instructors.instructor_names(member.classroom),
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

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=False, owner=False)
    return 200, _serialize_problem(scope.problem, scope.class_obj, viewer_id=request.auth_user.id)


@router.patch(
    "/classes/{class_id}/problems/{problem_id}",
    response={200: ProblemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def update_problem(request: HttpRequest, class_id: int, problem_id: int, payload: ProblemPatchIn):
    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    problem = problem_authoring.update_problem(scope.class_obj, scope.problem, payload)
    return 200, _serialize_problem(problem, scope.class_obj, viewer_id=request.auth_user.id)


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

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    remove_problem(scope.class_obj, scope.problem)
    return 204, None


def ensure_problem_deletable(problem: Problem, class_obj: Class) -> None:
    """지울 수 있는가는 소유권·존재·보관과는 다른 축의 판정이다(ADR-0050) —
    「그 문제 × 강사 자신」으로 닫힌 필터라 강사 범위와 합치지 않는다. 화면과 연결된 앱의
    두 단계 삭제(#515)가 미리보기와 실행 양쪽에서 이 판정 하나를 부른다."""

    if not _problem_deletable(problem, class_obj):
        raise HttpError(403, "지울 수 없습니다 — 대신 숨겨주세요.")


def remove_problem(class_obj: Class, problem: Problem) -> None:
    """문제를 지운다(`delete_problem` docstring의 규칙 그대로) — 화면과 연결된 앱이 함께 쓴다."""

    ensure_problem_deletable(problem, class_obj)
    # 채점을 걷는 것과 문제를 지우는 것, 둘이 한 트랜잭션이어야 한다 — 둘로
    # 쪼개진 채 죽으면(#431이 채점 걷기를 더하며 새로 생긴 위험) 채점만 사라지고
    # 문제·시도는 남는 어중간한 상태가 생긴다.
    with transaction.atomic():
        own = ClassroomScore.objects.filter(
            submission__problem=problem, submission__member__user_id__in=instructor_user_ids(class_obj)
        )
        # 그 채점에 덧댄 정정(#1317)도 같은 범위로 먼저 걷는다 — 정정이 점수를 PROTECT 로 가리킨다.
        ClassroomScoreCorrection.objects.filter(score__in=own).delete()
        own.delete()
        participants_saw_it = problem.status != Problem.Status.DRAFT
        problem.delete()
        # 격자 열·문제 목록에서 빠진다 — 그 클래스의 열린 화면이 다시 읽는다(#1471 ⑦).
        publish_problems_changed(class_obj, participants_see_it=participants_saw_it)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/open",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def open_problem(request: HttpRequest, class_id: int, problem_id: int):
    """초안을 연다. 필수 체크리스트 항목이 하나도 없으면 통과가 정의되지
    않아 막는다(#283 AC). 전이 표(`classroom.problem_transitions`, #440)가
    「초안에서만」과 「필수 항목이 있어야」 두 조건을 함께 정한다."""

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    problem = execute_transition("open", scope.problem)
    return 200, _serialize_problem(problem, scope.class_obj, viewer_id=request.auth_user.id)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/hide",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def hide_problem(request: HttpRequest, class_id: int, problem_id: int):
    """열린 문제를 참여자에게서 거둔다(#405) — 제출 유무와 무관하다. 열림
    →숨김만 허용한다: 초안은 애초에 참여자에게 보인 적이 없어 거둘 것이
    없고, 이미 숨긴 문제를 다시 숨기는 것도 뜻이 없다."""

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    problem = execute_transition("hide", scope.problem)
    return 200, _serialize_problem(problem, scope.class_obj, viewer_id=request.auth_user.id)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/reopen",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def reopen_problem(request: HttpRequest, class_id: int, problem_id: int):
    """숨긴 문제를 되돌린다(#405) — 지난 시도·통과는 손대지 않고 상태만
    되돌린다. `open_problem`과 같은 필수 항목 규칙을 다시 확인한다: 그
    사이 강사가 체크리스트를 비웠으면 통과가 정의되지 않아 열 수 없다."""

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    problem = execute_transition("reopen", scope.problem)
    return 200, _serialize_problem(problem, scope.class_obj, viewer_id=request.auth_user.id)


# --- Submission (참여자, #286) --------------------------------------------------


def _get_member_or_404(class_id: int, user_id: int) -> ClassMember:
    """강사 전용 엔드포인트의 `instructor_scope.class_scope`와 같은 존재-숨김
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
    클래스에 이미 적어 둔 그 강사의 이름(소유자면 클래스의 강사 이름, 공동 강사면
    수락할 때 정한 이름)을 그대로 쓴다.

    보관된 클래스에서는 행을 만들지 않는다 — 읽기 전용이라 어차피 제출이
    403이고, 없던 행을 남기지 않는 편이 정직하다."""

    try:
        return ClassMember.objects.select_related("classroom").get(
            classroom_id=class_id, user_id=user_id
        )
    except ClassMember.DoesNotExist:
        pass

    class_obj = classes_taught_by(user_id).filter(id=class_id).first()
    if class_obj is None:
        raise HttpError(404, "문제를 찾을 수 없습니다.")
    if class_obj.archived_at is not None:
        raise HttpError(403, "이 클래스는 보관되어 새 제출을 받지 않습니다.")

    member, _created = ClassMember.objects.get_or_create(
        classroom=class_obj,
        user_id=user_id,
        defaults={"display_name": instructor_display_name_of(class_obj, user_id) or "강사"},
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
        pending_scoring.with_rejection(ClassroomSubmission.objects.filter(problem=problem, member=member))
        .select_related("classroom_score").prefetch_related(current_score_prefetch()).defer(*_SCORE_PROMPT)
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
    #429 개정) — 초안·열림·숨김 어디서든 낼 수 있으므로 보통은 `None`이다.
    막는 것은 보관된 클래스 하나뿐이다(읽기 전용, CONTEXT.md 「클래스」) —
    참여자와 같은 이유·같은 문구다. 판정 자체는
    `classroom.participation.instructor_can_submit`이 한 곳에서 한다."""

    return None if instructor_can_submit(class_obj, problem) else SUBMIT_BLOCKED_ARCHIVED


@router.get(
    "/classes/{class_id}/problems/{problem_id}/contest-entry",
    response={200: ContestEntryFormOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_contest_entry_form(request: HttpRequest, class_id: int, problem_id: int):
    """참여자의 「공모전에도 내기」 칸(#549) — 직전 공모전 제출로 미리 채운다. 공모전 문제가
    아니면 404. 그 클래스의 강사도 본인 명의로 낼 수 있다(#878) — 강사는 자기 문제를
    상태와 무관하게 찾는다(`create_classroom_submission` 과 같은 문)."""

    instructor_class = classes_taught_by(request.auth_user.id).filter(id=class_id).first()
    if instructor_class is not None:
        problem = owned_problem_or_404(instructor_class, problem_id)
    else:
        member = _get_member_or_404(class_id, request.auth_user.id)
        problem = _get_visible_problem_for_participant_or_404(class_id, problem_id, member)
    if problem.contest_id is None:
        raise HttpError(404, "공모전 문제가 아닙니다.")
    return 200, contest_entry_form(problem, request.auth_user.id)


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
    문제를 내려준다. 강사 판정은 `classroom.instructors.classes_taught_by`가 한다.

    **열린 문제에는 강사도 낸다**(2026-09-17, #429 개정). 예전에는 이 분기가
    시도 목록을 언제나 빈 배열로 주고 제출을 막힌 것으로 표시해, 강사가 자기
    문제를 직접 내 볼 길이 화면에 없었다 — 가입 링크로 자기 클래스 참여자가
    되어 있어도 그랬다. 이제 **자기 시도는 그대로 보이고**(남의 시도는 여전히
    이 질의에 없다), 문제가 열려 있고 클래스가 보관되지 않았으면 제출 잠금이
    풀린다. 「강사가 보는 중」은 `viewing_as_instructor`가 따로 말한다 —
    초안·숨김처럼 참여자라면 못 낼 상태에서는 그 사유가 여전히 잠금을 건다.
    명단·달성률이 강사를 세지 않는 것은 그대로다(#290 — 강사 행은
    격자에 표시만 되고 집계에서 빠진다)."""

    # 강사 전용 라우트가 아니다 — 참여자와 강사가 같은 주소를 걷는 혼합
    # 라우트라 `instructor_scope.class_scope`(404로 존재를 숨기는 강사 전용
    # 문)가 아니라 `.filter(...).first()`로 확인한다: 강사가 아니면 아래
    # 참여자 경로로 그대로 흘러간다.
    instructor_class = classes_taught_by(request.auth_user.id).filter(id=class_id).first()
    if instructor_class is not None:
        class_obj = instructor_class
        problem = owned_problem_or_404(class_obj, problem_id)
        member = ClassMember.objects.filter(
            classroom=class_obj, user_id=request.auth_user.id
        ).first()
        checklist_items = list(problem.checklist_items.all())
        submissions = _serialize_own_submissions(
            problem, member, request.auth_user, checklist_items
        )
        return 200, ClassroomProblemSubmissionsOut(
            class_name=class_obj.name,
            max_source_asset_bytes=get_current_policy().max_source_asset_bytes,
            problem=_serialize_problem_mine(
                problem,
                passed=any(s.passed for s in submissions),
                perfect=_serialized_perfect(submissions, checklist_items),
            ),
            submissions=submissions,
            # 낼 수 있는 상태가 아니면 그 이유를 말한다 — 보관이 먼저다
            # (참여자와 같은 우선순위), 초안·숨김은 참여자에게 애초에 보이지
            # 않는 상태라 「강사가 보는 중」이 그 자리를 대신한다.
            submit_blocked_reason=_instructor_submit_blocked_reason(class_obj, problem),
            instructor_problem_status=problem.status,
            viewing_as_instructor=True,
            viewer_role="owner" if is_owner(class_obj, request.auth_user.id) else "co_instructor",
        )

    member = _get_member_or_404(class_id, request.auth_user.id)
    problem = _get_visible_problem_for_participant_or_404(class_id, problem_id, member)
    checklist_items = list(problem.checklist_items.all())

    serialized_submissions = _serialize_own_submissions(
        problem, member, request.auth_user, checklist_items
    )
    return 200, ClassroomProblemSubmissionsOut(
        class_name=problem.classroom.name,
        max_source_asset_bytes=get_current_policy().max_source_asset_bytes,
        # 문제 자체의 통과 여부는 시도 전체의 OR이다(#288 AC "한 번 통과하면
        # 유지된다") — 최신 시도만 보지 않는다.
        problem=_serialize_problem_mine(
            problem,
            passed=any(s.passed for s in serialized_submissions),
            perfect=_serialized_perfect(serialized_submissions, checklist_items),
        ),
        submissions=serialized_submissions,
        # 내보내진 사람도 지난 시도는 그대로 읽되(#300 AC), 화면이 제출
        # 수단을 감추고 이유를 말해 줄 수 있도록 이유 하나만 얹는다(#439,
        # 우선순위는 보관 → 내보냄 → 숨김) — 막는 문 자체는 여전히
        # `create_classroom_submission`의 403이다.
        submit_blocked_reason=participant_submit_blocked_reason(member.classroom, member, problem),
    )


def _enqueue_immediate_scoring(submission_id: int) -> None:
    """시도 하나의 채점 태스크를 큐에 넣는다(#378, #582, ADR-0056) — 큐에 넣은 시각도 함께
    찍어 60초 스캔이 같은 시도를 또 넣지 않게 한다(`classroom.scoring.enqueue_scoring`).
    dev·CI(eager)에서는 이 자리에서 채점까지 끝난다.

    **발행이 실패해도 제출을 실패시키지 않는다** — 이 콜백은 트랜잭션이 커밋된 뒤에 돌므로
    시도는 이미 저장됐고, 60초 스캔이 그 시도를 줍는다(안전망). 여기서 예외가 튀면 참여자는
    저장된 시도에 500 을 받고 다시 내 시도가 중복된다 — 브로커(Redis)가 재시작 중일 때 실제로
    그렇게 된다."""

    try:
        enqueue_scoring(submission_id, as_of=Clock.now())
    except Exception:  # noqa: BLE001 — 어떤 브로커 오류든 스캔이 대신 줍는다
        logger.warning(
            "강의실 채점 작업을 큐에 넣지 못했다 — 스캔이 줍는다 (submission_id=%s)",
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
    """제출할 때마다 새 시도가 쌓인다 — 시도 횟수 상한은 없다(ADR-0039, CONTEXT.md
    「Problem」). 마감(`Problem.due_at`)이 지나도 제출할 수 있고
    늦음 표시만 바뀐다(#941). 근거 연결도 자가 체크도 없다: 소스
    또는 저장소 값 하나만 받는다."""

    # 오류에는 식별자만 싣는다(#590) — 제출 값은 요청 본문이라 원래 보내지 않는다.
    tag_error_scope("classroom_submission", class_id=class_id, problem_id=problem_id)
    # **강사와 참여자는 다른 문을 지난다**(2026-09-17, #429 개정). 강사는 자기
    # 문제를 상태와 무관하게 내 볼 수 있고(초안·열림·숨김), 참여자에게는 그
    # 상태들이 각각 404·403이다 — 그래서 문제를 찾는 질의부터 갈린다.
    instructor_class = classes_taught_by(request.auth_user.id).filter(id=class_id).first()
    if instructor_class is not None:
        problem = owned_problem_or_404(instructor_class, problem_id)
        blocked_reason = _instructor_submit_blocked_reason(instructor_class, problem)
        if blocked_reason == SUBMIT_BLOCKED_ARCHIVED:
            raise HttpError(403, "이 클래스는 보관되어 새 제출을 받지 않습니다.")
        member = _get_submitting_member_or_404(class_id, request.auth_user.id)
        return _create_submission_row(request, problem, member, payload)

    member = _get_member_or_404(class_id, request.auth_user.id)
    problem = _get_visible_problem_for_participant_or_404(class_id, problem_id, member)

    # 낼 수 있는가는 참여 정책 모듈이 한 곳에서 답한다(#439) — 우선순위는
    # 보관 → 내보냄 → 숨김 → 마감이고, 화면의 `submit_blocked_reason`과 여기 문이
    # 같은 기준이어야 어긋나지 않는다.
    blocked_reason = participant_submit_blocked_reason(member.classroom, member, problem)
    if blocked_reason == SUBMIT_BLOCKED_ARCHIVED:
        # #294 AC "보관된 클래스에는 새 제출을 낼 수 없다" — 지난 시도는
        # 그대로 읽히므로(`get_my_problem`) 이 엔드포인트만 막는다.
        raise HttpError(403, "이 클래스는 보관되어 새 제출을 받지 않습니다.")
    if blocked_reason in (SUBMIT_BLOCKED_EXPELLED, SUBMIT_BLOCKED_LEFT):
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

    return _create_submission_row(request, problem, member, payload)


def _create_submission_row(request: HttpRequest, problem, member, payload):
    """값을 검증하고 시도 하나를 만든다 — 참여자와 강사(2026-09-17)가 같은
    코드를 지난다. 「낼 수 있는가」는 호출부가 이미 서로 다른 기준으로
    판정했다(참여자는 보관·내보냄·숨김, 강사는 보관 하나)."""

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
        # 저장소 · `/tree/<브랜치>` · `/commit/<sha>` 셋을 받는다(#777). 저장은 저장소 URL 과
        # ref·SHA 로 나뉘고, 공모전에도 내기(#549)에는 낸 URL 그대로 넘겨 공모전 쪽이 같은
        # 규칙으로 다시 나눈다.
        target = parse_github_submission_url(value)
        if target is None:
            raise HttpError(422, REPOSITORY_URL_SHAPES_MESSAGE)
        value = target.url
        asset_kind = SubmissionAsset.Kind.REPOSITORY

    # 「공모전에도 내기」(#549) — 시도를 만들기 전에 거른다. 끄고 낸 시도면 None.
    contest_entry = prepare_contest_entry(
        problem=problem,
        user_id=request.auth_user.id,
        entry_in=payload.contest_entry,
        scoring_asset=EntryAsset(kind=asset_kind, value=value, content_type=content_type),
    )
    asset_fields = (
        {
            "value": target.repo_url,
            "repository_ref": target.ref,
            "repository_commit_sha": target.commit_sha,
        }
        if asset_kind == SubmissionAsset.Kind.REPOSITORY
        else {"value": value}
    )

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
            submission=submission, kind=asset_kind, content_type=content_type, **asset_fields
        )
        # 이 시도가 생겼다는 신호를 그 참여자와 그 클래스 강사에게 낸다
        # (#383, ADR-0046) — 강사 제출 현황이 새로고침 없이 새 시도를 보여줄
        # 수 있게 한다. 커밋 뒤 발행 규율은 `publish_attempt_submitted`
        # 안에 있다(아래 즉시 채점 큐잉과 같은 이유로 `on_commit`을 쓴다).
        publish_attempt_submitted(submission)
        # 이 시도의 채점을 곧바로 큐에 넣는다(#378, #582) — 60초 스캔을
        # 기다리지 않는다. `on_commit`인 이유는 트랜잭션이 아직 커밋되지
        # 않았을 때 태스크가 먼저 돌면(워커가 있는 배포 환경에서는 그럴 수
        # 있다) 채점 워커가 아직 존재하지 않는 시도를 찾다 건너뛰기 때문이다.
        # dev·CI는 eager 라 이 콜백 안에서 채점까지 끝난다(ADR-0056).
        transaction.on_commit(lambda: _enqueue_immediate_scoring(submission.id))
        # 채점 연결이 없어 이 시도가 멈추면 소유자에게 한 번 알린다(#1389) — 커밋 뒤라 제출의 잠금을 쥐고 있지 않고,
        # 실패해도 제출은 실패하지 않는다(60초 스캔이 다시 한다). 강사 본인 시도만으로는 알리지 않는다(그 판정은 안에서).
        transaction.on_commit(lambda: alert_missing_key_safely(problem.classroom_id))
        if contest_entry is not None:
            # 커밋된 뒤 공모전에 보낸다 — 결과는 신호로 돌아와 이 시도에 남는다.
            request_contest_entry(submission, contest_entry)

    if contest_entry is not None:
        # 결과 신호가 커밋 콜백 안에서 이미 돌아왔다 — 응답에 그 결과를 싣는다.
        submission.refresh_from_db(
            fields=["contest_entry_status", "contest_entry_reason", "contest_entry_resolved_at"]
        )

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

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=False, owner=False)
    class_obj, problem = scope.class_obj, scope.problem
    checklist_items = list(problem.checklist_items.all())

    submissions = (
        pending_scoring.with_rejection(ClassroomSubmission.objects.filter(problem=problem))
        .select_related("classroom_score", "member").prefetch_related(current_score_prefetch())
        .prefetch_related("assets")
        .order_by("member__display_name", "-attempt_number")
    )
    marks = entry_marks([problem])
    return 200, [
        _serialize_instructor_submission(
            # `_mine`과 같은 이유로 리스트를 먼저 받아 prefetch 캐시를 쓴다.
            s,
            asset=list(s.assets.all())[0],
            class_obj=class_obj,
            problem=problem,
            checklist_items=checklist_items,
            marks=marks,
        )
        for s in submissions
    ]
# --- 완성도(#883, ADR-0072) ---------------------------------------------------------------


def _quality_item_outs(items) -> list[QualityItemOut]:
    return [QualityItemOut(**item) for item in items]


@router.get(
    "/classes/{class_id}/problems/{problem_id}/quality",
    response={200: QualityBoardOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_problem_quality(request: HttpRequest, class_id: int, problem_id: int):
    """강사의 「완성도 순위」 — 등수·참여자·완성도·항목별 0~5·근거. 대상이 아닌(통과 못 한) 참여자는 없다."""

    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=False, owner=False).problem
    current = quality.board(problem)
    return 200, QualityBoardOut(
        quality_public=problem.quality_public,
        target_count=len(current.targets),
        queued_count=sum(1 for t in current.targets if t.queued),
        failed_count=sum(1 for t in current.targets if t.failed),
        failed_names=sorted(t.submission.member.display_name for t in current.targets if t.failed),
        rows=[
            QualityRankRowOut(**{**row, "items": _quality_item_outs(row["items"])})
            for row in quality.ranking(current)
        ],
    )


@router.get(
    "/classes/{class_id}/problems/{problem_id}/quality/estimate",
    response={200: QualityEstimateOut, 404: ErrorOut},
    auth=jwt_auth,
)
def estimate_problem_quality(request: HttpRequest, class_id: int, problem_id: int):
    """「완성도 채점」을 누르기 전의 확인 — 새로 채점할 n명과 예상 비용."""

    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=False, owner=False).problem
    result = quality.estimate(problem)
    return 200, QualityEstimateOut(
        new_count=result.new_count,
        reuse_count=result.reuse_count,
        cost_krw=result.cost_krw,
        blocked_reason=result.blocked_reason,
    )


@router.post(
    "/classes/{class_id}/problems/{problem_id}/quality/run",
    response={200: QualityRunOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def run_problem_quality(request: HttpRequest, class_id: int, problem_id: int):
    """확인한 뒤 큐에 넣는다 — 대상 시도가 바뀐 사람(과 체크리스트를 고친 뒤의 모두)만. 비용이 강사 키에
    나가므로 쓰기로 다룬다(보관된 클래스에서는 403)."""

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    reason = pending_scoring.blocking_reason(scope.class_obj, scope.problem)
    if reason is not None:
        return 409, ErrorOut(detail=quality.BLOCKED_MESSAGES[reason])
    return 200, QualityRunOut(queued_count=quality.enqueue(scope.problem, as_of=Clock.now()))


@router.put(
    "/classes/{class_id}/problems/{problem_id}/quality/bonus/{submission_id}/{item_id}",
    response={200: ClassroomBonusScoreOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def rate_problem_bonus(
    request: HttpRequest,
    class_id: int,
    problem_id: int,
    submission_id: int,
    item_id: int,
    payload: ClassroomBonusScoreIn,
):
    """강사·공동 강사가 가산 하나에 0~5 와 한 줄 메모를 매긴다(#905, ADR-0073) — 그 참여자의 **지금 완성도
    대상 시도**에만(아니면 409). 보관된 클래스에서는 403(쓰기). 문제 마감은 막지 않는다."""

    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False)
    try:
        row = quality.save_bonus_score(
            scope.problem,
            submission_id=submission_id,
            item_id=item_id,
            score=payload.score,
            memo=payload.memo,
            rated_by_id=request.auth_user.id,
        )
    except quality.BonusTargetError as exc:
        return 409, ErrorOut(detail=str(exc))
    return 200, ClassroomBonusScoreOut(
        submission_id=row.submission_id, item_id=row.item_id, score=row.score, memo=row.memo
    )


@router.get(
    "/classes/{class_id}/problems/{problem_id}/quality/mine",
    response={200: MyQualityOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_my_problem_quality(request: HttpRequest, class_id: int, problem_id: int):
    """참여자 본인의 「완성도 순위 k등 / N명」·항목별. 공개가 꺼졌거나 본인 기록이 없으면 404 — 완성도는
    참여자 응답 어디에도 실리지 않는다. 다른 참여자의 이름·점수는 이 응답에 없다."""

    member = _get_member_or_404(class_id, request.auth_user.id)
    problem = _get_visible_problem_for_participant_or_404(class_id, problem_id, member)
    if not problem.quality_public:
        return 404, ErrorOut(detail="공개된 완성도가 없습니다.")
    mine = quality.my_row(quality.board(problem), member)
    if mine is None:
        return 404, ErrorOut(detail="공개된 완성도가 없습니다.")
    row, total = mine
    # 「가산 다시 매김 필요」는 강사 화면 몫이라 `MyQualityOut` 에 칸이 없다.
    return 200, MyQualityOut(
        rank=row["rank"],
        total=total,
        score_total=row["total"],
        max_total=row["max_total"],
        completeness=row["completeness"],
        # 숨은 항목(#906)은 「숨은 항목 k」와 점수만.
        items=_quality_item_outs(
            mask_hidden_quality_items(row["items"], set(problem.checklist_items.filter(hidden=True).values_list("id", flat=True)))
        ),
    )


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
    가져올 수 없다", #438) — `instructor_scope.class_scope(..., write=True)`가
    `problem_templates.import_template`과 같은 규칙을 여기서도 지킨다: 보관은
    읽기 전용이라는 뜻이라 복사도 예외가 아니다. 원본은 읽기만 하므로
    `write=False`다 — 보관된 클래스에서 다른 곳으로 복사해 가져오는 것은
    막지 않는다(위 `list_importable_problems`와 같은 원칙)."""

    source = problem_scope(class_id, problem_id, request.auth_user.id, write=False, owner=False)
    problem = source.problem
    target_class = class_scope(payload.target_class_id, request.auth_user.id, write=True, owner=False).class_obj

    copy = copy_problem_to_class(problem, target_class)
    return 201, _serialize_problem(copy, target_class, viewer_id=request.auth_user.id)


# --- ChecklistItem -------------------------------------------------------------


@router.post(
    "/classes/{class_id}/problems/{problem_id}/checklist-items",
    response={201: ChecklistItemSavedOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def create_checklist_item(
    request: HttpRequest, class_id: int, problem_id: int, payload: ChecklistItemIn
):
    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False).problem
    item = problem_authoring.add_checklist_item(problem, payload)
    return 201, _serialize_saved_checklist_item(item)


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

    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False).problem
    ordered = problem_authoring.reorder_checklist_items(problem, payload.item_ids)
    return 200, [_serialize_checklist_item(i) for i in ordered]


@router.patch(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
    response={200: ChecklistItemSavedOut, 404: ErrorOut, 422: ErrorOut},
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

    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False).problem
    item = problem_authoring.update_checklist_item(problem, item_id, payload)
    return 200, _serialize_saved_checklist_item(item, text_changed=payload.label is not None)


@router.delete(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
    response={204: None, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def delete_checklist_item(request: HttpRequest, class_id: int, problem_id: int, item_id: int):
    """열린·숨긴 문제의 마지막 필수 항목은 지울 수 없다(#440) —
    `assert_required_item_floor`와 같은 이유, `update_checklist_item`과
    같은 규율(초안은 예외)."""

    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=True, owner=False).problem
    problem_authoring.delete_checklist_item(problem, item_id)
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

#: 스트림 하나의 최대 수명(2026-09-18) — 넘기면 스스로 끝내고, 브라우저의
#: `EventSource`가 곧바로 다시 연결한다(사용자에게는 보이지 않는다).
#:
#: **왜 상한을 두는가.** 브라우저가 떠나도 앞단이 위쪽 요청을 끊지 못하면
#: 이 요청은 영원히 끝나지 않는다 — 2026-09-18 prod 에서 이벤트 서비스가
#: 유휴 연결 100개를 쥐어 Postgres 가 `too many clients already`로 **모든**
#: 요청을 거절했다(공개 앱 500, celery 포함). 앞단(강의실 BFF)이 이제
#: 브라우저의 끊김을 위로 전하지만(`classroom/lib/proxy/forward.ts`), 그
#: 길이 또 새더라도 이 상한이 스스로 회복시킨다.
#:
#: **DB 연결은 더 이상 이 상한에 기대지 않는다(#454).** 스트림이 시작되면
#: 그 자리에서 바로 연결을 놓으므로(`_release_db_connection_for_stream`),
#: 이 요청이 끝나지 않아도 DB 연결은 묶이지 않는다. 그래도 상한을 남기는
#: 이유는 끝나지 않는 요청 자체가 여전히 asyncio 태스크·소켓·(#456 전에는)
#: 스레드 풀 한 자리를 쥐기 때문이다 — 그 자원들도 무한정 쌓이면 안 된다.
#:
#: 30분인 이유: 실시간 신호가 그만큼 끊겨도 화면은 폴링으로 물러나 있고
#: (ADR-0046 "신호는 진실의 출처가 아니다"), 재연결 한 번의 비용은 요청
#: 하나다. 더 짧게 잡으면 재연결이 잦아 그 비용이 커진다.
_SSE_MAX_LIFETIME_SECONDS = 30 * 60.0


def _format_sse_event(event: Event) -> bytes:
    return f"event: {event.kind}\ndata: {json.dumps(event.payload)}\n\n".encode("utf-8")


def _release_db_connection_for_stream() -> None:
    """인증 미들웨어가 연 이 요청의 DB 연결을 놓는다(#454).

    ASGI 요청 하나는 `ThreadSensitiveContext` 하나를 쓰고(Django), 그 안의
    동기 코드(인증 미들웨어의 `User.objects.filter`)는 이 요청 전용의 실제
    스레드 하나에서 돈다 — DB 연결은 `thread_critical` 스토리지라 그 스레드에
    묶인다. 스트림은 그 뒤로 DB 를 한 번도 쓰지 않으므로, 여기서 그 스레드의
    연결을 닫아 두지 않으면 Django 는 요청이 완전히 끝날 때(스트림이 최대
    30분 흐른 뒤)까지 연결을 쥔 채로 둔다 — 동시 시청자 수만큼 DB 연결이
    쌓이는 원인이었다(2026-09-18 prod 장애)."""

    connections.close_all()


async def _stream_events_for(recipient_id: int):
    """**반드시 async 제너레이터다.** 동기 제너레이터로 두면 Django의 ASGI
    핸들러가 "StreamingHttpResponse must consume synchronous iterators in
    order to serve them asynchronously" 경고와 함께 완전히 다른(뒤로
    미뤄지는) 소비 경로를 타 실제로는 아무것도 실시간으로 나가지 않는다 —
    dev 스택에서 실제 요청으로 직접 확인했다(연결은 200 으로 열리지만
    keep-alive 조차 15초·20초 뒤에도 도착하지 않았다).

    **`bus.subscribe`·`poll`은 비동기 계약이다(#456).** 실물 어댑터
    (`core.events_redis.RedisEventBus`)는 `redis.asyncio`로 폴링해 스레드를
    쓰지 않는다 — 스트림 하나가 이벤트 서비스의 스레드 풀(기본 8개) 한
    자리를 붙잡지 않으므로, 동시 시청자가 그 수를 넘어도 신호가 늦지 않는다
    (2026-09-18 이전에는 9번째 시청자부터 최대 15초씩 늦었다).

    **DB 연결을 놓은 뒤에 구독한다(#454).** `bus.subscribe`·`poll`은 Redis만
    쓰고 DB를 건드리지 않으므로, 인증에서 연 연결을 여기서 놓아도 스트림
    동작은 그대로다. 놓기가 실패해도(스레드 경계·테스트 트랜잭션 등) 삼키고
    계속한다 — 연결 하나를 못 놓는 것보다 신호가 끊기는 쪽이 나쁘다."""

    try:
        await sync_to_async(_release_db_connection_for_stream, thread_sensitive=True)()
    except Exception:  # noqa: BLE001 — 놓기 실패가 신호 흐름을 막으면 안 된다
        logger.warning("스트림 시작 시 DB 연결을 놓지 못했다", exc_info=True)

    bus = get_event_bus()
    deadline = time.monotonic() + _SSE_MAX_LIFETIME_SECONDS
    try:
        async with bus.subscribe(recipient_id) as subscription:
            while time.monotonic() < deadline:
                events = await subscription.poll(timeout=_SSE_KEEPALIVE_SECONDS)
                if not events:
                    yield b": keep-alive\n\n"
                    continue
                for event in events:
                    yield _format_sse_event(event)
    except EventBusDisconnected:
        # 배포가 redis 를 바꿔 끼우는 몇 초에 흐르던 스트림이 다 여기로 온다
        # (GlitchTip 오류 67). 스트림을 끝내면 브라우저가 다시 연결하고, 그
        # 사이 화면은 폴링으로 맞춰진다 — 오류로 보낼 일이 아니다. 구독 자체를
        # 못 여는 것(redis 가 계속 없다)은 여기 오지 않고 그대로 오류로 간다.
        logger.warning("실시간 신호 버스 연결이 끊겨 스트림을 끝낸다", exc_info=True)


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
