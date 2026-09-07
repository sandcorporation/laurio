"""Assignment API — 생성·수정·열기·InviteCode 조회 (#207, ADR-0028/0029).

`contests.api`(공모전)와 분리한다 — 공모전 표면은 본인확인·Prize·Category를 요구하고
결제가 문을 열지만, 여기는 그 무엇도 요구하지 않는 대신 `AssignmentPermission`을
요구한다(ADR-0029: 결제가 서 있던 자리를 사람의 승인이 대신한다). 두 표면이 같은
`Contest` 모델을 공유하면서도(ADR-0028) 엔드포인트를 나누는 이유는 정확히 이것이다 —
한 파일에 섞으면 언젠가 Prize 필드가 Assignment 경로로 새거나, 본인확인 게이트가
실수로 여기 붙는다.

**본인확인 게이트를 지우지 않는다.** `contests.api.create_contest`의 Verification
검사는 그대로 서 있다 — 여기서는 그 함수를 아예 부르지 않을 뿐이다(ADR-0029).

InviteCode는 열 때(`open_assignment`) 발급된다 — 추측 불가능한 값이고
(`InviteCode._generate_invite_code`), 이것을 아는 사람만 `GET /assignments/invite/{code}`로
과제 상세를 볼 수 있다. 명단은 두지 않는다(스펙 #197) — 제출한 사람만
`submissions.api`(#208)가 보여준다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from core.clock import Clock
from core.transitions import claim_transition
from storage.adapters import get_storage_adapter
from submissions.models import AssignmentSourceReading, Submission, SubmissionAsset
from submissions.schemas import (
    AssignmentSourceRevealOut,
    AssignmentSubmissionSummaryOut,
    SourceRevealAssetOut,
)

from .assignment_category import get_assignment_category
from .models import Contest, DeliverableType, InviteCode, Requirement
from .schemas import (
    AssignmentCreateIn,
    AssignmentOut,
    AssignmentUpdateIn,
    RequirementOut,
)

router = Router(tags=["assignments"])

_VALID_GRADES = {"required", "optional"}


def _require_assignment_permission(user) -> SponsorProfile:
    """`AssignmentPermission`(#206, ADR-0029)이 있는 Sponsor만 통과한다.

    프로필이 아직 없으면(과제를 한 번도 연 적 없는 계정) 자격도 없다 — Operator가
    자격을 줄 때 `SponsorProfile`을 지연 생성해 두므로(`grant_assignment_permission`),
    프로필이 없다는 것 자체가 "자격을 받은 적 없다"는 뜻이다.
    """

    profile = SponsorProfile.objects.filter(user=user).first()
    if profile is None or not profile.can_open_assignments:
        raise HttpError(
            403, "과제를 열 자격이 없습니다. 운영자에게 자격을 요청해 주세요."
        )
    return profile


def _serialize_assignment(
    contest: Contest, *, auth_user: object | None = None, invite_code: str | None = None
) -> AssignmentOut:
    is_owner = auth_user is not None and contest.sponsor.user_id == getattr(auth_user, "id", None)
    return AssignmentOut(
        id=contest.id,
        title=contest.title,
        deliverable_types=[
            {"id": dt.id, "name": dt.name, "minimum_prize": dt.minimum_prize}
            for dt in contest.deliverable_types.all()
        ],
        description=contest.description,
        deadline_at=contest.deadline_at,
        status=contest.status,
        requirements=[
            RequirementOut(id=r.id, text=r.text, grade=r.grade, order=r.order)
            for r in contest.requirements.all()
        ],
        created_at=contest.created_at,
        invite_code=invite_code,
        is_owner=is_owner,
    )


def _active_invite_code(contest: Contest) -> str | None:
    """활성 InviteCode 하나 — 여러 행을 순회하는 `list_my_assignments`에서 이 함수를
    호출하는 자리는 항상 `contest.invite_codes`를 이미 `prefetch_related`해 뒀다.
    `.filter(is_active=True)`로 새 QuerySet을 만들면 Django가 그 prefetch 캐시를
    쓰지 않고 매번 새 쿼리를 낸다(prefetch 캐시는 `.all()`에만 적용된다) — 대신
    이미 불러온 `.all()`을 파이썬에서 걸러 N+1을 피한다. 목록 하나에 활성 코드는
    많아야 하나뿐이므로(unique_active_invite_code_per_contest) 비용이 무시할 만하다."""

    for code in contest.invite_codes.all():
        if code.is_active:
            return code.code
    return None


def _get_owned_assignment(request: HttpRequest, assignment_id: int) -> Contest:
    """소유자만 통과하는 게이트 — 상태는 안 본다(읽기·상태 전이 공통으로 쓴다).

    `contests.assignment_category`가 배정한 Category로만 Assignment를 가려낸다 — DRAFT는
    공모전과 Assignment가 공유하므로(ADR-0028) status만으로는 구별할 수 없다. 이 필터가
    없으면 공모전 DRAFT의 id를 안 타인이 이 라우터로 접근해 "존재는 하는데 과제가
    아니다"를 확인해버릴 수 있다 — 그래서 카테고리 불일치도 404로 감춘다(공모전
    `get_contest`가 타인의 draft를 감추는 것과 같은 원칙).
    """

    try:
        contest = (
            Contest.objects.select_related("sponsor", "category")
            .prefetch_related("deliverable_types", "requirements")
            .get(id=assignment_id, category=get_assignment_category())
        )
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "과제를 찾을 수 없습니다.") from exc

    auth_user = getattr(request, "auth_user", None)
    if auth_user is None or contest.sponsor.user_id != auth_user.id:
        raise HttpError(404, "과제를 찾을 수 없습니다.")

    return contest


def _get_owned_editable_assignment(request: HttpRequest, assignment_id: int) -> Contest:
    contest = _get_owned_assignment(request, assignment_id)

    if not Contest.Status.EDITABLE(contest.status):
        raise HttpError(409, "지금은 이 과제를 고칠 수 없는 상태입니다.")

    return contest


def _validate_deliverable_types(deliverable_type_ids: list[int]) -> list[DeliverableType]:
    if not deliverable_type_ids:
        raise HttpError(422, "산출물 종류를 하나 이상 선택해야 합니다.")

    deliverable_types = list(
        DeliverableType.objects.filter(id__in=deliverable_type_ids, is_active=True)
    )
    if len(deliverable_types) != len(set(deliverable_type_ids)):
        raise HttpError(422, "존재하지 않는 DeliverableType이 포함되어 있습니다.")
    return deliverable_types


def _validate_requirement_grades(requirements) -> None:
    for requirement in requirements:
        if requirement.grade not in _VALID_GRADES:
            raise HttpError(422, "Requirement grade는 required 또는 optional 이어야 합니다.")


@router.post("/assignments", response={201: AssignmentOut}, auth=jwt_auth)
def create_assignment(request: HttpRequest, payload: AssignmentCreateIn):
    """자격 있는 Sponsor가 본인확인 없이 과제를 DRAFT로 만든다(ADR-0028/0029).

    `contests.api.create_contest`와 짝이지만 Verification 검사를 부르지 않고, Prize·
    Category를 받지 않는다 — Prize는 0, Category는 `assignment_category`가 자동
    배정된다. `required_minimum_prize`·`is_underfunded`도 항상 0/False다(스펙 #197 —
    과제에는 "상금미달" 개념이 없다).
    """

    # `_require_assignment_permission`이 이미 `SponsorProfile`을 조회해 자격까지
    # 확인했다 — 그 결과를 그대로 쓴다(get_or_create로 다시 조회하지 않는다). 이
    # 함수를 통과했다는 것 자체가 프로필이 이미 존재한다는 뜻이다(자격은 프로필에
    # 붙은 플래그이므로 프로필 없이는 자격도 없다).
    sponsor_profile = _require_assignment_permission(request.auth_user)

    deliverable_types = _validate_deliverable_types(payload.deliverable_type_ids)
    _validate_requirement_grades(payload.requirements)

    with transaction.atomic():
        contest = Contest.objects.create(
            sponsor=sponsor_profile,
            title=sanitize_free_text(payload.title),
            category=get_assignment_category(),
            description=sanitize_free_text(payload.description),
            prize=0,
            deadline_at=payload.deadline_at,
            status=Contest.Status.DRAFT,
            required_minimum_prize=0,
            is_underfunded=False,
        )
        contest.deliverable_types.set(deliverable_types)

        Requirement.objects.bulk_create(
            [
                Requirement(
                    contest=contest,
                    text=sanitize_free_text(r.text),
                    grade=r.grade,
                    order=index,
                )
                for index, r in enumerate(payload.requirements)
            ]
        )

    contest.refresh_from_db()
    return 201, _serialize_assignment(contest, auth_user=request.auth_user)


@router.get("/assignments/mine", response=list[AssignmentOut], auth=jwt_auth)
def list_my_assignments(request: HttpRequest):
    """Sponsor 자신이 연/만든 과제 목록 — 「과제 만들기·수정·열기·코드 표시」 화면의 진입점.

    **`/assignments/{assignment_id}`보다 먼저 등록해야 한다** — `contests.api.
    list_my_sponsored_contests`와 같은 이유(정적 경로가 동적 컨버터보다 먼저 매치돼야
    한다).
    """

    profile = SponsorProfile.objects.filter(user=request.auth_user).first()
    if profile is None:
        return []

    contests = (
        Contest.objects.filter(sponsor=profile, category=get_assignment_category())
        .select_related("sponsor", "category")
        .prefetch_related("deliverable_types", "requirements", "invite_codes")
        .order_by("-created_at", "-id")
    )
    return [
        _serialize_assignment(
            c, auth_user=request.auth_user, invite_code=_active_invite_code(c)
        )
        for c in contests
    ]


@router.get("/assignments/invite/{code}", response=AssignmentOut, auth=None)
def get_assignment_by_invite_code(request: HttpRequest, code: str):
    """InviteCode를 아는 사람만 과제 상세·Requirement를 본다(ADR-0028) — 인증이 필요
    없다: 본인확인은커녕 로그인조차 이 조회의 전제가 아니다(학생이 코드를 받아 처음
    들어오는 순간에는 아직 로그인 전일 수 있다).

    코드가 없거나 비활성(재발급으로 무효화된 옛 코드, #209 소관)이면 404 — 존재를
    드러내지 않는다(공모전의 draft 은닉과 같은 원칙).
    """

    invite = (
        InviteCode.objects.filter(code=code, is_active=True)
        .select_related("contest__sponsor", "contest__category")
        .first()
    )
    if invite is None:
        raise HttpError(404, "InviteCode를 찾을 수 없습니다.")

    contest = invite.contest
    # 상태와 무관하게 보여준다 — ASSIGNMENT_CLOSED(마감) 후에도 학생이 자기 과제와
    # 점수를 계속 볼 수 있어야 한다(스펙 #197 user story 31). DRAFT는 InviteCode가
    # 아직 없어 이 분기에 도달할 수 없다(열 때만 발급된다).
    return _serialize_assignment(contest, invite_code=code)


@router.get("/assignments/{assignment_id}", response=AssignmentOut, auth=jwt_auth)
def get_my_assignment(request: HttpRequest, assignment_id: int):
    contest = _get_owned_assignment(request, assignment_id)
    return _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=_active_invite_code(contest)
    )


@router.patch("/assignments/{assignment_id}", response=AssignmentOut, auth=jwt_auth)
def update_assignment(request: HttpRequest, assignment_id: int, payload: AssignmentUpdateIn):
    """DRAFT·ASSIGNMENT_OPEN 과제를 고친다(스펙 #197) — `EDITABLE`이 두 상태 모두 True다.

    **제출 0건 술어는 여기 없다.** `EDITABLE: True`가 「고칠 수 있다」의 절반이고
    나머지 절반(첫 제출이 문을 닫는다)은 #209가 얹는다 — 지금은 ASSIGNMENT_OPEN이면
    제출이 있어도 계속 고칠 수 있다.
    """

    contest = _get_owned_editable_assignment(request, assignment_id)

    with transaction.atomic():
        if payload.title is not None:
            sanitized_title = sanitize_free_text(payload.title)
            if not sanitized_title:
                raise HttpError(422, "제목이 비어 있습니다.")
            contest.title = sanitized_title

        if payload.description is not None:
            contest.description = sanitize_free_text(payload.description)

        if payload.deadline_at is not None:
            contest.deadline_at = payload.deadline_at

        if payload.deliverable_type_ids is not None:
            deliverable_types = _validate_deliverable_types(payload.deliverable_type_ids)
            contest.deliverable_types.set(deliverable_types)

        contest.save()

    contest.refresh_from_db()
    return _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=_active_invite_code(contest)
    )


@router.post("/assignments/{assignment_id}/open", response={200: AssignmentOut}, auth=jwt_auth)
def open_assignment(request: HttpRequest, assignment_id: int):
    """DRAFT -> ASSIGNMENT_OPEN — 결제를 거치지 않는 유일한 공개 전이(ADR-0028).

    자격을 여기서 **다시** 확인한다 — 생성과 열기 사이에 Operator가 자격을 거뒀을 수
    있다(ADR-0029: "자격을 거두면 새 과제를 못 만든다"는 새로 여는 것도 막아야
    일관된다. 이미 열린 과제는 이 검사를 다시 지나지 않으므로 "이미 열린 과제는
    끝까지 돈다"는 그대로 성립한다).

    조건부 UPDATE(`core.transitions.claim_transition`, ADR-0003) 한 번으로 전이한다 —
    중복 클릭이 InviteCode를 두 번 발급하지 않는다: 두 번째 호출은 `from_state=DRAFT`
    조건에 걸려 `won=False`가 되고 409로 끝난다.
    """

    contest = _get_owned_assignment(request, assignment_id)
    _require_assignment_permission(request.auth_user)

    won = claim_transition(
        Contest,
        contest.pk,
        from_state=Contest.Status.DRAFT,
        to_state=Contest.Status.ASSIGNMENT_OPEN,
        state_field="status",
        now=Clock.now(),
    )
    if not won:
        raise HttpError(409, "이미 열렸거나 초안 상태가 아닙니다.")

    invite = InviteCode.objects.create(contest=contest)

    contest.refresh_from_db()
    return 200, _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=invite.code
    )


# --- 제출 목록·소스 펼침 (#211, ADR-0022/0028) -------------------------------
#
# 공모전의 Sponsor는 Award 전까지 소스를 절대 볼 수 없다(ADR-0014) — 그 규칙은
# `submissions.api`가 그대로 지킨다. Assignment에는 그 규칙 자체가 없다(Escrow도
# 지식재산권 이전도 없으므로 감출 근거가 없다, ADR-0028) — 대신 ADR-0022가
# Operator에 대해 세운 모양을 그대로 Sponsor에게 적용한다: 기본은 접혀 있고,
# 명시적으로 펼 때만 기록이 남는다. `_get_owned_assignment`가 카테고리로 Assignment
# 만 가려내므로, 이 두 엔드포인트는 프라이즈 Contest의 Submission에는 애초에
# 닿지 않는다 — ADR-0014를 건드릴 길이 없다.


@router.get(
    "/assignments/{assignment_id}/submissions",
    response=list[AssignmentSubmissionSummaryOut],
    auth=jwt_auth,
)
def list_assignment_submissions(request: HttpRequest, assignment_id: int):
    """Sponsor가 자기 Assignment에 낸 제출 목록을 본다.

    소스는 여기 없다 — 목록을 훑는 것만으로 소스가 보이면 안 된다(위 규율).
    소스를 보려면 `reveal_assignment_submission_source`를 따로 불러야 한다.
    """

    contest = _get_owned_assignment(request, assignment_id)
    submissions = (
        Submission.objects.filter(contest=contest)
        .select_related("developer")
        .order_by("-created_at")
    )
    return [
        AssignmentSubmissionSummaryOut(
            id=s.id,
            developer_id=s.developer_id,
            developer_display_name=s.developer.display_name or f"Developer#{s.developer_id}",
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in submissions
    ]


@router.post(
    "/assignments/{assignment_id}/submissions/{submission_id}/source",
    response={200: AssignmentSourceRevealOut},
    auth=jwt_auth,
)
def reveal_assignment_submission_source(
    request: HttpRequest, assignment_id: int, submission_id: int
):
    """Sponsor가 마감 전에도 제출 소스를 펼친다 — 이 요청 자체가
    `AssignmentSourceReading`을 하나 남긴다(#211).

    **소스는 presigned URL로 준다, 프롬프트가 아니다.** `appeals.api.
    reveal_appeal_source`는 이미 채점이 끝난 뒤 `Score.prompt`(LLM에 넣은 텍스트)를
    돌려주지만, 여기는 마감 전(Score가 아직 없을 때)에도 불릴 수 있어 그 값이 없다.
    그래서 `SubmissionAsset`(kind=source/repository)을 직접 본다 — source는
    storage 어댑터가 그 자리에서 발급한 짧은 수명의 다운로드 URL, repository는
    이미 URL인 값 그대로.

    **storage.policy를 거치지 않는다.** 일반 다운로드 게이트(`storage.api.
    request_download`)는 이 대상을 "Award 전까지 Developer 본인만"으로 판정해
    Sponsor를 막는다(`submissions.resolvers`) — 그 판정은 ADR-0014를 위한 것이라
    Assignment에서까지 다시 열 수 없다. 대신 이 엔드포인트 자신이 권한 판정
    (Sponsor가 이 Assignment의 소유자인가, `_get_owned_assignment`)을 마치고
    직접 presign한다 — Operator의 `reveal_appeal_source`가 storage를 거치지 않고
    `Score.prompt`를 바로 내주는 것과 같은 구조다.
    """

    contest = _get_owned_assignment(request, assignment_id)
    try:
        submission = Submission.objects.prefetch_related("assets").get(
            id=submission_id, contest=contest
        )
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "제출물을 찾을 수 없습니다.") from exc

    adapter = get_storage_adapter()
    out_assets: list[SourceRevealAssetOut] = []
    for asset in submission.assets.all():
        if asset.kind == SubmissionAsset.Kind.SOURCE:
            presigned = adapter.presign_download(
                asset.value,
                expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
            )
            url = presigned.url
        elif asset.kind == SubmissionAsset.Kind.REPOSITORY:
            url = asset.value
        else:
            continue
        out_assets.append(SourceRevealAssetOut(id=asset.id, kind=asset.kind, label=asset.label, url=url))

    # 열람은 상태가 아니라 사건이다 — 같은 Sponsor가 다시 펼치면 행이 하나 더
    # 쌓인다(중복 제거하지 않는다, ADR-0022와 같은 규율).
    AssignmentSourceReading.objects.create(
        submission=submission, read_by=request.auth_user, read_at=Clock.now()
    )

    return 200, AssignmentSourceRevealOut(assets=out_assets)
