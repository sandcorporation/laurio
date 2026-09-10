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

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core.crypto import encrypt
from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename, safe_download_base_name
from submissions.models import GITHUB_REPO_URL_PATTERN, Submission, SubmissionAsset

from .models import (
    ChecklistItem,
    Class,
    ClassMember,
    ClassroomScore,
    ClassroomSubmission,
    Problem,
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
    ClassroomProblemMineOut,
    ClassroomProblemSubmissionsOut,
    ClassroomScoreOut,
    ClassroomSubmissionIn,
    ClassroomSubmissionOut,
    ErrorOut,
    JoinIn,
    JoinLinkOut,
    JoinPreviewOut,
    JoinResultOut,
    MemberOut,
    OpenAIKeyIn,
    ProblemIn,
    ProblemOut,
    ProblemPatchIn,
    ProblemReorderIn,
    ScoringModelOut,
)
from .scoring_models import SCORING_MODEL_CHOICES, is_valid_model
from .submission_target_refs import source_target_ref

router = Router(tags=["classroom"])

_SUBMISSION_FORMATS = {choice for choice, _label in Problem.SubmissionFormat.choices}

#: 마스킹은 복호화가 아니라 저장 시점에 남긴 마지막 네 자리로만 만든다 —
#: `Class.openai_api_key_encrypted`를 다시 풀지 않는다(#284, 파일 상단 라우터
#: docstring과 같은 이유: 복호화는 채점 요청을 보낼 때만 한다).
_KEY_MASK_PREFIX = "••••••••"


def _mask_from_last4(last4: str) -> str:
    return f"{_KEY_MASK_PREFIX}{last4}"


def _serialize_class(class_obj: Class) -> ClassOut:
    has_key = bool(class_obj.openai_api_key_encrypted)
    return ClassOut(
        id=class_obj.id,
        name=class_obj.name,
        join_code=class_obj.join_code,
        created_at=class_obj.created_at,
        default_model=class_obj.default_model,
        has_openai_key=has_key,
        openai_key_masked=_mask_from_last4(class_obj.openai_api_key_last4) if has_key else None,
    )


def _serialize_checklist_item(item: ChecklistItem) -> ChecklistItemOut:
    return ChecklistItemOut(id=item.id, label=item.label, required=item.required, order=item.order)


def _serialize_problem(problem: Problem, class_obj: Class) -> ProblemOut:
    return ProblemOut(
        id=problem.id,
        classroom_id=problem.classroom_id,
        title=problem.title,
        description=problem.description,
        submission_format=problem.submission_format,
        status=problem.status,
        order=problem.order,
        model=problem.model,
        effective_model=problem.model or class_obj.default_model,
        checklist_items=[_serialize_checklist_item(i) for i in problem.checklist_items.all()],
    )


def _serialize_problem_mine(problem: Problem) -> ClassroomProblemMineOut:
    return ClassroomProblemMineOut(
        id=problem.id,
        classroom_id=problem.classroom_id,
        title=problem.title,
        description=problem.description,
        submission_format=problem.submission_format,
        checklist_items=[_serialize_checklist_item(i) for i in problem.checklist_items.all()],
    )


def _source_download_url(asset: SubmissionAsset, user) -> str:
    """소스 자료 하나의 presigned 다운로드 URL — 파일명은 제출자 본인의 User
    정보를 따른다(#286 AC). 강의실 참여자는 `accounts.DeveloperProfile`이
    없으므로 `contests.assignment_api`처럼 `developer.display_name`을 쓸 수
    없다 — 대신 `User.email`을 쓴다(`classroom.api.preview_join`이 강사를
    가리킬 때 이미 같은 값을 쓰고 있다)."""

    adapter = get_storage_adapter()
    base_name = safe_download_base_name(user.email)
    presigned = adapter.presign_download(
        asset.value,
        filename=build_download_filename(asset.content_type or None, base_name=base_name),
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )
    return presigned.url


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
        created_at=score.created_at,
    )


def _serialize_classroom_submission(
    submission: ClassroomSubmission, *, asset: SubmissionAsset, user
) -> ClassroomSubmissionOut:
    download_url = (
        _source_download_url(asset, user) if asset.kind == SubmissionAsset.Kind.SOURCE else None
    )
    score = getattr(submission, "classroom_score", None)
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
    class_obj = Class.objects.create(instructor_id=request.auth_user.id, name=payload.name)
    return 201, _serialize_class(class_obj)


@router.get("/classes", response={200: list[ClassOut]}, auth=jwt_auth)
def list_my_classes(request: HttpRequest):
    """「내 클래스」— 본인이 강사인 것만. 남의 클래스는 여기 나오지 않는다."""

    classes = Class.objects.filter(instructor_id=request.auth_user.id)
    return 200, [_serialize_class(c) for c in classes]


@router.get("/classes/{class_id}", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def get_class(request: HttpRequest, class_id: int):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    return 200, _serialize_class(class_obj)


@router.patch(
    "/classes/{class_id}", response={200: ClassOut, 404: ErrorOut, 422: ErrorOut}, auth=jwt_auth
)
def update_class(request: HttpRequest, class_id: int, payload: ClassPatchIn):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)

    if payload.default_model is not None and not is_valid_model(payload.default_model):
        raise HttpError(422, f"알 수 없는 채점 모델입니다: {payload.default_model}")

    update_fields = []
    if payload.name is not None:
        class_obj.name = payload.name
        update_fields.append("name")
    if payload.default_model is not None:
        class_obj.default_model = payload.default_model
        update_fields.append("default_model")
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
    본인 전용이다. 응답은 마스킹된 `ClassOut`뿐, 평문은 어디에도 싣지 않는다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)

    raw_key = payload.api_key.strip()
    if not raw_key:
        raise HttpError(422, "채점 키를 입력해주세요.")

    class_obj.openai_api_key_encrypted = encrypt(raw_key)
    class_obj.openai_api_key_last4 = raw_key[-4:]
    class_obj.save(update_fields=["openai_api_key_encrypted", "openai_api_key_last4"])
    return 200, _serialize_class(class_obj)


@router.get("/scoring-models", response={200: list[ScoringModelOut]}, auth=jwt_auth)
def list_scoring_models(request: HttpRequest):
    """「채점 설정」 화면이 선택지마다 컨텍스트 크기를 함께 보여주는 자리(#285)."""

    return 200, [
        ScoringModelOut(id=c.id, label=c.label, context_window=c.context_window)
        for c in SCORING_MODEL_CHOICES
    ]


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
    판단할 수 있어야 한다(#280 AC)."""

    class_obj = _get_class_by_join_code_or_404(join_code)
    # `members.count()`는 강사 본인이 가입했으면 그 행도 센다 — CONTEXT.md
    # 「ClassMember」가 강사를 빼라고 정한 것은 **달성률**의 분모뿐이다(그
    # 계산은 아직 없는 티켓의 몫이다). 이 미리보기의 "참여자 수"는 그
    # 지표가 아니라 문자 그대로 "이 클래스에 누가 있는가"라 뺄 이유가
    # 없다.
    return 200, JoinPreviewOut(
        class_name=class_obj.name,
        instructor_email=class_obj.instructor.email,
        problem_count=class_obj.problems.count(),
        participant_count=class_obj.members.count(),
    )


@router.post(
    "/join/{join_code}", response={200: JoinResultOut, 404: ErrorOut, 422: ErrorOut}, auth=jwt_auth
)
def join_class(request: HttpRequest, join_code: str, payload: JoinIn):
    """가입과 클래스 가입이 한 흐름이다 — 계정이 있으면(로그인 되어 있으면)
    이 요청 하나로 끝난다. 이미 참여자면 새로 만들지 않고 그 행을 그대로
    돌려준다(#280 AC "같은 사람이 같은 클래스에 두 번 들어가지 않는다") —
    두 번째 이름은 버려진다, 첫 가입 때 정한 이름이 그 클래스에서의 정체성이기
    때문이다."""

    class_obj = _get_class_by_join_code_or_404(join_code)
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


# --- Problem -------------------------------------------------------------------


@router.post(
    "/classes/{class_id}/problems",
    response={201: ProblemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def create_problem(request: HttpRequest, class_id: int, payload: ProblemIn):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)

    if payload.submission_format not in _SUBMISSION_FORMATS:
        raise HttpError(422, f"알 수 없는 제출 형식입니다: {payload.submission_format}")

    next_order = class_obj.problems.count()
    problem = Problem.objects.create(
        classroom=class_obj,
        title=payload.title,
        description=payload.description,
        submission_format=payload.submission_format,
        order=next_order,
    )
    return 201, _serialize_problem(problem, class_obj)


@router.get(
    "/classes/{class_id}/problems", response={200: list[ProblemOut], 404: ErrorOut}, auth=jwt_auth
)
def list_problems(request: HttpRequest, class_id: int):
    """강사 본인의 클래스 문제 전부(초안 + 열림), 순서대로."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problems = class_obj.problems.prefetch_related("checklist_items").all()
    return 200, [_serialize_problem(p, class_obj) for p in problems]


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
    problems = {p.id: p for p in class_obj.problems.all()}

    if set(payload.problem_ids) != set(problems):
        raise HttpError(422, "이 클래스의 문제 목록과 일치하지 않습니다.")

    with transaction.atomic():
        for index, problem_id in enumerate(payload.problem_ids):
            problem = problems[problem_id]
            problem.order = index
        Problem.objects.bulk_update(problems.values(), ["order"])

    ordered = sorted(problems.values(), key=lambda p: p.order)
    return 200, [_serialize_problem(p, class_obj) for p in ordered]


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

    if payload.submission_format is not None and payload.submission_format not in _SUBMISSION_FORMATS:
        raise HttpError(422, f"알 수 없는 제출 형식입니다: {payload.submission_format}")
    if payload.model and not is_valid_model(payload.model):
        raise HttpError(422, f"알 수 없는 채점 모델입니다: {payload.model}")

    update_fields = []
    if payload.title is not None:
        problem.title = payload.title
        update_fields.append("title")
    if payload.description is not None:
        problem.description = payload.description
        update_fields.append("description")
    if payload.submission_format is not None:
        problem.submission_format = payload.submission_format
        update_fields.append("submission_format")
    if payload.model is not None:
        problem.model = payload.model
        update_fields.append("model")
    if update_fields:
        problem.save(update_fields=[*update_fields, "updated_at"])
    return 200, _serialize_problem(problem, class_obj)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/open",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def open_problem(request: HttpRequest, class_id: int, problem_id: int):
    """초안을 연다. 필수 체크리스트 항목이 하나도 없으면 통과가 정의되지
    않아 막는다(#283 AC)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)

    if not problem.checklist_items.filter(required=True).exists():
        raise HttpError(400, "필수 항목이 하나도 없는 문제는 열 수 없습니다.")

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
        return ClassMember.objects.get(classroom_id=class_id, user_id=user_id)
    except ClassMember.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


def _get_open_problem_for_participant_or_404(class_id: int, problem_id: int) -> Problem:
    """참여자에게는 열린 문제만 존재한다 — 초안은 강사만 본다(Problem
    docstring). 남의 클래스와 같은 이유로 404다."""

    try:
        return Problem.objects.prefetch_related("checklist_items").get(
            id=problem_id, classroom_id=class_id, status=Problem.Status.OPEN
        )
    except Problem.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


@router.get(
    "/classes/{class_id}/problems/{problem_id}/mine",
    response={200: ClassroomProblemSubmissionsOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_my_problem(request: HttpRequest, class_id: int, problem_id: int):
    """참여자가 보는 문제 하나 — 체크리스트와 본인의 시도 목록(#286). 남의
    시도는 애초에 이 질의에 없다(`member=member` 필터) — "남의 제출물을 볼 수
    없다"는 AC를 별도 권한 검사가 아니라 쿼리 모양으로 지킨다."""

    member = _get_member_or_404(class_id, request.auth_user.id)
    problem = _get_open_problem_for_participant_or_404(class_id, problem_id)

    submissions = (
        ClassroomSubmission.objects.filter(problem=problem, member=member)
        .select_related("classroom_score")
        .prefetch_related("assets")
        .order_by("-attempt_number")
    )
    return 200, ClassroomProblemSubmissionsOut(
        problem=_serialize_problem_mine(problem),
        submissions=[
            # `s.assets.all()[0]`이 아니라 리스트로 먼저 받는다 — 그래야
            # `prefetch_related("assets")`가 채워 둔 캐시를 쓴다. `.get()`은
            # 매니저를 거쳐 매번 새 질의를 날려 그 prefetch를 헛수고로 만든다.
            _serialize_classroom_submission(s, asset=list(s.assets.all())[0], user=request.auth_user)
            for s in submissions
        ],
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

    member = _get_member_or_404(class_id, request.auth_user.id)
    problem = _get_open_problem_for_participant_or_404(class_id, problem_id)

    if member.expelled_at is not None:
        # ClassMember.expelled_at의 docstring이 이 엔드포인트를 지목해 둔
        # 자리다 — 행은 지우지 않되 새 제출만 막는다. 강사가 이미 그 사실을
        # 아는 사람에게는 404(존재 자체를 숨김)보다 403(권한이 없다는 것을
        # 안다)이 더 정직하다.
        raise HttpError(403, "더 이상 이 클래스의 참여자가 아닙니다.")

    value = payload.value.strip()
    if not value:
        raise HttpError(422, "제출 값을 입력해주세요.")

    content_type = ""
    if problem.submission_format == Problem.SubmissionFormat.SOURCE:
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

    return 201, _serialize_classroom_submission(submission, asset=asset, user=request.auth_user)


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
    response={200: ChecklistItemOut, 404: ErrorOut},
    auth=jwt_auth,
)
def update_checklist_item(
    request: HttpRequest,
    class_id: int,
    problem_id: int,
    item_id: int,
    payload: ChecklistItemPatchIn,
):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    item = _get_owned_checklist_item_or_404(problem, item_id)

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
    response={204: None, 404: ErrorOut},
    auth=jwt_auth,
)
def delete_checklist_item(request: HttpRequest, class_id: int, problem_id: int, item_id: int):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    item = _get_owned_checklist_item_or_404(problem, item_id)
    item.delete()
    return 204, None
