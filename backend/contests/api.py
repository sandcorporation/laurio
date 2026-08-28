"""Contest API — draft 개최, DeliverableType 견적, 공개 목록/상세.

결제·`Escrow`(#9)는 이 티켓 범위 밖이다. 여기서 만든 `Contest`는 항상 draft로 남고,
결제가 확인되면 #9가 `status`를 `published`로 전이시킬 훅만 남겨둔다.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from core.clock import Clock
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from payments.adapters import PGError, PGTimeoutError, get_adapter
from verification.models import Verification

from .models import Category, Contest, DeliverableType, Requirement
from .schemas import (
    CategoryOut,
    ContestCreateIn,
    ContestOut,
    DeliverableTypeOut,
    ExtendJudgingPeriodIn,
    ExtendJudgingPeriodOut,
    QuoteIn,
    QuoteOut,
    RequirementOut,
)

router = Router(tags=["contests"])

# 마감(#11) 이후 계속 공개로 남는 상태들. CLOSED뿐 아니라 AWARDED·JUDGING_ENDED도
# 포함한다(#13) — 그렇지 않으면 심사기간이 끝나거나 Award되는 순간 목록·상세가
# 404가 되어, #11이 만든 "마감된 Contest는 계속 공개" 계약이 그 이후 상태에서
# 조용히 깨진다(정확히 이 티켓이 경계하라고 지시받은, 새 상태를 놓치는 실패 형태다).
_PUBLICLY_VISIBLE_STATUSES = [
    Contest.Status.PUBLISHED,
    Contest.Status.CLOSED,
    Contest.Status.AWARDED,
    Contest.Status.JUDGING_ENDED,
]


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
        created_at=contest.created_at,
        judging_ends_at=contest.judging_ends_at,
        judging_extension_count=contest.judging_extension_count,
        refund_disabled=contest.refund_disabled,
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
        status__in=_PUBLICLY_VISIBLE_STATUSES
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

    # PUBLISHED·CLOSED·AWARDED·JUDGING_ENDED 모두 공개다 — list_contests와 같은
    # 기준(위 _PUBLICLY_VISIBLE_STATUSES 설명 참고).
    if contest.status not in _PUBLICLY_VISIBLE_STATUSES:
        auth_user = getattr(request, "auth_user", None)
        is_owner = auth_user is not None and contest.sponsor.user_id == auth_user.id
        if not is_owner:
            raise HttpError(404, "Contest를 찾을 수 없습니다.")

    return _serialize_contest(contest)


@router.post(
    "/contests/{contest_id}/extend-judging-period",
    response={200: ExtendJudgingPeriodOut},
    auth=jwt_auth,
)
def extend_judging_period(request: HttpRequest, contest_id: int, payload: ExtendJudgingPeriodIn):
    """심사기간을 유료로 연장한다 (#13, REQUEST.md "기간 연장", ADR-0003).

    핵심 불변식 — **전이 시각 컬럼(judging_ends_at)만 갱신한다.** core.transitions
    레지스트리에 등록된 CLOSED -> JUDGING_ENDED 규칙은 그대로 둔 채, 그 규칙이 다음
    틱에 읽어갈 값만 여기서 미룬다. 예약을 취소하고 다시 등록하는 코드 경로는
    존재하지 않는다.

    2회 이상(judging_extension_count가 2에 도달) 연장되면 refund_disabled가 영구히
    True로 확정된다 — 이후 다시 False로 되돌리는 경로는 없다.

    결제 실패 시(402) Contest는 전혀 건드리지 않는다 — 돈이 안 들어왔는데 심사기간만
    늘어나는 사고를 막는다.
    """

    with transaction.atomic():
        try:
            contest = Contest.objects.select_for_update().select_related("sponsor").get(
                id=contest_id
            )
        except Contest.DoesNotExist as exc:
            raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

        if contest.sponsor.user_id != request.auth_user.id:
            raise HttpError(403, "본인이 개최한 Contest만 심사기간을 연장할 수 있습니다.")

        if contest.status != Contest.Status.CLOSED:
            # PUBLISHED(아직 마감 전)·DRAFT(아직 공개 전)는 심사기간 자체가 없고,
            # AWARDED(이미 Award됨)·JUDGING_ENDED(이미 심사기간 종료)는 더 늘릴
            # 대상이 없다.
            raise HttpError(409, "지금은 심사기간을 연장할 수 있는 상태가 아닙니다.")

        now = Clock.now()
        if contest.judging_ends_at is None or now >= contest.judging_ends_at:
            # status가 아직 CLOSED로 보여도(스캔 주기만큼 늦어질 수 있다, ADR-0003)
            # 시각으로 다시 한번 확인한다 — 스케줄러가 아직 JUDGING_ENDED로 옮기지
            # 못했다고 해서 이미 끝난 심사기간을 연장해줄 수는 없다.
            raise HttpError(409, "이미 심사기간이 종료되어 연장할 수 없습니다.")

        adapter = get_adapter()
        order_id = f"judging-extension:{contest.id}:{contest.judging_extension_count + 1}"
        adapter.request_payment(order_id=order_id, amount=settings.CONTEST_EXTENSION_FEE)
        try:
            result_status = adapter.confirm(order_id=order_id, simulate=payload.simulate)
        except PGTimeoutError:
            result_status = adapter.query_status(order_id=order_id)
        except PGError as exc:
            raise HttpError(502, str(exc)) from exc

        if result_status != "paid":
            raise HttpError(402, "연장 결제에 실패했습니다.")

        new_extension_count = contest.judging_extension_count + 1
        new_refund_disabled = contest.refund_disabled or new_extension_count >= 2
        new_judging_ends_at = contest.judging_ends_at + timedelta(
            days=settings.JUDGING_EXTENSION_DAYS
        )

        # 여전히 조건부 UPDATE로 남긴다 — select_for_update로 이미 직렬화됐지만,
        # ADR-0003의 규율(WHERE state=<이전상태>)을 다른 전이들과 똑같이 지킨다.
        Contest.objects.filter(pk=contest.pk, status=Contest.Status.CLOSED).update(
            judging_ends_at=new_judging_ends_at,
            judging_extension_count=new_extension_count,
            refund_disabled=new_refund_disabled,
        )

        post_journal_entry(
            contest_id=contest.ledger_id,
            memo=(
                f"Contest #{contest.id} 심사기간 연장 {new_extension_count}회차 — "
                f"{settings.CONTEST_EXTENSION_FEE:,}원"
            ),
            lines=[
                LineInput(
                    account=Account.SPONSOR_DEPOSIT,
                    side=EntrySide.DEBIT,
                    amount=settings.CONTEST_EXTENSION_FEE,
                ),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.CREDIT,
                    amount=settings.CONTEST_EXTENSION_FEE,
                ),
            ],
        )

    return 200, ExtendJudgingPeriodOut(
        contest_id=contest.id,
        judging_ends_at=new_judging_ends_at,
        judging_extension_count=new_extension_count,
        refund_disabled=new_refund_disabled,
    )
