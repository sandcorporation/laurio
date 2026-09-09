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
from django.db.models import Count
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from core.clock import Clock
from core.transitions import claim_transition
from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename
from submissions.models import AssignmentSourceReading, Submission, SubmissionAsset
from submissions.schemas import AssignmentSourceRevealOut, SourceRevealAssetOut

from .assignment_category import get_assignment_category
from .images import (
    create_image as create_assignment_image_for,
    remove_image as remove_assignment_image_for,
    reorder_image as reorder_assignment_image_for,
    request_upload_url as request_assignment_image_upload_url_for,
    serialize_contest_image,
)
from .models import Contest, DeliverableType, InviteCode, Requirement
from .schemas import (
    AssignmentCreateIn,
    AssignmentOut,
    AssignmentSubmissionOut,
    AssignmentSubmissionScoreOut,
    AssignmentUpdateIn,
    ContestImageCreateIn,
    ContestImageOut,
    ContestImageReorderIn,
    ContestImageUploadUrlIn,
    ContestImageUploadUrlOut,
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


def _is_locked_by_first_submission(status: str, submission_count: int) -> bool:
    """「첫 제출이 문을 닫는다」(#209)의 유일한 정의 — 이 한 곳에서만 판정한다.

    `_get_owned_editable_assignment`(수정을 실제로 막는 게이트)와
    `_serialize_assignment`(그 결과를 `is_editable`로 미리 화면에 실어 보내는 자리)
    양쪽이 이 함수를 부른다. 둘로 갈라 각자 조건을 다시 쓰면(코드리뷰 지적 — 전에는
    프론트가 `status === "draft" || status === "assignment_open"`으로 이 규칙을
    화면에서 다시 적고 있었다) 언젠가 한쪽만 고쳐져 게이트는 막는데 화면은 편집
    폼을 계속 보여주는 fail-open이 생긴다.
    """

    return status == Contest.Status.ASSIGNMENT_OPEN and submission_count > 0


def _serialize_assignment(
    contest: Contest,
    *,
    auth_user: object | None = None,
    invite_code: str | None = None,
    submission_count: int | None = None,
) -> AssignmentOut:
    """`submission_count`는 호출부가 이미 알고 있으면 넘긴다 — 모르면(`None`) 여기서
    한 번 센다. `list_my_assignments`처럼 여러 Contest를 순회하는 자리가 매번 이
    기본값에 기대면 행마다 COUNT 쿼리가 하나씩 붙는다(N+1, 코드리뷰 지적) — 그런
    자리는 쿼리셋을 `annotate(submission_count=Count("submissions"))`로 미리 세어
    여기 넘긴다. `get_assignment_by_invite_code`(로그인조차 필요 없는 공개
    엔드포인트)는 명시적으로 `0`을 넘긴다 — Assignment는 명단을 두지 않는다는
    원칙(스펙 #197)이 "몇 명이 냈는지"까지는 다루지 않지만, 굳이 인증 없는 요청에
    실제 제출 건수를 새로 노출할 이유도 없다.

    `is_editable`은 `_get_owned_editable_assignment`가 실제로 막는 조건과 정확히
    같은 술어(`Contest.Status.EDITABLE` + `_is_locked_by_first_submission`)로
    계산한다 — 화면이 PATCH를 시도해 409를 받아보기 전에 편집 폼 자체를 숨길 수
    있게(#209 코드리뷰 지적, `is_owner`와 같은 자리에서 같은 이유로 계산해 나간다).
    """

    is_owner = auth_user is not None and contest.sponsor.user_id == getattr(auth_user, "id", None)
    resolved_submission_count = (
        contest.submissions.count() if submission_count is None else submission_count
    )
    is_editable = Contest.Status.EDITABLE(contest.status) and not _is_locked_by_first_submission(
        contest.status, resolved_submission_count
    )
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
        images=[serialize_contest_image(image) for image in contest.images.all()],
        created_at=contest.created_at,
        invite_code=invite_code,
        is_owner=is_owner,
        submission_count=resolved_submission_count,
        is_editable=is_editable,
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

    `kind=Contest.Kind.ASSIGNMENT`로만 Assignment를 가려낸다(#213) — DRAFT는
    공모전과 Assignment가 공유하므로(ADR-0028) status만으로는 구별할 수 없다. 이 필터가
    없으면 공모전 DRAFT의 id를 안 타인이 이 라우터로 접근해 "존재는 하는데 과제가
    아니다"를 확인해버릴 수 있다 — 그래서 종류 불일치도 404로 감춘다(공모전
    `get_contest`가 타인의 draft를 감추는 것과 같은 원칙).
    """

    try:
        contest = (
            Contest.objects.select_related("sponsor", "category")
            .prefetch_related("deliverable_types", "requirements", "images")
            .get(id=assignment_id, kind=Contest.Kind.ASSIGNMENT)
        )
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "과제를 찾을 수 없습니다.") from exc

    auth_user = getattr(request, "auth_user", None)
    if auth_user is None or contest.sponsor.user_id != auth_user.id:
        raise HttpError(404, "과제를 찾을 수 없습니다.")

    return contest


def _get_owned_editable_assignment(request: HttpRequest, assignment_id: int) -> Contest:
    """수정 가능 여부는 `EDITABLE` 하나로 끝나지 않는다(#209, ADR-0028).

    「첫 제출이 문을 닫는다」— `ASSIGNMENT_OPEN`이면서 제출이 0건일 때만 고칠 수
    있다. DRAFT는 `EDITABLE`을 통과하면 이 술어에 걸릴 일이 없다(제출은
    ASSIGNMENT_OPEN 이후에만 가능하다, `submissions.api`). 공모전의 "결제가 문을
    닫는다"에 대응하는 값이고, Escrow의 "참가자가 한 명이라도 있으면 되돌아가지
    않는다"와 같은 결이다 — 채점 기준이 제출 뒤에 바뀌면 그 점수가 무엇을 측정한
    것인지 알 수 없게 되고, Assignment에는 이의제기가 없어 학생에게 구제 수단이
    없다. 거부 이유를 일반적인 409("지금은 고칠 수 없는 상태")와 다른 문구로
    돌려준다 — Sponsor가 왜 막혔는지 화면에서 바로 알아야 한다(#209).
    """

    contest = _get_owned_assignment(request, assignment_id)

    if not Contest.Status.EDITABLE(contest.status):
        raise HttpError(409, "지금은 이 과제를 고칠 수 없는 상태입니다.")

    # `_is_locked_by_first_submission`이 이 판정의 유일한 정의다 — `_serialize_
    # assignment`가 같은 함수로 `is_editable`을 계산해 화면에 미리 실어 보낸다(#209
    # 코드리뷰 지적). 여기서 조건을 다시 쓰면 둘이 갈릴 수 있다.
    if _is_locked_by_first_submission(contest.status, contest.submissions.count()):
        # "과제 내용"이라고 쓴다(구체적으로 "요구사항을"이라 쓰지 않는다) — 이
        # 게이트가 지키는 `update_assignment`는 title·description·deadline_at·
        # deliverable_type_ids뿐 아니라 requirements 통째 교체(#217)도 같은 이유로
        # 여기서 막는다. 새 잠금 규칙을 만들지 않고 이 게이트 하나를 그대로
        # 재사용한다 — 제출 뒤 채점 기준이 바뀌면 이미 낸 학생이 불리해지고,
        # Assignment에는 이의제기가 없어(ADR-0028) 구제 수단이 없다는 이유는
        # title이든 requirements든 다르지 않다.
        raise HttpError(
            409,
            "이미 제출한 학생이 있어 과제 내용을 더 이상 고칠 수 없습니다. "
            "제출 뒤 기준이 바뀌면 이미 낸 학생이 불리해집니다.",
        )

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
            kind=Contest.Kind.ASSIGNMENT,
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
    # 방금 만든 Contest다 — 제출이 있을 수 없으니 COUNT 쿼리 없이 0을 넘긴다.
    return 201, _serialize_assignment(contest, auth_user=request.auth_user, submission_count=0)


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

    # `annotate(Count("submissions"))`로 목록 전체를 쿼리 하나에 센다 — 그러지 않고
    # `_serialize_assignment`의 기본 동작(모르면 직접 센다)에 맡기면 행마다 COUNT가
    # 하나씩 붙는다(N+1, 코드리뷰 지적). `submissions`는 FK 역참조라(M2M이 아니다)
    # 이 자리에서 `deliverable_types`·`requirements`·`invite_codes`·`images`(#236)를
    # 함께 `prefetch_related`해도(별도 쿼리라 JOIN 팬아웃이 없다) `distinct` 없이 정확하다.
    contests = (
        Contest.objects.filter(sponsor=profile, kind=Contest.Kind.ASSIGNMENT)
        .select_related("sponsor", "category")
        .prefetch_related("deliverable_types", "requirements", "invite_codes", "images")
        .annotate(submission_count=Count("submissions"))
        .order_by("-created_at", "-id")
    )
    return [
        _serialize_assignment(
            c,
            auth_user=request.auth_user,
            invite_code=_active_invite_code(c),
            submission_count=c.submission_count,
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
    #
    # `submission_count=0`을 명시한다 — 로그인조차 요구하지 않는 공개 엔드포인트다.
    # Assignment는 명단을 두지 않는다는 원칙(스펙 #197)이 "몇 명이 냈는지"까지 다루진
    # 않지만, 인증 없는 요청에 실제 제출 건수를 새로 노출할 이유도 없다(코드리뷰 지적).
    return _serialize_assignment(contest, invite_code=code, submission_count=0)


@router.get("/assignments/{assignment_id}", response=AssignmentOut, auth=jwt_auth)
def get_my_assignment(request: HttpRequest, assignment_id: int):
    contest = _get_owned_assignment(request, assignment_id)
    return _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=_active_invite_code(contest)
    )


@router.patch("/assignments/{assignment_id}", response=AssignmentOut, auth=jwt_auth)
def update_assignment(request: HttpRequest, assignment_id: int, payload: AssignmentUpdateIn):
    """DRAFT·ASSIGNMENT_OPEN 과제를 고친다(스펙 #197) — `EDITABLE`이 두 상태 모두 True다.

    **제출 0건 술어는 `_get_owned_editable_assignment`에 있다(#209).** `EDITABLE:
    True`가 「고칠 수 있다」의 절반이고, ASSIGNMENT_OPEN이면서 제출이 1건이라도
    있으면 나머지 절반(첫 제출이 문을 닫는다)에 걸려 409로 거부된다.

    **`requirements`도 title·description·deadline_at·deliverable_type_ids와 같은
    게이트를 탄다(#217).** 새 잠금 규칙을 만들지 않는다 — 제출이 있으면 이 핸들러에
    들어오기도 전에 `_get_owned_editable_assignment`가 이미 409로 막는다. 그래서
    아래 `requirements` 처리는 "이미 통과한 게이트를 다시 확인"하지 않는다.
    """

    contest = _get_owned_editable_assignment(request, assignment_id)

    # 어떤 필드를 실제로 바꿨는지 직접 모은다(코드리뷰 지적 — 실제 보안 사고로
    # 확인됨). 이 인스턴스는 `select_for_update()` 없이 읽었으므로, 바로 이 요청이
    # 도는 사이에 마감 전이 스캔(`assignment-close`, `contests/apps.py`)이 조건부
    # UPDATE(ADR-0003)로 `status`를 `ASSIGNMENT_CLOSED`로 이미 옮겼을 수 있다.
    # `contest.save()`(전체 컬럼 UPDATE)를 그대로 쓰면 메모리에 남아 있는 옛
    # `status="assignment_open"`을 그 위에 덮어써, 이미 마감된 과제가 이 PATCH
    # 하나로 다시 열린 것처럼 돌아가 버린다 — 스캔의 조건부 UPDATE가 "정확히 한 번
    # 이기면 그 결과가 유지된다"고 약속한 것을 평범한 저장이 조용히 무효화하는
    # 모양이다. `update_fields`로 이 핸들러가 실제로 대입한 필드만 적어, `status`가
    # 이 UPDATE 문에 아예 실리지 않게 한다.
    update_fields: list[str] = []

    with transaction.atomic():
        if payload.title is not None:
            sanitized_title = sanitize_free_text(payload.title)
            if not sanitized_title:
                raise HttpError(422, "제목이 비어 있습니다.")
            contest.title = sanitized_title
            update_fields.append("title")

        if payload.description is not None:
            contest.description = sanitize_free_text(payload.description)
            update_fields.append("description")

        if payload.deadline_at is not None:
            contest.deadline_at = payload.deadline_at
            update_fields.append("deadline_at")

        if payload.deliverable_type_ids is not None:
            deliverable_types = _validate_deliverable_types(payload.deliverable_type_ids)
            # m2m `.set()`은 그 자체로 DB에 반영된다 — `Contest.save()`가 필요 없다.
            contest.deliverable_types.set(deliverable_types)

        if payload.requirements is not None:
            # 통째 교체다(#217, `AssignmentUpdateIn` 독스트링) — 부분 수정이 아니라
            # 옛 항목을 전부 지우고 새 목록을 그 자리에 다시 만든다. 검증을 먼저
            # 끝내 둔다 — grade가 잘못돼 422가 나면(아래) `transaction.atomic()`이
            # 이 블록에서 일어난 delete까지 통째로 롤백하지만, 순서를 바꿔 delete
            # 뒤에 검증하면 "실패했는데 옛 항목이 이미 지워졌다"는 중간 상태를
            # 트랜잭션 밖에서 관찰할 여지를 만들 이유가 없다.
            _validate_requirement_grades(payload.requirements)
            contest.requirements.all().delete()
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

        if update_fields:
            contest.save(update_fields=update_fields)

    # `refresh_from_db()`를 부르지 않는다(코드리뷰 지적) — `contest`는 이미 방금 쓴
    # 값을 그대로 들고 있다(title·description·deadline_at은 위에서 직접 대입했다).
    # `.set()`은 스스로 캐시를 갱신하는 것이 아니라 그 관계의 prefetch 캐시를
    # **비운다** — 그래서 아래 `_serialize_assignment`의 `.all()`이 다시 쿼리해
    # 최신 값을 그대로 받는다(Django 동작 확인, 코드리뷰). `requirements`도 같은
    # 모양이다(#217): `contest.requirements.all()`이 돌려주는 것은
    # `_get_owned_editable_assignment`가 미리 `prefetch_related`해 둔 바로 그
    # QuerySet 객체이고, 그 위에서 부른 `.delete()`가 (Django `QuerySet.delete()`
    # 구현이) 자기 `_result_cache`를 비운다 — 그래서 이후 `.all()`이 다시 그 캐시를
    # 참조해도 재조회가 일어난다. 결과는 같다: 인자 없는 `refresh_from_db()`처럼
    # `deliverable_types` prefetch를 통째로 버리지 않고, `deliverable_type_ids`를
    # 안 바꾼 요청에서는 그 prefetch가 그대로 살아남는다.
    return _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=_active_invite_code(contest)
    )


# --- AssignmentImage (#236, ADR-0032) ------------------------------------------
#
# 강사가 조건을 보여줄 이유는 공모전과 같다(spec #225) — 그래서 발급·등록·순서
# 변경·제거의 실제 로직은 `contests.images`를 공모전 표면과 그대로 공유한다.
# 다른 것은 게이트 하나뿐이다: 공모전은 결제가 문을 닫고
# (`_get_owned_draft_contest`), 과제는 **첫 제출**이 문을 닫는다
# (`_get_owned_editable_assignment` — #209가 이미 정의한 잠금, 새로 만들지
# 않는다). DRAFT뿐 아니라 아직 제출이 없는 ASSIGNMENT_OPEN 과제도 고칠 수
# 있다는 점까지 그 게이트가 그대로 답한다.


@router.post(
    "/assignments/{assignment_id}/images/upload-url",
    response=ContestImageUploadUrlOut,
    auth=jwt_auth,
)
def request_assignment_image_upload_url(
    request: HttpRequest, assignment_id: int, payload: ContestImageUploadUrlIn
):
    """강사가 참고 이미지를 올리기 전, 공개 이미지 버킷으로의 presigned POST를
    받는다 — `contests.api.request_contest_image_upload_url`과 같은 자리."""

    contest = _get_owned_editable_assignment(request, assignment_id)
    return request_assignment_image_upload_url_for(contest, payload)


@router.post(
    "/assignments/{assignment_id}/images", response=ContestImageOut, auth=jwt_auth
)
def add_assignment_image(
    request: HttpRequest, assignment_id: int, payload: ContestImageCreateIn
):
    """브라우저가 presigned POST로 실제 바이트를 올린 뒤, 그 object_key를 이
    과제의 이미지 목록에 등록한다."""

    contest = _get_owned_editable_assignment(request, assignment_id)
    return create_assignment_image_for(contest, payload)


@router.patch(
    "/assignments/{assignment_id}/images/{image_id}",
    response=ContestImageOut,
    auth=jwt_auth,
)
def reorder_assignment_image(
    request: HttpRequest, assignment_id: int, image_id: int, payload: ContestImageReorderIn
):
    """강사가 이미지의 노출 순서를 고친다."""

    contest = _get_owned_editable_assignment(request, assignment_id)
    return reorder_assignment_image_for(contest, image_id, payload)


@router.delete("/assignments/{assignment_id}/images/{image_id}", auth=jwt_auth)
def remove_assignment_image(request: HttpRequest, assignment_id: int, image_id: int):
    """이미지를 뺀다 — 이 행만 지운다(공모전과 같은 이유, ADR-0005/0032). 재개최는
    과제에 없으므로(REOPENABLE이 REFUNDED Payment를 요구하고 과제에는 결제가
    없다) 지금은 어느 다른 Contest도 이 object_key를 참조하지 않지만, 어댑터에
    삭제 메서드가 없다는 사실 자체는 종류와 무관하다."""

    contest = _get_owned_editable_assignment(request, assignment_id)
    remove_assignment_image_for(contest, image_id)
    return {"success": True}


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

    **전이와 InviteCode 발급을 한 트랜잭션으로 묶는다**(코드리뷰 지적) — 이 프로젝트는
    `ATOMIC_REQUESTS`를 켜지 않으므로 `transaction.atomic()` 없이 두 문장을 그냥
    나란히 두면 각자 따로 커밋된다. `claim_transition`이 커밋된 뒤
    `InviteCode.objects.create`가 실패(IntegrityError·연결 끊김 등)하면 Contest는
    `ASSIGNMENT_OPEN`인데 활성 InviteCode가 하나도 없는 채로 멈춘다 — 재시도는
    `from_state=DRAFT` 조건에 걸려 그때부터 영영 409다(과제를 다시 열 방법이 없다).
    """

    contest = _get_owned_assignment(request, assignment_id)
    _require_assignment_permission(request.auth_user)

    with transaction.atomic():
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

        # 방금 만든 코드를 직접 들고 있지 않고 `_active_invite_code`로 다시 읽는다 —
        # `list_my_assignments`·`get_my_assignment`·`update_assignment`·아래 재발급까지
        # "이 과제의 활성 InviteCode가 무엇인가"를 항상 같은 한 자리(`_active_invite_
        # code`)로 답하게 해서(#209 코드리뷰 지적), 방금 만든 객체를 들고 다니는 경로와
        # 다시 조회하는 경로가 갈릴 여지를 없앤다. 생성은 위 `claim_transition`과 같은
        # `transaction.atomic()` 안에 남는다(#207 통합) — 전이만 커밋되고 코드가 없는
        # 과제가 남으면 재시도가 409라 아무도 들어올 수 없다.
        InviteCode.objects.create(contest=contest)

    # `claim_transition`은 조건부 UPDATE(원시 SQL, ADR-0003)로 DB 행만 옮긴다 —
    # 이 Python 인스턴스는 `status`뿐 아니라 `updated_at`(auto_now, claim_transition이
    # 그 UPDATE 문 안에서 함께 찍는다)도 여전히 옛 값이다. 인자 없는
    # `refresh_from_db()`는 그 둘을 바로잡지만 `_get_owned_assignment`가 미리 해 둔
    # `prefetch_related("deliverable_types", "requirements")`까지 통째로 버려
    # `_serialize_assignment`가 그 둘을 다시 쿼리하게 만든다(코드리뷰 지적) — 반면
    # `fields=`를 주는 형태는 prefetch 캐시를 건드리지 않는다(Django). 두 필드만
    # 지정해 DB 가 실제로 갖고 있는 값을 그대로 읽어 온다 — "이 인스턴스가 옮긴 값과
    # 같다"를 주석으로 약속하는 대신 실제로 다시 읽어 보장한다.
    contest.refresh_from_db(fields=["status", "updated_at"])
    return 200, _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=_active_invite_code(contest)
    )


@router.post(
    "/assignments/{assignment_id}/invite-code/reissue",
    response={200: AssignmentOut},
    auth=jwt_auth,
)
def reissue_invite_code(request: HttpRequest, assignment_id: int):
    """코드가 새어 나가면 강사가 다시 발급한다(#209) — **새 진입만 막는다.**

    옛 InviteCode는 지우지 않고 `is_active=False`로만 죽인다 — `InviteCode.contest`가
    append-only 이력을 위해 `ForeignKey`(OneToOne이 아니다, `models.py` 주석)로 둔
    이유가 정확히 이것이다. 이미 그 코드로 낸 `Submission`은 InviteCode 행이 아니라
    `Submission.developer`로 존재하므로 옛 코드가 죽어도 전혀 건드리지 않는다 — 명단이
    없어(스펙 #197) "이미 낸 사람"은 애초에 InviteCode가 아니라 Submission의 존재로
    판정된다.

    `ASSIGNMENT_OPEN`에서만 의미가 있다 — DRAFT는 아직 InviteCode 자체가 없고(열 때
    발급된다), `ASSIGNMENT_CLOSED` 이후에는 더 막을 새 진입이 없다(마감 후 학생은
    이미 손에 쥔 코드로 자기 점수를 계속 볼 뿐 새로 제출하지 않는다).

    두 번 연달아 눌러도 활성 코드가 둘 남지 않는다 — `select_for_update`로 Contest
    행을 잠근 채 비활성화와 재발급을 한 트랜잭션에 묶는다(`unique_active_invite_code_
    per_contest`가 DB 레벨 최후 방어선으로 이미 서 있다, `models.py`).

    **상태를 잠근 행에서 다시 확인한다.** 소유권만 확인한 `contest`(트랜잭션 밖에서
    읽은 스냅샷)로 상태를 판정하면, 그 판정과 `select_for_update` 사이에 마감 스캔
    (`ASSIGNMENT_OPEN -> ASSIGNMENT_CLOSED`, `contests/apps.py`)이 끼어들 수 있다 —
    체크는 통과했는데 잠근 순간에는 이미 CLOSED라, "CLOSED 이후에는 재발급이 의미
    없다"는 위 설명을 스스로 어기며 마감된 과제에 새 활성 코드를 만들게 된다
    (코드리뷰 지적). 그래서 상태 판정 자체를 잠근 행 안으로 옮긴다 — `accounts.
    assignment_permission_services.grant_assignment_permission`이 같은 이유로
    `select_for_update` 뒤에 상태(`can_open_assignments`)를 다시 보는 것과 같은
    자리다.
    """

    contest = _get_owned_assignment(request, assignment_id)

    with transaction.atomic():
        locked_contest = Contest.objects.select_for_update().get(pk=contest.pk)
        if locked_contest.status != Contest.Status.ASSIGNMENT_OPEN:
            raise HttpError(409, "열린 과제만 InviteCode를 재발급할 수 있습니다.")

        InviteCode.objects.filter(contest=locked_contest, is_active=True).update(is_active=False)
        InviteCode.objects.create(contest=locked_contest)

    # 방금 만든 코드를 직접 들고 있지 않고 `_active_invite_code`로 다시 읽는다 —
    # `open_assignment`와 같은 이유(#209 코드리뷰 지적): "이 과제의 활성 InviteCode가
    # 무엇인가"를 항상 같은 한 자리로 답한다.
    contest.refresh_from_db()
    return 200, _serialize_assignment(
        contest, auth_user=request.auth_user, invite_code=_active_invite_code(contest)
    )


@router.get(
    "/assignments/{assignment_id}/submissions",
    response=list[AssignmentSubmissionOut],
    auth=jwt_auth,
)
def list_assignment_submissions(request: HttpRequest, assignment_id: int):
    """Sponsor 가 제출 목록과 각 제출의 Score·근거를 본다(#210, ADR-0006/0028).

    상태·시각과 무관하게 항상 조회할 수 있다 — 채점 전에는 `score`가 null일 뿐이다.
    소스는 여기 없다: 소스 열람은 명시적으로 펼쳐야 기록과 함께 이루어지는 별도
    경로다(#211, ADR-0022) — 목록을 훑는 것만으로 소스가 눈에 들어오면 그 기록이
    잡음으로 가득 차 의미를 잃는다.
    """

    contest = _get_owned_assignment(request, assignment_id)

    submissions = (
        Submission.objects.filter(contest=contest)
        .select_related("developer", "score")
        .order_by("created_at", "id")
    )
    return [
        AssignmentSubmissionOut(
            submission_id=s.id,
            developer_id=s.developer_id,
            developer_display_name=s.developer.display_name or f"Developer#{s.developer_id}",
            created_at=s.created_at,
            score=(
                AssignmentSubmissionScoreOut(
                    percentage=str(s.score.percentage),
                    model_version=s.score.model_version,
                    reasoning=s.score.reasoning,
                    created_at=s.score.created_at,
                )
                if hasattr(s, "score")
                else None
            ),
        )
        for s in submissions
    ]


# 제출 목록은 #210 의 것 하나만 둔다 — #211 도 소스 펼치기를 걸 자리로 같은
# 엔드포인트를 따로 만들었는데, 두 체인이 병렬로 짜다 겹친 것이라 통합에서
# 하나로 합쳤다. Score 를 싣는 #210 쪽이 상위집합이다.
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

    **`storage.api.request_download`와 같은 방식으로 파일명을 붙인다(#241).**
    `asset.content_type`(제출 시점에 받은 값, 없으면 빈 문자열)을
    `storage.filenames.build_download_filename`에 넘긴다 — storage.policy를
    거치지 않아도 그 헬퍼는 그대로 재사용할 수 있다.
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
                filename=build_download_filename(asset.content_type),
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
