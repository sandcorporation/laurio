"""Contest API — draft 개최, DeliverableType 견적, 공개 목록/상세.

결제·`Escrow`(#9)는 이 티켓 범위 밖이다. 여기서 만든 `Contest`는 항상 draft로 남고,
결제가 확인되면 #9가 `status`를 `published`로 전이시킬 훅만 남겨둔다.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from payments.models import Payment
from verification.models import Verification

from .models import Category, Contest, DeliverableType, Requirement
from .schemas import (
    CategoryOut,
    ContestCreateIn,
    ContestOut,
    ContestReopenIn,
    DeliverableTypeOut,
    QuoteIn,
    QuoteOut,
    RequirementOut,
)

router = Router(tags=["contests"])


def _minimum_total(deliverable_type_ids: list[int]) -> int:
    total = DeliverableType.objects.filter(
        id__in=deliverable_type_ids, is_active=True
    ).aggregate(total=Sum("minimum_prize"))["total"]
    return total or 0


def _serialize_contest(contest: Contest) -> ContestOut:
    return ContestOut(
        id=contest.id,
        title=contest.title,
        category=CategoryOut(id=contest.category_id, name=contest.category.name),
        deliverable_types=[
            DeliverableTypeOut(id=dt.id, name=dt.name, minimum_prize=dt.minimum_prize)
            for dt in contest.deliverable_types.all()
        ],
        description=contest.description,
        prize=contest.prize,
        deadline_at=contest.deadline_at,
        status=contest.status,
        required_minimum_prize=contest.required_minimum_prize,
        is_underfunded=contest.is_underfunded,
        requirements=[
            RequirementOut(id=r.id, text=r.text, grade=r.grade, order=r.order)
            for r in contest.requirements.all()
        ],
        source_contest_id=contest.source_contest_id,
        created_at=contest.created_at,
    )


@router.get("/contests/categories", response=list[CategoryOut], auth=None)
def list_categories(request: HttpRequest):
    return [
        CategoryOut(id=c.id, name=c.name) for c in Category.objects.filter(is_active=True)
    ]


@router.get("/contests/deliverable-types", response=list[DeliverableTypeOut], auth=None)
def list_deliverable_types(request: HttpRequest):
    return [
        DeliverableTypeOut(id=d.id, name=d.name, minimum_prize=d.minimum_prize)
        for d in DeliverableType.objects.filter(is_active=True)
    ]


@router.post("/contests/quote", response=QuoteOut, auth=None)
def quote(request: HttpRequest, payload: QuoteIn):
    """선택한 DeliverableType들의 최소 제안 상금 합계를 등록 전에 보여준다."""

    return QuoteOut(
        deliverable_type_ids=payload.deliverable_type_ids,
        minimum_total=_minimum_total(payload.deliverable_type_ids),
    )


@router.post("/contests", response=ContestOut, auth=jwt_auth)
def create_contest(request: HttpRequest, payload: ContestCreateIn):
    """Verification을 마친 Sponsor가 Contest를 draft로 만든다.

    Prize가 선택한 DeliverableType 최소 상금 합계에 미달해도 등록은 성공한다 —
    「상금미달」 배지만 선다. 플랫폼은 신호를 줄 뿐 금지하지 않는다.
    """

    if not Verification.objects.filter(
        user=request.auth_user, status=Verification.Status.VERIFIED
    ).exists():
        raise HttpError(403, "본인확인을 완료해야 Contest를 개최할 수 있습니다.")

    if not payload.deliverable_type_ids:
        raise HttpError(422, "DeliverableType을 하나 이상 선택해야 합니다.")

    try:
        category = Category.objects.get(id=payload.category_id, is_active=True)
    except Category.DoesNotExist as exc:
        raise HttpError(422, "존재하지 않는 Category입니다.") from exc

    deliverable_types = list(
        DeliverableType.objects.filter(id__in=payload.deliverable_type_ids, is_active=True)
    )
    if len(deliverable_types) != len(set(payload.deliverable_type_ids)):
        raise HttpError(422, "존재하지 않는 DeliverableType이 포함되어 있습니다.")

    for requirement in payload.requirements:
        if requirement.grade not in {"required", "optional"}:
            raise HttpError(422, "Requirement grade는 required 또는 optional 이어야 합니다.")

    sponsor_profile, _created = SponsorProfile.objects.get_or_create(user=request.auth_user)

    minimum_total = sum(dt.minimum_prize for dt in deliverable_types)

    # Contest 행 커밋과 Requirement 일괄 생성이 한 단위여야 한다 — 예를 들어 500자를
    # 넘는 Requirement.text가 DB CHECK/길이 제약에 걸려 bulk_create가 실패해도,
    # Contest만 커밋된 채 남는 고아 레코드를 만들지 않는다.
    with transaction.atomic():
        contest = Contest.objects.create(
            sponsor=sponsor_profile,
            title=sanitize_free_text(payload.title),
            category=category,
            description=sanitize_free_text(payload.description),
            prize=payload.prize,
            deadline_at=payload.deadline_at,
            status=Contest.Status.DRAFT,
            required_minimum_prize=minimum_total,
            is_underfunded=payload.prize < minimum_total,
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
    return _serialize_contest(contest)


@router.get("/contests", response=list[ContestOut], auth=None)
@paginate(PageNumberPagination, page_size=20)
def list_contests(request: HttpRequest):
    """공개된 Contest만 나온다 — draft는 비로그인·타인에게 보이지 않는다.

    PUBLISHED뿐 아니라 CLOSED도 공개 목록에 남는다 — 마감 전이(#11)는 결제 취소가
    아니라 "데모·영상이 전면 공개되는 시점"일 뿐이다(ADR-0014). CLOSED를 여기서
    빼면 submissions.api.get_developer_public_profile이 돌려주는 contest_id·title이
    가리키는 곳이 404가 되어, 마감된 Submission을 아카이브하는 #11의 취지 자체가
    무너진다(#12 리뷰 지적).

    `select_related("category")`가 없으면 목록의 Contest마다 Category를 한 번씩 더
    조회하는 N+1이 난다. 목록은 무한정 커질 수 있으므로 페이지네이션도 둔다.
    """

    return Contest.objects.filter(
        status__in=[Contest.Status.PUBLISHED, Contest.Status.CLOSED]
    ).select_related("category").prefetch_related("deliverable_types", "requirements")


@router.get("/contests/{contest_id}", response=ContestOut, auth=None)
def get_contest(request: HttpRequest, contest_id: int):
    try:
        contest = (
            Contest.objects.select_related("category")
            .prefetch_related("deliverable_types", "requirements")
            .get(id=contest_id)
        )
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    # PUBLISHED·CLOSED 둘 다 공개다 — list_contests와 같은 기준(위 설명 참고).
    if contest.status not in (Contest.Status.PUBLISHED, Contest.Status.CLOSED):
        auth_user = getattr(request, "auth_user", None)
        is_owner = auth_user is not None and contest.sponsor.user_id == auth_user.id
        if not is_owner:
            raise HttpError(404, "Contest를 찾을 수 없습니다.")

    return _serialize_contest(contest)


@router.post("/contests/{contest_id}/reopen", response=ContestOut, auth=jwt_auth)
def reopen_contest(request: HttpRequest, contest_id: int, payload: ContestReopenIn):
    """유찰(참여자 0명 전액 환불, #17)된 Contest를 복제해 새 Contest를 draft로 만든다
    (#22, ADR-0001).

    요구사항(`Requirement`, 이 프로젝트의 "체크리스트")·`Category`·`DeliverableType`
    선택·제목·설명은 원본에서 그대로 복제된다 — Prize와 마감기한만 새로 받는다. 이
    코드베이스에는 아직 Contest에 별도의 Attachment 모델이 없다(그런 필드가 추가되면
    이 복제 로직도 함께 손봐야 한다).

    새 Contest는 원본과 완전히 별개의 행이다 — `ledger_id`가 새로 발급되고(모델
    필드의 `default=uuid.uuid4`), `source_contest`만 원본을 가리킨다. 그래서 결제·
    제출·원장 이력이 원본과 절대 섞이지 않는다: 이 Contest에 새로 붙는 `Payment`·
    `Submission`·`JournalEntry`는 전부 이 새 `id`/`ledger_id`를 통해서만 연결된다.

    "유찰"의 판정 근거는 마감(CLOSED) + 전액 환불(REFUNDED) 완료다 — 참여자가
    한 명이라도 있었으면 #17이 절대 환불하지 않으므로(ADR-0004), REFUNDED
    Payment의 존재가 곧 "참여자 0명으로 유찰됐다"는 가장 직접적인 증거다. 새로
    만들어진 Contest는 다른 draft Contest와 똑같이 결제를 다시 거쳐야 published로
    간다 — 재개최라고 그 경로를 단축하지 않는다.
    """

    try:
        original = (
            Contest.objects.select_related("category", "sponsor")
            .prefetch_related("deliverable_types", "requirements")
            .get(id=contest_id)
        )
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    if original.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest만 재개최할 수 있습니다.")

    if original.status != Contest.Status.CLOSED:
        raise HttpError(409, "마감된 Contest만 재개최할 수 있습니다.")

    if not Payment.objects.filter(contest=original, status=Payment.Status.REFUNDED).exists():
        # CLOSED이지만 환불되지 않았다 — 참여자가 있어 정상적으로 마감됐거나
        # (Escrow: "참가자가 한 명이라도 있으면 Sponsor에게 되돌아가지 않는다"),
        # 아직 환불 스캔(#17)이 돌지 않았다. 어느 쪽이든 재개최 대상이 아니다.
        raise HttpError(409, "전액 환불된(유찰) Contest만 재개최할 수 있습니다.")

    if not Verification.objects.filter(
        user=request.auth_user, status=Verification.Status.VERIFIED
    ).exists():
        raise HttpError(403, "본인확인을 완료해야 Contest를 개최할 수 있습니다.")

    minimum_total = sum(dt.minimum_prize for dt in original.deliverable_types.all())

    with transaction.atomic():
        new_contest = Contest.objects.create(
            sponsor=original.sponsor,
            title=original.title,
            category=original.category,
            description=original.description,
            prize=payload.prize,
            deadline_at=payload.deadline_at,
            status=Contest.Status.DRAFT,
            source_contest=original,
            required_minimum_prize=minimum_total,
            is_underfunded=payload.prize < minimum_total,
        )
        new_contest.deliverable_types.set(original.deliverable_types.all())

        Requirement.objects.bulk_create(
            [
                Requirement(
                    contest=new_contest,
                    text=requirement.text,
                    grade=requirement.grade,
                    order=requirement.order,
                )
                for requirement in original.requirements.all()
            ]
        )

    new_contest.refresh_from_db()
    return _serialize_contest(new_contest)
