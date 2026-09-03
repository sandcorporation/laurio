"""Contest API — draft 개최, DeliverableType 견적, 공개 목록/상세.

결제·`Escrow`(#9)는 이 티켓 범위 밖이다. 여기서 만든 `Contest`는 항상 draft로 남고,
결제가 확인되면 #9가 `status`를 `published`로 전이시킬 훅만 남겨둔다.
"""

# `from __future__ import annotations` 를 쓰지 않는다 — 이 모듈에는 `@paginate` 로
# 감싼 엔드포인트가 있고(list_contests, #39), 그 래퍼는 원본 함수의 `__globals__` 를
# 가져갈 수 없어서 문자열이 된 어노테이션(`Query[ContestListFilters]`)을 해석하지
# 못한다 — 필터 하나 붙이려다 `QueryParams is not fully defined` 로 500 이 났다.
# Python 3.13 은 `int | None` 같은 문법을 런타임에 그대로 지원하므로 이 임포트가
# 없어도 아쉬울 것이 없다.

import logging
from uuid import UUID

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, DateTimeField, Q, QuerySet, Sum, Value
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from contests.curation import HOME_IMMINENT_DEADLINE_DAYS, HomeCurationBucket, home_bucket_for
from contests.sponsorship import sponsored_contest_queryset
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from core.clock import Clock
from payments.adapters import PGError, PGTimeoutError, get_adapter
from payments.models import Payment
from policies.services import get_current_policy
from verification.models import Verification

from .models import (
    Category,
    Contest,
    DeliverableType,
    JudgingExtensionPayment,
    Requirement,
    RequirementChatMessage,
)
from .requirement_chat import (
    ChatTurn,
    ExistingRequirement,
    RequirementChatAdapterError,
    RequirementChatInput,
    build_chat_prompt,
    get_requirement_chat_adapter,
)
from .schemas import (
    MySponsoredContestOut,
    CategoryOut,
    ContestListFilters,
    ContestSort,
    ConfirmJudgingExtensionIn,
    ContestCreateIn,
    ContestOut,
    ContestReopenIn,
    DeliverableTypeOut,
    HomeCurationGroupOut,
    InitiateJudgingExtensionIn,
    JudgingExtensionPaymentOut,
    QuoteIn,
    QuoteOut,
    RequirementChatMessageIn,
    RequirementChatResponseOut,
    RequirementChatTurnOut,
    RequirementCreateIn,
    RequirementOut,
    RequirementProposalOut,
    RequirementUpdateIn,
)
from .services import mark_extension_failed, mark_extension_paid

router = Router(tags=["contests"])
logger = logging.getLogger(__name__)

# Requirement.grade / RequirementIn.grade와 같은 값 집합. create_contest의 인라인
# 체크와 아래 requirement CRUD·chat 제안이 같은 기준을 쓰도록 한 곳에 둔다.
_VALID_GRADES = {"required", "optional"}

# 한 Sponsor가 한 Contest에 쌓을 수 있는 대화 턴 수 상한. 무제한으로 두면 한 Contest가
# 프롬프트에 실리는 대화 이력을 무한정 늘려 이후 매 턴의 LLM 호출 비용·지연을 키운다.
_MAX_CHAT_HISTORY_TURNS = 200

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

# 홈의 한 묶음이 보여주는 최대 건수 (#94). 홈은 큐레이션이지 탐색이 아니다 —
# 전체는 `/contests`(#39, 필터·정렬·페이지네이션을 이미 갖고 있다)의 몫이다.
# 이전 자리표시 홈(#93)이 전체를 12건으로 잘랐던 것과 같은 정신이다.
_HOME_BUCKET_LIMIT = 6


def _minimum_total(deliverable_type_ids: list[int]) -> int:
    total = DeliverableType.objects.filter(
        id__in=deliverable_type_ids, is_active=True
    ).aggregate(total=Sum("minimum_prize"))["total"]
    return total or 0


def _serialize_contest(contest: Contest) -> ContestOut:
    # `contest.submission_count`는 annotate로 미리 실려 있어야 한다
    # (list_contests/get_contest/get_home_curation) — 새로 만든 Contest는
    # 호출부가 0을 직접 채워 넣는다(create_contest/reopen_contest, 둘 다 방금
    # 만든 행이라 Submission이 있을 수 없다). 여기서 조용히 0으로 기본값을
    # 주지 않는 이유는, annotate를 빠뜨린 새 호출부가 있으면 AttributeError로
    # 바로 드러나야 하기 때문이다 — getattr로 감싸면 그 실수가 "항상 0"이라는
    # 그럴듯한 값으로 위장해 테스트를 통과할 수 있다.
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
        judging_ends_at=contest.judging_ends_at,
        submission_count=contest.submission_count,
    )


def _serialize_extension_payment(
    payment: JudgingExtensionPayment, *, checkout_url: str | None = None
) -> JudgingExtensionPaymentOut:
    # 항상 최신 Contest 값을 다시 읽는다 — payment 객체 자체는 confirm이 막 확정한
    # 시점의 스냅샷이 아닐 수 있고(예: 아직 REQUESTED인 initiate 응답), Sponsor가
    # 이 응답으로 "지금 심사기간이 언제까지인지"를 바로 알 수 있어야 한다.
    contest = Contest.objects.get(pk=payment.contest_id)
    return JudgingExtensionPaymentOut(
        order_id=str(payment.order_id),
        contest_id=payment.contest_id,
        amount=payment.amount,
        extension_number=payment.extension_number,
        status=payment.status,
        checkout_url=checkout_url,
        created_at=payment.created_at,
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
        if requirement.grade not in _VALID_GRADES:
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
    # 방금 만든 행이라 Submission이 있을 수 없다 — annotate 대신 직접 0을 채운다
    # (_serialize_contest 참고).
    contest.submission_count = 0
    return _serialize_contest(contest)


@router.get("/contests", response=list[ContestOut], auth=None)
@paginate(PageNumberPagination, page_size=20)
def list_contests(request: HttpRequest, filters: Query[ContestListFilters]):
    """공개된 Contest만 나온다 — draft는 비로그인·타인에게 보이지 않는다.

    PUBLISHED뿐 아니라 CLOSED도 공개 목록에 남는다 — 마감 전이(#11)는 결제 취소가
    아니라 "데모·영상이 전면 공개되는 시점"일 뿐이다(ADR-0014). CLOSED를 여기서
    빼면 submissions.api.get_developer_public_profile이 돌려주는 contest_id·title이
    가리키는 곳이 404가 되어, 마감된 Submission을 아카이브하는 #11의 취지 자체가
    무너진다(#12 리뷰 지적).

    `select_related("category")`가 없으면 목록의 Contest마다 Category를 한 번씩 더
    조회하는 N+1이 난다. 목록은 무한정 커질 수 있으므로 페이지네이션도 둔다.

    **필터·정렬은 여기서 처리한다(#39).** FE-04(#29)를 만들 때 이 엔드포인트에
    필터가 없어서 프론트가 `page_size=200`으로 한 번에 받아 서버 컴포넌트 안에서
    직접 걸렀다. 그 구조는 두 가지로 조용히 틀린다 — (1) 공개 Contest가 한 페이지를
    넘으면 뒤쪽이 목록에서 그냥 사라진다(예외도 빈 화면도 아니다), (2) 애초에
    200이 통째로 오지도 않았다. ninja의 PageNumberPagination은 요청한 page_size를
    `NINJA_MAX_PER_PAGE_SIZE`(기본 100)로 잘라내므로 실제 천장은 100이었다.
    공개 표면에서 "조용한 누락"은 가장 나쁜 실패 방식이라 축을 백엔드로 내린다.

    `Category`와 `DeliverableType`은 서로 다른 축이다(ADR-0001) — 둘 다 주면 AND로
    좁혀진다. `deliverable_type`은 M2M이지만 값이 하나뿐이라 조인이 Contest당 최대
    한 행이므로 중복이 생기지 않는다(그래서 `distinct()`가 필요 없다).

    정렬에는 항상 `id`를 마지막 키로 붙인다. 상금이나 마감이 동점이면 DB가 순서를
    보장할 이유가 없고, 페이지마다 순서가 달라지면 **같은 Contest가 두 페이지에
    나오고 다른 하나는 어느 페이지에도 안 나온다** — 페이지네이션에서 정렬이
    불안정하면 목록이 조용히 틀리는 그 두 번째 방식이다.

    알 수 없는 값은 500이 아니라 4xx다 — `sort`는 Enum이라 ninja가 422로 막고,
    `category`/`deliverable_type`도 int가 아니면 422다. 존재하지 않는 id는 오류가
    아니라 빈 목록이다(필터는 "그런 게 있느냐"가 아니라 "그것으로 좁혀라"이다).
    """

    queryset = Contest.objects.filter(status__in=_PUBLICLY_VISIBLE_STATUSES)

    if filters.category is not None:
        queryset = queryset.filter(category_id=filters.category)
    if filters.deliverable_type is not None:
        queryset = queryset.filter(deliverable_types__id=filters.deliverable_type)

    ordering = (
        ("-prize", "id") if filters.sort is ContestSort.PRIZE else ("deadline_at", "id")
    )

    return (
        queryset.order_by(*ordering)
        .select_related("category")
        .prefetch_related("deliverable_types", "requirements")
        # 참가작 수(#106, spec #105) — 목록은 행이 가장 많은 화면이라 행마다
        # 세면 N+1이 정확히 여기서 터진다. `distinct=True`는 `deliverable_type`
        # 필터가 M2M을 조인할 때(위 `deliverable_types__id` 필터) Count가 그
        # 조인으로 부풀려지는 것을 막는다 — 필터가 없을 때도 안전하고 비용도
        # 무시할 만하다.
        .annotate(submission_count=Count("submissions", distinct=True))
    )


@router.get("/contests/mine", response=list[MySponsoredContestOut], auth=jwt_auth)
@paginate(PageNumberPagination, page_size=20)
def list_my_sponsored_contests(request: HttpRequest, **kwargs):
    """Sponsor 가 자기가 연 공모전들과 각각의 「다음 행동」을 본다 (#81).

    **`/contests/{contest_id}` 보다 먼저 등록해야 한다.** 아래에 두면 django-ninja
    가 `mine` 을 `contest_id` 로 읽어 422 를 낸다 — 참가자 쪽 `/submissions/mine`
    이 이미 겪은 함정이다.

    **`draft` 도 나온다.** 공개 목록은 draft 를 감추지만 여기는 「내 것」이고, 초안인
    채로 결제하지 않으면 아무 일도 일어나지 않는다는 사실을 말해 줄 곳이 여기밖에
    없다.

    Sponsor 프로필이 없으면 빈 목록이다 — 개최한 적 없는 사람은 정상적인 상태이지
    없는 리소스가 아니다(`/submissions/mine` 과 같은 관용구).
    """

    profile = SponsorProfile.objects.filter(user=request.auth_user).first()
    if profile is None:
        return Contest.objects.none()

    # 시각과 정책을 이 요청 스코프에서 **한 번씩만** 구한다 — `core.api.tick` 과
    # `distributions.services.run_due_distributions` 가 쓰는 것과 같은 관용구
    # (#75, ADR-0023). 행마다 구하면 조회가 행 수만큼 늘고, 게다가 한 화면 안에서
    # 행마다 다른 시각으로 판정하게 된다.
    as_of = Clock.now()
    policy = get_current_policy()

    return sponsored_contest_queryset(
        Contest.objects.filter(sponsor=profile), as_of=as_of, policy=policy
    ).annotate(judged_as_of=Value(as_of, output_field=DateTimeField())).order_by(
        "-created_at"
    )


def _home_bucket_queryset(base: QuerySet, bucket, *, now) -> QuerySet:
    """`bucket`에 속하는 Contest만, 그 묶음에 맞는 정렬로 돌려준다 (#94).

    **`contests.curation.home_bucket_for`가 판정의 원본이고, 이 함수는 그
    판정을 SQL WHERE로 다시 표현한 것이다.** 원래는(#94 1차) 공개 Contest를
    전부 가져와 Python에서 `home_bucket_for`를 한 번씩만 부르는 단일 질의
    였다 — 조건을 두 벌로 쓰지 않으려던 것이었는데, 그러면 공개 Contest가
    쌓일수록(수천 건) 매 홈 방문마다 전부 fetch하고
    `deliverable_types`·`requirements`까지 prefetch하게 된다(#94 코드리뷰
    4 — 홈은 `force-dynamic`이라 캐시도 없다). 그래서 묶음마다 상태·기한으로
    좁히고 그 묶음에 맞는 정렬로 DB에서 상위 `_HOME_BUCKET_LIMIT`건만 뽑는다.

    **이 이중화는 방치되지 않는다** — `get_home_curation`이 각 행을 다시
    `home_bucket_for`에 통과시켜 이 필터와 갈리면 로그로 드러내고,
    `backend/tests/test_home_curation.py`의 경계값 테스트들이 임계값
    (`HOME_IMMINENT_DEADLINE_DAYS`)의 양쪽 끝을 계속 검증한다.

    정렬은 묶음마다 다르다(#94 코드리뷰 1) — 「진행중」·「마감임박」은 마감이
    가까운 순(오름차순), 「심사중」·「완료」는 최근에 마감된 순(내림차순)이다.
    네 묶음이 전부 같은 정렬을 쓰면 「완료」·「심사중」은 가장 오래된 건에
    영구히 고정된다 — 방금 선정된 공모전이 홈에 절대 안 오른다.
    """

    imminent_cutoff = now + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS)

    if bucket == HomeCurationBucket.ONGOING:
        return base.filter(
            status=Contest.Status.PUBLISHED, deadline_at__gt=imminent_cutoff
        ).order_by("deadline_at", "id")

    if bucket == HomeCurationBucket.IMMINENT:
        # 하한(`deadline_at__gte=now`)이 없으면 스캔이 아직 CLOSED로 못 옮긴
        # 마감 지난 PUBLISHED가 여기 섞여, 오름차순 정렬의 맨 앞자리(가장
        # 음수인 값)를 영구히 차지하고 진짜 D-1·D-2를 밀어낸다(#94 코드리뷰
        # 2). `home_bucket_for`가 그 구간을 IN_JUDGING으로 보내는 것과
        # 같은 경계다.
        return base.filter(
            status=Contest.Status.PUBLISHED,
            deadline_at__gte=now,
            deadline_at__lte=imminent_cutoff,
        ).order_by("deadline_at", "id")

    if bucket == HomeCurationBucket.IN_JUDGING:
        return base.filter(
            Q(status=Contest.Status.CLOSED)
            | Q(status=Contest.Status.PUBLISHED, deadline_at__lt=now)
        ).order_by("-deadline_at", "-id")

    if bucket == HomeCurationBucket.COMPLETED:
        return base.filter(
            status__in=(Contest.Status.AWARDED, Contest.Status.JUDGING_ENDED)
        ).order_by("-deadline_at", "-id")

    raise ValueError(f"알 수 없는 HomeCurationBucket: {bucket!r}")  # pragma: no cover


@router.get("/contests/home", response=list[HomeCurationGroupOut], auth=None)
def get_home_curation(request: HttpRequest):
    """홈이 보여줄 네 묶음 — 진행중·마감임박·심사중·완료 (#94, spec #92).

    **`/contests/{contest_id}` 보다 먼저 등록해야 한다** — `/contests/mine`과 같은
    이유다(위 `list_my_sponsored_contests` 참고). 아래에 두면 ninja가 `home`을
    `contest_id`로 읽으려다 422를 낸다.

    **판정의 원본은 `contests.curation.home_bucket_for`다.** 화면이
    `status`·`deadline_at`에서 재파생하면 새 상태가 생겼을 때 조용히 어느
    분기에도 안 걸린다 — `submissions.participation`·`contests.sponsorship`이
    같은 이유로 백엔드 판정인 것과 같다(#94 인수조건). 다만 이 엔드포인트는
    성능 때문에 그 판정을 묶음별 쿼리(`_home_bucket_queryset`)로 다시
    표현한다 — 왜 그래야 했는지, 그리고 갈리지 않게 무엇을 해 두었는지는 그
    함수의 docstring을 본다.

    `DRAFT`는 어느 `_home_bucket_queryset` 필터에도 안 걸린다 — 결제 전
    Contest가 새지 않는다는 계약은 공개 목록/상세와 같다(#94 인수조건).

    네 묶음은 **비어 있어도 항상 다 나온다** — `HomeCurationBucket`을 순회해
    목록을 만들므로, 실제로 그 부류의 Contest가 하나도 없으면 `contests: []`인
    채로 그 묶음이 응답에 실린다. 화면이 그 자리에서 "비어 있다"고 보여줄 수
    있는 것은 이 항상-네-묶음 계약 덕분이다(#94 인수조건 — 섹션이 통째로
    사라지면 안 된다).

    각 묶음은 최대 `_HOME_BUCKET_LIMIT`건만 담는다 — 홈은 큐레이션이지 탐색이
    아니다. 전체를 보려면 `/contests`(#39)로 간다.
    """

    now = Clock.now()

    base = (
        Contest.objects.select_related("category")
        .prefetch_related("deliverable_types", "requirements")
        # 참가작 수(#106, spec #105) — 네 묶음 각각의 쿼리(_home_bucket_queryset)가
        # 이 `base`를 그대로 이어받아 필터만 얹으므로, annotate를 여기 한 번만
        # 둬도 네 쿼리 전부에 실린다. 홈 큐레이션이 이미 경계해 둔 N+1(#94)과
        # 같은 이유로 묶음마다·행마다 따로 세지 않는다.
        .annotate(submission_count=Count("submissions", distinct=True))
    )

    groups = []
    for bucket in HomeCurationBucket:
        contests = list(_home_bucket_queryset(base, bucket, now=now)[:_HOME_BUCKET_LIMIT])

        for contest in contests:
            # `_home_bucket_queryset`가 `home_bucket_for`의 판정을 SQL로
            # 다시 쓴 것이므로, 둘이 갈리면 화면이 조용히 틀린 채로 나간다
            # — curation.home_bucket_for의 docstring이 "호출부는 조용히
            # 버리지 않고 드러내야 한다"고 적어 둔 계약을 여기서 지킨다
            # (#94 코드리뷰 5). 홈 전체를 죽이지는 않는다 — 묶음 하나가
            # 틀리는 것이 홈이 통째로 500이 되는 것보다 낫다.
            actual_bucket = home_bucket_for(contest, now=now)
            if actual_bucket != bucket:
                logger.error(
                    "홈 큐레이션 불일치: Contest %s(status=%s, deadline_at=%s)를 "
                    "%s 쿼리로 가져왔는데 home_bucket_for는 %s라고 판정했다 — "
                    "_home_bucket_queryset과 home_bucket_for가 갈렸다.",
                    contest.id, contest.status, contest.deadline_at, bucket, actual_bucket,
                )

        groups.append(
            HomeCurationGroupOut(
                bucket=bucket,
                contests=[_serialize_contest(c) for c in contests],
            )
        )

    return groups


@router.get("/contests/{contest_id}", response=ContestOut, auth=None)
def get_contest(request: HttpRequest, contest_id: int):
    try:
        contest = (
            Contest.objects.select_related("category")
            .prefetch_related("deliverable_types", "requirements")
            # 참가작 수(#106, spec #105) — 단건이라도 annotate로 얻는다.
            # `_serialize_contest`가 `contest.submission_count`를 그대로 읽는다.
            .annotate(submission_count=Count("submissions", distinct=True))
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

    한 Contest는 최대 한 번만 재개최된다(리뷰 지적 5) — 이미 `reopenings`가 하나
    라도 있으면 거부한다. `initiate_payment`(payments.api)와 같은 이유로 이
    존재 확인과 생성을 `original` 행을 `select_for_update`로 잠근 채 같은
    트랜잭션 안에서 한다 — 잠그지 않으면 두 요청이 동시에 "아직 재개최 안 됐다"
    를 보고 통과해 같은 원본에서 별개의 사본이 두 개 만들어진다(중복 클릭·재시도
    모두 같은 경합이다).

    복제되는 `Category`·`DeliverableType`은 운영자가 그 사이 비활성화했을 수
    있다(리뷰 지적 6) — `create_contest`가 신규 개최에 요구하는 것과 같은 검증
    (활성 상태, `DeliverableType`이 하나 이상)을 재개최에도 그대로 적용한다.
    그렇지 않으면 `create_contest`라면 422로 거부했을 죽은 분류가 이 경로로만
    살아남고, 이미 은퇴한 `DeliverableType`의 낡은 최소 상금이 상금미달 배지
    계산에 계속 쓰인다.
    """

    with transaction.atomic():
        try:
            original = (
                Contest.objects.select_for_update()
                .select_related("category", "sponsor")
                .get(id=contest_id)
            )
        except Contest.DoesNotExist as exc:
            raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

        if original.sponsor.user_id != request.auth_user.id:
            raise HttpError(403, "본인이 개최한 Contest만 재개최할 수 있습니다.")

        if original.status not in (Contest.Status.CLOSED, Contest.Status.JUDGING_ENDED):
            # CLOSED뿐 아니라 JUDGING_ENDED도 허용한다 — 스케줄러가
            # judging_ends_at이 지나면 CLOSED -> JUDGING_ENDED로 무조건 전이시키므로
            # (core.transitions 레지스트리, Award 여부와 무관), 참여자 0명으로
            # 유찰된 Contest도 이 엔드포인트가 그 사실을 알아채기 전에
            # JUDGING_ENDED로 넘어갈 수 있다. CLOSED만 허용하면 그 순간부터
            # 재개최가 영구히 409로 막힌다 — 실제 판정 근거는 아래
            # REFUNDED Payment 존재 여부이지 이 status 값 자체가 아니므로, 상태
            # 값만으로 이미 유찰이 확정된 Contest를 걸러낼 이유가 없다.
            raise HttpError(409, "마감된 Contest만 재개최할 수 있습니다.")

        if not Payment.objects.filter(contest=original, status=Payment.Status.REFUNDED).exists():
            # CLOSED이지만 환불되지 않았다 — 참여자가 있어 정상적으로 마감됐거나
            # (Escrow: "참가자가 한 명이라도 있으면 Sponsor에게 되돌아가지 않는다"),
            # 아직 환불 스캔(#17)이 돌지 않았다. 어느 쪽이든 재개최 대상이 아니다.
            raise HttpError(409, "전액 환불된(유찰) Contest만 재개최할 수 있습니다.")

        if original.reopenings.exists():
            # 이미 한 번 재개최됐다 — original 행을 위에서 잠갔으므로 이 확인과
            # 아래 생성 사이에 다른 요청이 끼어들 수 없다(리뷰 지적 5). 몇 번째
            # 사본인지는 source_contest_id 체인을 따라가면 된다(ADR-0001).
            raise HttpError(409, "이미 재개최된 Contest입니다.")

        if not Verification.objects.filter(
            user=request.auth_user, status=Verification.Status.VERIFIED
        ).exists():
            raise HttpError(403, "본인확인을 완료해야 Contest를 개최할 수 있습니다.")

        if not original.category.is_active:
            raise HttpError(422, "카테고리가 더 이상 활성화되어 있지 않습니다.")

        active_deliverable_types = list(original.deliverable_types.filter(is_active=True))
        if not active_deliverable_types:
            raise HttpError(
                422, "선택했던 DeliverableType이 더 이상 활성화되어 있지 않습니다."
            )

        minimum_total = sum(dt.minimum_prize for dt in active_deliverable_types)

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
        new_contest.deliverable_types.set(active_deliverable_types)

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
    # 방금 만든 행이라 Submission이 있을 수 없다 — annotate 대신 직접 0을 채운다
    # (_serialize_contest 참고).
    new_contest.submission_count = 0
    return _serialize_contest(new_contest)


_ACTIVE_EXTENSION_PAYMENT_STATUSES = [JudgingExtensionPayment.Status.REQUESTED]


def _reject_if_judging_period_is_not_extendable(contest: Contest) -> None:
    if contest.status != Contest.Status.CLOSED:
        # PUBLISHED(아직 마감 전)·DRAFT(아직 공개 전)는 심사기간 자체가 없고,
        # AWARDED(이미 Award됨)·JUDGING_ENDED(이미 심사기간 종료)는 더 늘릴 대상이
        # 없다.
        raise HttpError(409, "지금은 심사기간을 연장할 수 있는 상태가 아닙니다.")

    # 코드베이스 관용구와 맞춘다: 심사기간 종료는 `judging_ends_at <= as_of`일 때
    # 일어나므로(core.transitions), "아직 끝나지 않았다"는 정확히 `now <
    # judging_ends_at`이다. Award(awards.api)도 같은 경계를 쓴다(#13 리뷰 지적 7 —
    # 세 곳이 서로 다른 부등호를 쓰면 경계 순간에 판정이 갈린다).
    now = Clock.now()
    if contest.judging_ends_at is None or now >= contest.judging_ends_at:
        # status가 아직 CLOSED로 보여도(스캔 주기만큼 늦어질 수 있다, ADR-0003)
        # 시각으로 다시 한번 확인한다 — 스케줄러가 아직 JUDGING_ENDED로 옮기지
        # 못했다고 해서 이미 끝난 심사기간을 연장해줄 수는 없다.
        raise HttpError(409, "이미 심사기간이 종료되어 연장할 수 없습니다.")


@router.post(
    "/contests/{contest_id}/extend-judging-period",
    response={201: JudgingExtensionPaymentOut},
    auth=jwt_auth,
)
def initiate_judging_period_extension(
    request: HttpRequest, contest_id: int, payload: InitiateJudgingExtensionIn
):
    """심사기간 유료 연장 결제를 시작한다 (#13, REQUEST.md "기간 연장", ADR-0003).

    `payments.api.initiate_payment`와 같은 두 단계 구조를 그대로 따른다 — 이
    엔드포인트는 결제 **의도**를 `JudgingExtensionPayment(REQUESTED)`로 먼저
    영속화하고 PG에 결제를 등록할 뿐, 아직 심사기간을 늘리지도 원장에 분개를
    남기지도 않는다. 실제로 돈이 확정되는 것은
    `POST .../extend-judging-period/{order_id}/confirm`뿐이다(#13 리뷰 지적 1 —
    확정 전에 먼저 행을 만들어 둬야, 결제 결과가 나중에 pending으로 걸리거나
    confirm 호출 자체가 유실돼도 대사할 수 있는 흔적이 남는다).

    같은 Contest에 대해 두 요청이 동시에 들어와도 진행 중인(REQUESTED) 연장 결제가
    하나만 남아야 한다(#13 리뷰 지적 2, `payments.api.initiate_payment`와 같은
    이유) — `Contest` 행을 `select_for_update`로 잠가 동시 요청을 직렬화하고,
    `JudgingExtensionPayment.unique_pending_judging_extension_payment_per_contest`
    부분 유니크 제약을 두 번째 방어선으로 둔다.
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

        _reject_if_judging_period_is_not_extendable(contest)

        # 이미 진행 중인 연장 결제가 있으면 새로 만들지 않고 그대로 돌려준다 —
        # 중복 클릭·재요청이 새 주문을 계속 만들어내지 않게 하는 멱등성이다.
        # Contest 행을 위에서 잠갔으므로 이 조회는 동시 요청과 경합하지 않는다.
        existing = (
            JudgingExtensionPayment.objects.filter(
                contest=contest, status__in=_ACTIVE_EXTENSION_PAYMENT_STATUSES
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            adapter = get_adapter()
            result = adapter.request_payment(
                order_id=str(existing.order_id), amount=existing.amount
            )
            return 201, _serialize_extension_payment(existing, checkout_url=result.checkout_url)

        try:
            # 중첩 atomic(세이브포인트) — payments.api.initiate_payment와 같은
            # 이유. IntegrityError가 나면 바깥 트랜잭션 전체가 aborted 상태가 되어
            # 그 뒤의 방어적 조회조차 TransactionManagementError로 죽는다.
            #
            # amount와 extension_days를 같은 policy 조회에서 함께 스냅샷한다
            # (#78 코드리뷰 지적 2) — 이 initiate 시점 이후 confirm까지
            # 정책이 바뀌어도 이 결제가 청구하는 금액과 실제로 늘어나는
            # 심사기간이 서로 다른 시점을 가리키는 불일치가 생기지 않는다.
            policy = get_current_policy()
            with transaction.atomic():
                payment = JudgingExtensionPayment.objects.create(
                    contest=contest,
                    amount=policy.judging_extension_fee,
                    extension_days=policy.judging_extension_days,
                    extension_number=contest.judging_extension_count + 1,
                    status=JudgingExtensionPayment.Status.REQUESTED,
                )
        except IntegrityError:
            # Contest 잠금에도 불구하고 unique_pending_judging_extension_payment_
            # per_contest에 걸렸다 — 방어적 안전망이다(정상 경로에서는 위
            # select_for_update가 이미 직렬화했으므로 도달하지 않아야 한다).
            payment = JudgingExtensionPayment.objects.filter(
                contest=contest, status__in=_ACTIVE_EXTENSION_PAYMENT_STATUSES
            ).latest("created_at")

        adapter = get_adapter()
        result = adapter.request_payment(order_id=str(payment.order_id), amount=payment.amount)

        return 201, _serialize_extension_payment(payment, checkout_url=result.checkout_url)


@router.post(
    "/contests/{contest_id}/extend-judging-period/{order_id}/confirm",
    response={200: JudgingExtensionPaymentOut},
    auth=jwt_auth,
)
def confirm_judging_period_extension(
    request: HttpRequest, contest_id: int, order_id: UUID, payload: ConfirmJudgingExtensionIn
):
    """연장 결제를 동기 확인한다 (`payments.api.confirm_payment`와 같은 구조).

    **PG 호출은 어떤 `transaction.atomic()` 블록 밖에서 일어난다** — 잠금을 쥔 채
    외부 네트워크 호출을 기다리지 않는다(#13 리뷰 지적 3). 타임아웃이 나도 곧바로
    실패로 처리하지 않고 `query_status`로 실제 결과를 조회해 확정한다(ADR-0008).
    돈이 실제로 오갔는지 알 수 없는 "pending"도 실패로 단정하지 않는다 — 함부로
    `mark_extension_failed`를 부르면, 나중에 PG가 성공으로 정산해도 이미 실패로
    적힌 결제는 다시 확인되지 않는다.
    """

    try:
        payment = JudgingExtensionPayment.objects.select_related("contest__sponsor").get(
            order_id=order_id, contest_id=contest_id
        )
    except JudgingExtensionPayment.DoesNotExist as exc:
        raise HttpError(404, "연장 결제를 찾을 수 없습니다.") from exc

    if payment.contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest의 연장 결제만 확인할 수 있습니다.")

    if payment.status != JudgingExtensionPayment.Status.REQUESTED:
        # 이미 확정되어 있다 — 그대로 현재 상태를 돌려준다(재전송·재조회에 안전).
        return 200, _serialize_extension_payment(payment)

    adapter = get_adapter()
    try:
        result_status = adapter.confirm(
            order_id=str(order_id),
            simulate=payload.simulate,
            payment_key=payload.payment_key,
            amount=payment.amount,
        )
    except PGTimeoutError:
        # payments.api.confirm_payment과 같은 규율이다(#87 코드리뷰 지적 4) —
        # 이 재확인 호출자체가 또 실패할 수 있다. FakePGAdapter는 query_status에서
        # 절대 예외를 던지지 않아 이 경로가 기존 테스트에서 한 번도 밟힌 적이
        # 없었다 — 그 실패를 그대로 올리면 500이 된다. 타임아웃만큼 이 실패도
        # "아직 모른다"이지 "실패했다"가 아니므로 강제 종결시키지 않고 현재
        # 상태(REQUESTED)를 그대로 돌려준다.
        try:
            result_status = adapter.query_status(order_id=str(order_id))
        except Exception as exc:  # noqa: BLE001 - 재확인조차 실패하면 미확정으로 남겨둔다.
            logger.error(
                "토스 연장 결제 재확인(query_status)이 실패했다 — 실패로 단정하지 않고 "
                "현재 상태를 그대로 돌려준다(order_id=%s): %s",
                order_id,
                exc,
            )
            result_status = "pending"
    except PGError as exc:
        raise HttpError(502, str(exc)) from exc

    if result_status == "paid":
        payment = mark_extension_paid(order_id)
    elif result_status == "failed":
        payment = mark_extension_failed(order_id)
    else:
        # 아직 확정할 수 없다(pending) — 함부로 실패 처리하지 않고 현재 상태를
        # 그대로 돌려준다. 이후 재조회가 마저 확정한다.
        payment.refresh_from_db()

    return 200, _serialize_extension_payment(payment)


# --- AI grill — Requirement 체크리스트 대화형 생성 + Sponsor 수정/삭제/추가 (#20) -----


def _get_owned_contest(request: HttpRequest, contest_id: int) -> Contest:
    """소유자만 통과하는 읽기 전용 게이트 — 상태(draft/published/closed)는 안 본다.

    Sponsor 자신의 AI grill 대화 이력을 읽는 건 아무것도 바꾸지 않으므로, Contest가
    공개된 뒤에도 계속 볼 수 있어야 한다. 타인의 Contest는 존재 자체를 숨기려 404로
    응답한다(get_contest·test_owner_can_view_own_draft_but_stranger_cannot과 같은 이유).
    """

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    auth_user = getattr(request, "auth_user", None)
    if auth_user is None or contest.sponsor.user_id != auth_user.id:
        raise HttpError(404, "Contest를 찾을 수 없습니다.")

    return contest


def _get_owned_draft_contest(request: HttpRequest, contest_id: int) -> Contest:
    """AI grill 대화 전송·Requirement CRUD가 공통으로 쓰는 소유권·상태 게이트.

    읽기 전용 조회(`_get_owned_contest`)와 달리 여기는 상태를 무언가 바꾸는
    엔드포인트용이라, 소유자라도 DRAFT를 벗어난 Contest는 편집을 막는다 — 공개된
    뒤 체크리스트가 흔들리면 제출·심사·채점이 기준으로 삼는 대상 자체가 바뀌어
    버린다.
    """

    contest = _get_owned_contest(request, contest_id)

    if contest.status != Contest.Status.DRAFT:
        raise HttpError(409, "공개된 Contest의 Requirement 체크리스트는 더 이상 수정할 수 없습니다.")

    return contest


def _turn_out(message: RequirementChatMessage) -> RequirementChatTurnOut:
    return RequirementChatTurnOut(
        role=message.role, content=message.content, created_at=message.created_at
    )


@router.post(
    "/contests/{contest_id}/requirement-chat/messages",
    response=RequirementChatResponseOut,
    auth=jwt_auth,
)
def send_requirement_chat_message(
    request: HttpRequest, contest_id: int, payload: RequirementChatMessageIn
):
    """Sponsor가 한 턴 발화하면 AI가 질문하거나 체크리스트 항목을 제안한다.

    제안(`proposed_requirements`)은 그 자체로 `Requirement`가 되지 않는다 — AI는
    제안만 하고 Sponsor가 아래 `POST .../requirements`로 실제 추가해야 확정된다
    (AI가 제안, Sponsor가 결정).

    LLM 어댑터가 실패해도(타임아웃·예상 밖 응답 등) 500을 내지 않는다 — 대화가
    끊기지 않도록 사과 응답으로 감성한 뒤 그대로 200을 돌려주고, Sponsor가 같은
    말을 다시 보내거나 다른 말로 이어갈 수 있게 한다.
    """

    contest = _get_owned_draft_contest(request, contest_id)

    prior_messages = list(contest.requirement_chat_messages.all())
    if len(prior_messages) >= _MAX_CHAT_HISTORY_TURNS:
        raise HttpError(
            422,
            "이 Contest의 AI grill 대화가 너무 길어졌습니다. 지금까지 나온 체크리스트로 "
            "진행해 주세요.",
        )

    sanitized_message = sanitize_free_text(payload.message)
    if not sanitized_message:
        raise HttpError(422, "메시지 내용이 비어 있습니다.")

    sponsor_turn = RequirementChatMessage.objects.create(
        contest=contest,
        role=RequirementChatMessage.Role.SPONSOR,
        content=sanitized_message,
    )

    chat_input = RequirementChatInput(
        contest_id=contest.id,
        contest_title=contest.title,
        latest_message=sanitized_message,
        history=[ChatTurn(role=m.role, content=m.content) for m in prior_messages],
        existing_requirements=[
            ExistingRequirement(text=r.text, grade=r.grade) for r in contest.requirements.all()
        ],
    )

    # 감사용으로만 남기는 프롬프트라 대화 이력 전문을 매 턴 다시 담지 않는다
    # (리뷰 지적: 안 그러면 저장량이 턴 수의 제곱으로 자란다) — 이전 턴들은 각자의
    # RequirementChatMessage 행에 이미 자기 몫의 감사 기록을 남겨 뒀다.
    prompt = build_chat_prompt(chat_input, include_history=False)

    try:
        adapter = get_requirement_chat_adapter()
        output = adapter.respond(chat_input)
        reply = output.reply
        proposals = [
            RequirementProposalOut(
                text=p.text[:500], grade=p.grade if p.grade in _VALID_GRADES else "required"
            )
            for p in output.proposed_requirements
            if p.text.strip()
        ]
    except RequirementChatAdapterError as exc:
        logger.warning("Contest(pk=%s) AI grill 응답 실패, 사과 응답으로 감성: %s", contest.id, exc)
        reply = (
            "일시적으로 제안을 만들지 못했어요. 잠시 후 다시 시도해 주시거나, 다른 방식으로 "
            "설명해 주시겠어요?"
        )
        proposals = []
    except Exception:  # noqa: BLE001 - 실제 벤더 연동의 예상 밖 실패도 500으로 새면 안 된다.
        logger.exception("Contest(pk=%s) AI grill 응답 중 예기치 못한 예외", contest.id)
        reply = (
            "일시적으로 제안을 만들지 못했어요. 잠시 후 다시 시도해 주시거나, 다른 방식으로 "
            "설명해 주시겠어요?"
        )
        proposals = []

    assistant_turn = RequirementChatMessage.objects.create(
        contest=contest, role=RequirementChatMessage.Role.ASSISTANT, content=reply, prompt=prompt
    )

    return RequirementChatResponseOut(
        reply=reply,
        proposed_requirements=proposals,
        messages=[_turn_out(m) for m in prior_messages] + [_turn_out(sponsor_turn), _turn_out(assistant_turn)],
    )


@router.get(
    "/contests/{contest_id}/requirement-chat/messages",
    response=list[RequirementChatTurnOut],
    auth=jwt_auth,
)
def list_requirement_chat_messages(request: HttpRequest, contest_id: int):
    """지금까지의 AI grill 대화 이력 — 다시 들어와도 이어갈 수 있게 한다.

    조회는 아무것도 바꾸지 않으므로 Contest가 공개된 뒤에도(더 이상 체크리스트를
    수정할 수 없게 된 뒤에도) 자기 대화 이력은 계속 읽을 수 있어야 한다 —
    `_get_owned_draft_contest`(편집 게이트)가 아니라 `_get_owned_contest`(읽기
    게이트)를 쓴다.
    """

    contest = _get_owned_contest(request, contest_id)
    return [_turn_out(m) for m in contest.requirement_chat_messages.all()]


@router.post(
    "/contests/{contest_id}/requirements", response=RequirementOut, auth=jwt_auth
)
def add_requirement(request: HttpRequest, contest_id: int, payload: RequirementCreateIn):
    """AI 제안을 그대로, 또는 Sponsor가 고쳐 쓴 문구로 체크리스트에 실제로 추가한다."""

    contest = _get_owned_draft_contest(request, contest_id)

    if payload.grade not in _VALID_GRADES:
        raise HttpError(422, "Requirement grade는 required 또는 optional 이어야 합니다.")

    sanitized_text = sanitize_free_text(payload.text)
    if not sanitized_text:
        raise HttpError(422, "Requirement 내용이 비어 있습니다.")

    next_order = contest.requirements.count()
    requirement = Requirement.objects.create(
        contest=contest,
        text=sanitized_text,
        grade=payload.grade,
        order=next_order,
    )
    return RequirementOut(
        id=requirement.id, text=requirement.text, grade=requirement.grade, order=requirement.order
    )


@router.patch(
    "/contests/{contest_id}/requirements/{requirement_id}",
    response=RequirementOut,
    auth=jwt_auth,
)
def update_requirement(
    request: HttpRequest, contest_id: int, requirement_id: int, payload: RequirementUpdateIn
):
    """Sponsor가 AI 제안이든 기존 항목이든 문구·등급·순서를 직접 고친다."""

    contest = _get_owned_draft_contest(request, contest_id)

    try:
        requirement = contest.requirements.get(id=requirement_id)
    except Requirement.DoesNotExist as exc:
        raise HttpError(404, "Requirement를 찾을 수 없습니다.") from exc

    if payload.grade is not None:
        if payload.grade not in _VALID_GRADES:
            raise HttpError(422, "Requirement grade는 required 또는 optional 이어야 합니다.")
        requirement.grade = payload.grade
    if payload.text is not None:
        sanitized = sanitize_free_text(payload.text)
        if not sanitized:
            raise HttpError(422, "Requirement 내용이 비어 있습니다.")
        requirement.text = sanitized
    if payload.order is not None:
        requirement.order = payload.order

    requirement.save(update_fields=["text", "grade", "order"])
    return RequirementOut(
        id=requirement.id, text=requirement.text, grade=requirement.grade, order=requirement.order
    )


@router.delete("/contests/{contest_id}/requirements/{requirement_id}", auth=jwt_auth)
def delete_requirement(request: HttpRequest, contest_id: int, requirement_id: int):
    """Sponsor가 AI 제안이든 기존 항목이든 체크리스트에서 뺀다."""

    contest = _get_owned_draft_contest(request, contest_id)

    try:
        requirement = contest.requirements.get(id=requirement_id)
    except Requirement.DoesNotExist as exc:
        raise HttpError(404, "Requirement를 찾을 수 없습니다.") from exc

    requirement.delete()
    return {"success": True}
