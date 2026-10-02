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

from django.db import IntegrityError, transaction
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    F,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.functions import NullIf
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from accounts.sponsor_display import require_sponsor_display_name
from contests.curation import HomeCurationBucket, home_bucket_for, home_bucket_queryset
from contests.images import (
    create_image as create_contest_image_for,
    remove_image as remove_contest_image_for,
    reorder_image as reorder_contest_image_for,
    request_upload_url as request_contest_image_upload_url_for,
)
from contests.search import search_contests
from contests.sponsorship import sponsored_contest_queryset
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from core.banned_words import BannedWordViolation, find_banned_word_violation
from core.clock import Clock
from core.contest_catalog import contest_source_changed
from core.contest_switch import (
    require_contest_product_enabled,
    require_paid_contest_product_enabled,
)
from core.keyset import decode_cursor, keyset_page
from payments.adapters import PGError, get_adapter
from payments.charges import settle_charge
from payments.models import Payment
from policies.scope import current_policy
from verification.models import Verification

from .lifecycle_notifications import notify_contest_updated
from .models import (
    Category,
    Contest,
    ContestChange,
    ContestImage,
    ContestSubmission,
    DeliverableType,
    HomeStatusAxis,
    HostingPermission,
    JudgingExtensionPayment,
    Requirement,
    RequirementChatMessage,
)
from .transitions import claim_contest_transition
from .requirement_chat import (
    ChatTurn,
    ExistingRequirement,
    RequirementChatAdapterError,
    RequirementChatInput,
    build_chat_prompt,
    get_requirement_chat_adapter,
)
from .view_tracking import record_view
from .schemas import (
    MySponsoredContestOut,
    MySponsoredContestPageOut,
    CategoryOut,
    ContestImageCreateIn,
    ContestImageOut,
    ContestImageReorderIn,
    ContestImageUploadUrlIn,
    ContestImageUploadUrlOut,
    ContestListFilters,
    ContestSort,
    ConfirmJudgingExtensionIn,
    ContestCreateIn,
    ContestOut,
    ContestReopenIn,
    ContestUpdateIn,
    DeliverableTypeOut,
    FreeContestCreateIn,
    HomeCurationGroupOut,
    HostingPermissionSelfOut,
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

router = Router(tags=["contests"])
logger = logging.getLogger(__name__)

# Requirement.grade / RequirementIn.grade와 같은 값 집합. create_contest의 인라인
# 체크와 아래 requirement CRUD·chat 제안이 같은 기준을 쓰도록 한 곳에 둔다.
_VALID_GRADES = {"required", "optional"}

# 한 Sponsor가 한 Contest에 쌓을 수 있는 대화 턴 수 상한. 무제한으로 두면 한 Contest가
# 프롬프트에 실리는 대화 이력을 무한정 늘려 이후 매 턴의 LLM 호출 비용·지연을 키운다.
_MAX_CHAT_HISTORY_TURNS = 200

# 홈의 한 묶음이 보여주는 최대 건수 (#94). 홈은 큐레이션이지 탐색이 아니다 —
# 전체는 `/contests`(#39, 필터·정렬·페이지네이션을 이미 갖고 있다)의 몫이다.
# 이전 자리표시 홈(#93)이 전체를 12건으로 잘랐던 것과 같은 정신이다.
_HOME_BUCKET_LIMIT = 6


def _reject_if_banned_public_text(value: str, field_label: str) -> None:
    """공모전 제목·설명에 욕설이 있으면 거절한다(spec #474, #479) — 사칭
    목록은 걸지 않는다: 「운영자 대시보드」는 정당한 공모전 제목이다
    (`core.banned_word_rules.RULES`의 `("contests", ...)` 항목들). 로그인 없이
    열리는 목록·상세가 그대로 그리는 값이라 저장 전에 막는다."""

    violation = find_banned_word_violation(value, check_impersonation=False)
    if violation is BannedWordViolation.PROFANITY:
        raise HttpError(422, f"{field_label}에 욕설을 쓸 수 없습니다.")


def _minimum_total(deliverable_type_ids: list[int]) -> int:
    total = DeliverableType.objects.filter(
        id__in=deliverable_type_ids, is_active=True
    ).aggregate(total=Sum("minimum_prize"))["total"]
    return total or 0


def _serialize_contest(contest: Contest, auth_user: object | None = None) -> ContestOut:
    # `contest.submission_count`는 annotate로 미리 실려 있어야 한다
    # (list_contests/get_contest/get_home_curation) — 새로 만든 Contest는
    # 호출부가 0을 직접 채워 넣는다(create_contest/reopen_contest, 둘 다 방금
    # 만든 행이라 Submission이 있을 수 없다). 여기서 조용히 0으로 기본값을
    # 주지 않는 이유는, annotate를 빠뜨린 새 호출부가 있으면 AttributeError로
    # 바로 드러나야 하기 때문이다 — getattr로 감싸면 그 실수가 "항상 0"이라는
    # 그럴듯한 값으로 위장해 테스트를 통과할 수 있다.
    #
    # `auth_user`를 넘기지 않는 호출부는 `is_owner=False`로 응답한다(ContestOut의
    # 기본값, #164) — list_contests/get_home_curation처럼 "내 것인가"가 화면에
    # 드러나지 않는 목록이다. `contest.sponsor`가 이미 select_related로 실려
    # 있어야 N+1 없이 비교할 수 있다(get_contest가 그렇게 한다).
    is_owner = auth_user is not None and contest.sponsor.user_id == getattr(auth_user, "id", None)
    # `has_own_submission`도 `is_owner`와 같은 자리에서 같은 이유로 계산한다(#245)
    # — `auth_user`를 안 넘기는 호출부(list_contests/get_home_curation)는 목록에
    # "내가 이미 냈는가"가 드러나지 않으므로 쿼리를 내지 않고 기본값 False를 그대로
    # 둔다. `get_contest`만 실제 값을 계산해 공개 상세의 제출 CTA가 문구를 가른다.
    has_own_submission = auth_user is not None and ContestSubmission.objects.filter(
        contest=contest, developer__user_id=getattr(auth_user, "id", None)
    ).exists()
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
        is_free=contest.is_free,
        allows_classroom_import=contest.allows_classroom_import,
        requirements=[
            RequirementOut(id=r.id, text=r.text, grade=r.grade, order=r.order)
            for r in contest.requirements.all()
        ],
        images=[
            ContestImageOut(id=img.id, url=img.url, thumbnail_url=img.thumbnail_url, order=img.order)
            for img in contest.images.all()
        ],
        source_contest_id=contest.source_contest_id,
        created_at=contest.created_at,
        judging_ends_at=contest.judging_ends_at,
        submission_count=contest.submission_count,
        view_count=contest.view_count,
        is_owner=is_owner,
        has_own_submission=has_own_submission,
        sponsor_display_name=contest.sponsor.display_name or None,
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
    """선택한 DeliverableType들의 최소 제안 상금 합계를 등록 전에 보여준다.

    과제에는 "상금미달" 개념이 없었다(과제 라우터가 걷히기 전 `contests.
    assignment_api` 모듈 docstring, #361로 사라졌다) — 이 견적은 유료 공모전
    전용이라 유료 공모전 스위치(#413)가 닫는다.
    """

    require_paid_contest_product_enabled()

    return QuoteOut(
        deliverable_type_ids=payload.deliverable_type_ids,
        minimum_total=_minimum_total(payload.deliverable_type_ids),
    )


@router.post("/contests", response=ContestOut, auth=jwt_auth)
def create_contest(request: HttpRequest, payload: ContestCreateIn):
    """Verification을 마친 Sponsor가 Contest를 draft로 만든다.

    Prize가 선택한 DeliverableType 최소 상금 합계에 미달해도 등록은 성공한다 —
    「상금미달」 배지만 선다. 플랫폼은 신호를 줄 뿐 금지하지 않는다.

    본인확인을 요구하는 **유료** 개최다 — 유료 공모전 스위치(#413)가 닫는다.
    무료 개최는 `create_free_contest`(`POST /contests/free`, #415)가 별도로
    연다 — 본인확인 대신 개최 권한을 요구하고 Prize를 받지 않는다. 과제
    개설 자체는 과제 라우터와 함께 걷혔다(#361, 부모 #358).
    """

    require_paid_contest_product_enabled()

    if not Verification.objects.filter(
        user=request.auth_user, status=Verification.Status.VERIFIED
    ).exists():
        raise HttpError(403, "본인확인을 완료해야 공모전을 개최할 수 있습니다.")

    if not payload.deliverable_type_ids:
        raise HttpError(422, "산출물 종류를 하나 이상 선택해야 합니다.")

    try:
        category = Category.objects.get(id=payload.category_id, is_active=True)
    except Category.DoesNotExist as exc:
        raise HttpError(422, "존재하지 않는 카테고리입니다.") from exc

    deliverable_types = list(
        DeliverableType.objects.filter(id__in=payload.deliverable_type_ids, is_active=True)
    )
    if len(deliverable_types) != len(set(payload.deliverable_type_ids)):
        raise HttpError(422, "존재하지 않는 산출물 종류가 포함되어 있습니다.")

    for requirement in payload.requirements:
        if requirement.grade not in _VALID_GRADES:
            raise HttpError(422, "요구사항 등급은 필수 또는 선택 중 하나여야 합니다.")
        # 공모전 상세에서 참가자 전부가 로그인 없이 보는 공개 본문이다 —
        # 제목·설명과 같은 노출(빠뜨렸던 것을 #480 구조 검사가 잡았다).
        _reject_if_banned_public_text(requirement.text, "요구사항")

    sanitized_title = sanitize_free_text(payload.title)
    sanitized_description = sanitize_free_text(payload.description)
    _reject_if_banned_public_text(sanitized_title, "제목")
    _reject_if_banned_public_text(sanitized_description, "설명")

    sponsor_profile, _created = SponsorProfile.objects.get_or_create(user=request.auth_user)

    minimum_total = sum(dt.minimum_prize for dt in deliverable_types)

    # Contest 행 커밋과 Requirement 일괄 생성이 한 단위여야 한다 — 예를 들어 500자를
    # 넘는 Requirement.text가 DB CHECK/길이 제약에 걸려 bulk_create가 실패해도,
    # Contest만 커밋된 채 남는 고아 레코드를 만들지 않는다.
    with transaction.atomic():
        contest = Contest.objects.create(
            sponsor=sponsor_profile,
            title=sanitized_title,
            category=category,
            description=sanitized_description,
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


# --- 무료 공모전 개최 (#415, ADR-0048) ---------------------------------------


def _require_hosting_permission(user) -> None:
    """개최 권한(`HostingPermission`)이 지금 켜져 있는지 확인한다 — 결제가
    유료 개최를 걸러 주는 자리를 대신한다. 행이 아예 없는 계정은 권한이 없는
    것과 같다(`contests.models.HostingPermission` 독스트링)."""

    permission = HostingPermission.objects.filter(user=user).first()
    if permission is None or not permission.is_granted:
        raise HttpError(403, "무료 공모전 개최 권한이 없습니다.")


@router.get(
    "/contests/free/hosting-permission", response=HostingPermissionSelfOut, auth=jwt_auth
)
def get_own_hosting_permission(request: HttpRequest):
    """로그인한 사용자 본인의 개최 권한 (#415, user story 13). 공개 앱의 무료
    공모전 만들기 화면이 폼을 그리기 전에 이 값을 먼저 확인해, 권한이 없으면
    폼 대신 안내를 보인다 — 헛걸음 방지다. `POST /contests/free`가 실제
    집행자이고, 이 엔드포인트는 화면이 미리 묻는 자리일 뿐이다.

    **`/contests/{contest_id}`보다 먼저 등록해야 한다** — `/contests/mine`과
    같은 이유(위 `list_my_sponsored_contests` 참고).
    """

    permission = HostingPermission.objects.filter(user=request.auth_user).first()
    return HostingPermissionSelfOut(is_granted=bool(permission and permission.is_granted))


@router.post("/contests/free", response=ContestOut, auth=jwt_auth)
def create_free_contest(request: HttpRequest, payload: FreeContestCreateIn):
    """개최 권한이 있는 사용자가 본인확인·결제 없이 무료 공모전 초안을 만든다
    (#415, ADR-0048).

    `create_contest`(유료)와 갈리는 지점 셋: 본인확인을 요구하지 않고,
    Verification 대신 `HostingPermission`을 확인하며, Prize를 받지 않는다
    — 무료 공모전은 상금·최소 제안 상금·상금미달 판정 자체가 없으므로
    `prize`·`required_minimum_prize`는 0, `is_underfunded`는 늘 False로
    만든다.

    공모전 스위치(#271)만 본다 — 유료 스위치(#413)와 무관하게 열려 있다.
    """

    require_contest_product_enabled()
    _require_hosting_permission(request.auth_user)

    if not payload.deliverable_type_ids:
        raise HttpError(422, "산출물 종류를 하나 이상 선택해야 합니다.")

    try:
        category = Category.objects.get(id=payload.category_id, is_active=True)
    except Category.DoesNotExist as exc:
        raise HttpError(422, "존재하지 않는 카테고리입니다.") from exc

    deliverable_types = list(
        DeliverableType.objects.filter(id__in=payload.deliverable_type_ids, is_active=True)
    )
    if len(deliverable_types) != len(set(payload.deliverable_type_ids)):
        raise HttpError(422, "존재하지 않는 산출물 종류가 포함되어 있습니다.")

    for requirement in payload.requirements:
        if requirement.grade not in _VALID_GRADES:
            raise HttpError(422, "요구사항 등급은 필수 또는 선택 중 하나여야 합니다.")
        # 공모전 상세에서 참가자 전부가 로그인 없이 보는 공개 본문이다 —
        # 제목·설명과 같은 노출(빠뜨렸던 것을 #480 구조 검사가 잡았다).
        _reject_if_banned_public_text(requirement.text, "요구사항")

    sanitized_title = sanitize_free_text(payload.title)
    sanitized_description = sanitize_free_text(payload.description)
    _reject_if_banned_public_text(sanitized_title, "제목")
    _reject_if_banned_public_text(sanitized_description, "설명")

    sponsor_profile, _created = SponsorProfile.objects.get_or_create(user=request.auth_user)

    with transaction.atomic():
        contest = Contest.objects.create(
            sponsor=sponsor_profile,
            title=sanitized_title,
            category=category,
            description=sanitized_description,
            prize=0,
            deadline_at=payload.deadline_at,
            status=Contest.Status.DRAFT,
            is_free=True,
            allows_classroom_import=payload.allows_classroom_import,
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
    contest.submission_count = 0
    return _serialize_contest(contest)


@router.post("/contests/{contest_id}/publish", response=ContestOut, auth=jwt_auth)
def publish_free_contest(request: HttpRequest, contest_id: int):
    """개최 권한이 있는 Sponsor가 무료 공모전 초안을 결제 없이 공개한다
    (#415, ADR-0048).

    유료 경로의 `publish-on-payment`(결제 확인이 부르는 훅, `payments.models.
    Payment.on_paid`)와 짝이다 — 이쪽은 사람이 직접 부르는 행위 엔드포인트이고,
    문을 여는 조건이 결제 완료가 아니라 **지금 이 순간의** 개최 권한이다.
    권한을 만든 뒤 회수당했다면 이 draft는 새로 공개할 수 없다(#414 — 이미
    공개된 Contest는 영향받지 않지만, 아직 draft인 것은 새 규칙을 그대로
    적용받는다).

    소유자·DRAFT 게이트는 `_get_owned_draft_contest`가 진다(404/409) — 공모전
    스위치도 그 안에서 이미 확인된다.
    """

    contest = _get_owned_draft_contest(request, contest_id)

    if not contest.is_free:
        raise HttpError(409, "무료 공모전만 이 방법으로 공개할 수 있습니다.")

    _require_hosting_permission(request.auth_user)

    # 체크리스트가 없으면 채점이 볼 기준이 없다 — 유료 경로는 결제 전에 요구사항
    # 단계를 거치지만 이 경로는 버튼 하나라 여기서 막는다.
    if not contest.requirements.exists():
        raise HttpError(422, "요구사항을 하나 이상 적어야 공개할 수 있습니다.")

    # 참가자에게 개최자가 익명으로 보이지 않도록, 공개 직전에 표시 이름을
    # 확인한다(#447) — 초안 상태에서는 요구하지 않는다.
    require_sponsor_display_name(contest.sponsor)

    transitioned = claim_contest_transition("publish-free", contest.pk)
    if not transitioned:
        # 동시에 들어온 다른 요청이 먼저 이겼다 — 정상 경로에서는 도달하지
        # 않아야 한다(_get_owned_draft_contest가 이미 DRAFT를 확인했다).
        raise HttpError(409, "이미 공개되었거나 공개할 수 없는 상태입니다.")

    contest.refresh_from_db()
    contest.submission_count = 0
    return _serialize_contest(contest)


@router.get("/contests", response=list[ContestOut], auth=None)
@paginate(PageNumberPagination, page_size=20)
def list_contests(request: HttpRequest, filters: Query[ContestListFilters]):
    """지금 참가할 수 있는 Contest가 기본이다 — draft·과제는 아무 조건에서도 나오지
    않는다(#227).

    **`closed=true`가 아니면 PUBLISHED만 나온다(#227).** 예전에는 여기가
    `Contest.Status.PUBLICLY_VISIBLE`(PUBLISHED·CLOSED·AWARDED·JUDGING_ENDED
    전부) 통째를 대상으로 삼고 기본 정렬만 마감 오름차순이었다 — 마감된 Contest는
    정의상 마감이 과거이므로 **항상 진행 중인 것보다 앞에 왔고**, 첫 페이지
    위쪽이 가장 오래전에 끝난 Contest로 채워졌다. 화면의 "마감 임박순"이라는
    말이 실제로는 "가장 오래전에 끝난 것 먼저"로 동작하던 버그다. 홈 큐레이션
    (`contests.curation`)이 이미 같은 질문(`HomeStatusAxis`)에 답을 갖고 있으므로
    그 축을 그대로 재사용한다 — OPEN(PUBLISHED)이 기본, `closed=true`면
    IN_JUDGING·COMPLETED(CLOSED·AWARDED·JUDGING_ENDED)로 뒤집는다. 마감된
    Contest의 **상세**는 이 필터와 무관하게 계속 열린다(`get_contest`가 독립적으로
    `PUBLICLY_VISIBLE` 전체를 본다) — 공개 개발자 프로필이 가리키는 Contest가
    404가 되면 안 되므로(#12 리뷰 지적, ADR-0014), 이 엔드포인트가 바꾸는 것은
    "기본으로 무엇을 보여주는가"이지 "무엇을 볼 수 있는가"가 아니다.

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

    **`sort`는 무엇을 보여줄지를 바꾸지 않는다 — 순서만 바꾼다(#227 인수조건).**
    `deliverable_type`/`category`와 달리 `closed`는 필터가 아니라 별도 축이라, 둘을
    조합해도 서로 간섭하지 않는다: `sort=prize`는 `closed` 값과 무관하게 항상
    상금 내림차순이고, `sort=deadline`(기본)만 `closed`에 따라 방향이 뒤집힌다 —
    참가 가능한 것은 마감이 가까운 순(오름차순, "마감임박순"), 마감된 것은 최근에
    마감된 순(내림차순, "최근 마감순")이다. 이 내림차순은 홈 완료 묶음
    (`contests.curation.home_bucket_queryset`의 COMPLETED)이 쓰는 것과 정확히
    같은 표현(`-deadline_at, -id`)이다 — 같은 질문에 두 화면이 다른 순서로
    답하지 않는다.

    정렬에는 항상 `id`를 마지막 키로 붙인다. 상금이나 마감이 동점이면 DB가 순서를
    보장할 이유가 없고, 페이지마다 순서가 달라지면 **같은 Contest가 두 페이지에
    나오고 다른 하나는 어느 페이지에도 안 나온다** — 페이지네이션에서 정렬이
    불안정하면 목록이 조용히 틀리는 그 두 번째 방식이다.

    알 수 없는 값은 500이 아니라 4xx다 — `sort`는 Enum이라 ninja가 422로 막고,
    `category`/`deliverable_type`도 int가 아니면 422다. 존재하지 않는 id는 오류가
    아니라 빈 목록이다(필터는 "그런 게 있느냐"가 아니라 "그것으로 좁혀라"이다).

    **`q`(#449)는 상태·카테고리·요구형태 필터에 AND로 더 얹는 조건이다** — 검색
    모듈(`contests.search`)이 이미 `Contest.Status.PUBLICLY_VISIBLE`로 초안을
    빼고 돌려주지만, 여기서도 위에서 고른 `visible_statuses`(참가 가능/마감)로
    한 번 더 좁힌다. 그래서 초안은 두 겹으로 막혀 있고, `closed` 축과 검색어를
    같이 걸어도(예: 마감된 것 중에서 검색) 서로 간섭하지 않는다. `sort`를
    명시하지 않았는데 `q`가 있으면 관련도순이 기본이다 — 검색어 없이 관련도순을
    요청하면(사용자가 직접 `sort=relevance`를 줬는데 `q`가 비었을 때) 관련도라는
    개념 자체가 성립하지 않으므로 조용히 마감임박순으로 대신한다.

    공모전 제품 스위치(#271)가 꺼지면 이 목록도 닫는다 — 과제는 명단을 두지 않으므로
    (ADR-0028) 대응하는 공개 목록이 애초에 없다.
    """

    require_contest_product_enabled()

    # 참가 가능(OPEN=PUBLISHED)이 기본, closed=true면 마감된 쪽(IN_JUDGING·
    # COMPLETED = CLOSED·AWARDED·JUDGING_ENDED)이다 — 홈 큐레이션과 같은 축
    # (HomeStatusAxis)을 그대로 쓴다: DRAFT·Assignment는 그 축에서 HIDDEN이라
    # 어느 쪽으로도 나오지 않는다(PUBLICLY_VISIBLE과 정확히 같은 배제).
    if filters.closed:
        visible_statuses = Contest.Status.HOME_AXIS.where(
            HomeStatusAxis.IN_JUDGING
        ) | Contest.Status.HOME_AXIS.where(HomeStatusAxis.COMPLETED)
    else:
        visible_statuses = Contest.Status.HOME_AXIS.where(HomeStatusAxis.OPEN)

    queryset = Contest.objects.filter(status__in=visible_statuses)

    if filters.category is not None:
        queryset = queryset.filter(category_id=filters.category)
    if filters.deliverable_type is not None:
        queryset = queryset.filter(deliverable_types__id=filters.deliverable_type)

    # `q`가 있고 `sort`를 명시하지 않았으면 관련도순이 기본이다(부모 #444 스펙).
    effective_sort = filters.sort
    if effective_sort is None:
        effective_sort = ContestSort.RELEVANCE if filters.q else ContestSort.DEADLINE

    matched_ids: list[int] | None = None
    if filters.q:
        matched_ids = search_contests(
            query=filters.q,
            category=filters.category,
            deliverable_type=filters.deliverable_type,
        )
        queryset = queryset.filter(id__in=matched_ids)

    if effective_sort is ContestSort.RELEVANCE and matched_ids:
        # 검색 모듈이 이미 관련도순으로 돌려준 id 순서를 그대로 지킨다 — DB가
        # `id__in`의 결과를 그 순서로 돌려줄 이유가 없으므로 위치를 Case로 못박는다.
        ordering: tuple = (
            Case(*[When(pk=pk, then=position) for position, pk in enumerate(matched_ids)]),
        )
    elif effective_sort is ContestSort.PRIZE:
        ordering = ("-prize", "id")
    elif filters.closed:
        ordering = ("-deadline_at", "-id")
    else:
        ordering = ("deadline_at", "id")

    return (
        queryset.order_by(*ordering)
        .select_related("category")
        .prefetch_related("deliverable_types", "requirements", "images")
        # 참가작 수(#106, spec #105) — 목록은 행이 가장 많은 화면이라 행마다
        # 세면 N+1이 정확히 여기서 터진다. `distinct=True`는 `deliverable_type`
        # 필터가 M2M을 조인할 때(위 `deliverable_types__id` 필터) Count가 그
        # 조인으로 부풀려지는 것을 막는다 — 필터가 없을 때도 안전하고 비용도
        # 무시할 만하다.
        .annotate(submission_count=Count("submissions", distinct=True))
        # 개최자의 공개용 표시 이름(#447) — 이 엔드포인트는 ninja가 QuerySet을
        # 직접 ContestOut으로 옮기므로(_serialize_contest를 거치지 않는다),
        # `contest.sponsor.display_name`을 파이썬에서 읽는 대신 SQL 단계에서
        # 같은 이름의 애노테이션으로 만들어 둬야 필드가 채워진다. `NullIf`가
        # 빈 문자열을 null로 바꾼다 — 스키마 계약("비어 있으면 null")과 같다.
        .annotate(sponsor_display_name=NullIf(F("sponsor__display_name"), Value("")))
    )


# 한 페이지에 몇 행인가. 오프셋 시절의 `page_size=20` 을 그대로 이어받는다.
_MY_CONTESTS_PAGE_SIZE = 20


@router.get("/contests/mine", response=MySponsoredContestPageOut, auth=jwt_auth)
def list_my_sponsored_contests(request: HttpRequest, after: str | None = None):
    """Sponsor 가 자기가 연 공모전들과 각각의 「다음 행동」을 본다 (#81).

    **`/contests/{contest_id}` 보다 먼저 등록해야 한다.** 아래에 두면 django-ninja
    가 `mine` 을 `contest_id` 로 읽어 422 를 낸다 — 참가자 쪽 `/submissions/mine`
    이 이미 겪은 함정이다.

    **`draft` 도 나온다.** 공개 목록은 draft 를 감추지만 여기는 「내 것」이고, 초안인
    채로 결제하지 않으면 아무 일도 일어나지 않는다는 사실을 말해 줄 곳이 여기밖에
    없다.

    Sponsor 프로필이 없으면 빈 목록이다 — 개최한 적 없는 사람은 정상적인 상태이지
    없는 리소스가 아니다(`/submissions/mine` 과 같은 관용구).

    **자르기는 커서다**(#151/#152) — 「몇 번째부터」가 아니라 「마지막으로 본 행
    다음부터」를 묻는다. 오프셋은 목록이 머리 쪽에서 자라면 경계가 밀린다 — 개최자가
    「더 보기」를 넘기는 중에 공모전을 하나 더 열면 2페이지가 1페이지의 행을 다시
    돌려주고, 원래 그 자리에 와야 했던 행은 어느 페이지에도 안 나온다. 정렬 마지막
    키에 `id` 를 붙이는 이유도 운영자 지급 큐와 같다 — `created_at` 이 같은 두 행의
    순서를 DB 가 보장하지 않는다.

    공모전 제품 스위치(#271)가 꺼지면 이 목록도 닫는다.
    """

    require_contest_product_enabled()

    if after is not None and decode_cursor(after) is None:
        # 읽을 수 없는 커서는 조용히 처음부터가 아니라 422 다 — 그러면 「더 보기」를
        # 눌렀는데 목록이 처음으로 되돌아간 화면이 되고, 무엇을 봤고 못 봤는지 알 수
        # 없게 된다(운영자 지급 큐와 같은 규율, #151).
        raise HttpError(422, "읽을 수 없는 커서입니다.")

    profile = SponsorProfile.objects.filter(user=request.auth_user).first()
    if profile is None:
        return {"items": [], "count": 0, "next": None}

    # 시각과 정책을 이 요청 스코프에서 **한 번씩만** 구한다 — `core.api.tick` 과
    # `distributions.services.run_due_distributions` 가 쓰는 것과 같은 관용구
    # (#75, ADR-0023). 행마다 구하면 조회가 행 수만큼 늘고, 게다가 한 화면 안에서
    # 행마다 다른 시각으로 판정하게 된다.
    as_of = Clock.now()
    policy = current_policy()

    contests = (
        sponsored_contest_queryset(
            Contest.objects.filter(sponsor=profile),
            as_of=as_of,
            policy=policy,
        )
        .annotate(judged_as_of=Value(as_of, output_field=DateTimeField()))
        .order_by("-created_at", "-id")
    )

    items, next_cursor = keyset_page(contests, after=after, page_size=_MY_CONTESTS_PAGE_SIZE)
    return {"items": items, "count": contests.count(), "next": next_cursor}


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
    성능 때문에 그 판정을 묶음별 쿼리(`contests.curation.home_bucket_queryset`)로 다시
    표현한다 — 왜 그래야 했는지, 그리고 갈리지 않게 무엇을 해 두었는지는 그
    함수의 docstring을 본다.

    `DRAFT`는 어느 `contests.curation.home_bucket_queryset` 필터에도 안 걸린다 — 결제 전
    Contest가 새지 않는다는 계약은 공개 목록/상세와 같다(#94 인수조건).

    네 묶음은 **비어 있어도 항상 다 나온다** — `HomeCurationBucket`을 순회해
    목록을 만들므로, 실제로 그 부류의 Contest가 하나도 없으면 `contests: []`인
    채로 그 묶음이 응답에 실린다. 화면이 그 자리에서 "비어 있다"고 보여줄 수
    있는 것은 이 항상-네-묶음 계약 덕분이다(#94 인수조건 — 섹션이 통째로
    사라지면 안 된다).

    각 묶음은 최대 `_HOME_BUCKET_LIMIT`건만 담는다 — 홈은 큐레이션이지 탐색이
    아니다. 전체를 보려면 `/contests`(#39)로 간다.

    공모전 제품 스위치(#271)가 꺼지면 이 큐레이션도 닫는다.
    """

    require_contest_product_enabled()

    now = Clock.now()

    base = (
        Contest.objects.select_related("category")
        .prefetch_related("deliverable_types", "requirements", "images")
        # 참가작 수(#106, spec #105) — 네 묶음 각각의 쿼리(home_bucket_queryset)가
        # 이 `base`를 그대로 이어받아 필터만 얹으므로, annotate를 여기 한 번만
        # 둬도 네 쿼리 전부에 실린다. 홈 큐레이션이 이미 경계해 둔 N+1(#94)과
        # 같은 이유로 묶음마다·행마다 따로 세지 않는다.
        .annotate(submission_count=Count("submissions", distinct=True))
    )

    groups = []
    for bucket in HomeCurationBucket:
        contests = list(home_bucket_queryset(base, bucket, now=now)[:_HOME_BUCKET_LIMIT])

        for contest in contests:
            # `contests.curation.home_bucket_queryset`가 `home_bucket_for`의 판정을 SQL로
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
                    "home_bucket_queryset과 home_bucket_for가 갈렸다.",
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
    """공모전 제품 스위치(#271)가 꺼지면 이 상세도 닫는다 — 과제 상세를 따로
    답하던 `contests.assignment_api`는 과제 라우터와 함께 걷혔다(#361)."""

    require_contest_product_enabled()

    try:
        contest = (
            # `sponsor`도 select_related한다 — draft 소유자 판정(아래)과
            # `is_owner`(#164, `_serialize_contest`) 둘 다 `contest.sponsor.user_id`를
            # 읽으므로, 여기서 미리 조인해 두지 않으면 로그인한 방문자가 볼 때마다
            # SponsorProfile을 한 번 더 조회하는 N+1이 생긴다.
            Contest.objects.select_related("category", "sponsor")
            .prefetch_related("deliverable_types", "requirements", "images")
            # 참가작 수(#106, spec #105) — 단건이라도 annotate로 얻는다.
            # `_serialize_contest`가 `contest.submission_count`를 그대로 읽는다.
            .annotate(submission_count=Count("submissions", distinct=True))
            .get(id=contest_id)
        )
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

    auth_user = getattr(request, "auth_user", None)

    # PUBLISHED·CLOSED·AWARDED·JUDGING_ENDED 모두 공개다 — list_contests와 같은
    # 기준(Contest.Status.PUBLICLY_VISIBLE).
    if not Contest.Status.PUBLICLY_VISIBLE(contest.status):
        is_owner = auth_user is not None and contest.sponsor.user_id == auth_user.id
        if not is_owner:
            raise HttpError(404, "공모전을 찾을 수 없습니다.")

    # 익명(SSR 공개 상세, ADR-0015 — 서버 컴포넌트는 Authorization을 보내지 않는다)
    # 이면 auth_user가 None이라 `_serialize_contest`가 그대로 is_owner=False를
    # 낸다. 로그인한 브라우저가 BFF를 거쳐 이 엔드포인트를 다시 부를 때만(예:
    # 공개 상세의 "제출하러 가기" CTA가 자기 Contest인지 확인할 때) 실제 값이
    # 나온다 — 공개 SSR과 인증 구역이 같은 엔드포인트를 서로 다른 신뢰 수준으로
    # 부르는 것은 이 파일의 다른 auth=None 엔드포인트(예: record_contest_view)와
    # 같은 모양이다.
    return _serialize_contest(contest, auth_user=auth_user)


@router.patch("/contests/{contest_id}", response=ContestOut, auth=jwt_auth)
def update_contest(request: HttpRequest, contest_id: int, payload: ContestUpdateIn):
    """DRAFT는 결제가 문을 닫기 전까지, PUBLISHED는 마감이 문을 닫기 전까지
    브리프를 고칠 수 있다 (#113, 부모 #110; 제출 기간 중 편집은 #473, ADR-0051).

    게이트는 `_get_owned_content_editable_contest`가 진다 — 소유자가 아니면
    404("있는지가 아니라 없는지"), CONTENT_EDITABLE을 벗어났으면(CLOSED 이후)
    409("분명히 거절당한다").

    **돈에 닿는 값(`prize`)은 PUBLISHED에서는 아예 받지 않는다.** DRAFT에서
    바뀌면 `required_minimum_prize`(최소 제안 상금 합계)와 `is_underfunded`
    (상금미달 배지)를 새로 구한다 — 그 값은 "개최 시점의 스냅샷"인데 DRAFT는
    아직 개최된 것이 아니므로 다시 계산하는 것이 원래 의미에 맞다(결제가 그
    스냅샷을 굳힌다). PUBLISHED에서는 이미 결제·Escrow가 그 금액을 확정했으므로
    `prize`가 오면 422로 거절하고, `deliverable_type_ids`가 바뀌어도 그 스냅샷은
    다시 계산하지 않는다(굳어진 값 그대로 둔다) — 상금·개최 조건이 이미 굳은
    뒤에 배지 판정만 조용히 바뀌면 안 된다.

    **이미 붙인 Requirement는 요구형태를 바꿔도 지우지 않는다** — 자유 텍스트라
    구조적으로 무효가 되지 않고, 그것을 쓴 사람이 Sponsor 자신이다(spec #110
    Implementation Decisions). 이 엔드포인트는 `Requirement`를 전혀 건드리지
    않는다 — 화면이 "요구형태를 바꿨다"는 사실을 스스로 안내한다.

    **무료 공모전은 `prize`를 받지 않는다(#415, ADR-0048).** 상금·결제·Escrow가
    아예 없는 공모전이라 바꿀 대상 자체가 없다 — 화면이 이 필드를 아예 감추는
    것과 별개로(사고 예방), 여기서도 거절한다(방어).

    **마감은 지금보다 뒤로만 옮길 수 있다(#473).** 이미 지난 시각으로 바꾸면
    422다 — DRAFT든 PUBLISHED든 같다. 스캔이 다음 틱에 그 마감을 보고 곧바로
    닫아버리는 것보다, 조작 시점에 분명히 거절하는 편이 낫다.

    **`published`에서 실제로 바뀐 필드가 있으면 `ContestChange`를 남기고 이미
    제출한 참가자에게 알린다** (`_record_contest_change`) — DRAFT에서는 남기지
    않는다(위 함수 독스트링 참고).
    """

    contest = _get_owned_content_editable_contest(request, contest_id)

    if contest.status != Contest.Status.DRAFT and payload.prize is not None:
        raise HttpError(
            422,
            "제출을 받는 동안에는 상금을 바꿀 수 없습니다 — 이미 결제로 확정된 금액입니다.",
        )

    if contest.is_free and payload.prize is not None:
        raise HttpError(422, "무료 공모전은 상금을 설정할 수 없습니다.")

    if not contest.is_free and payload.allows_classroom_import is not None:
        raise HttpError(422, "클래스에서 들여오기는 무료 공모전에서만 허용할 수 있습니다.")

    if payload.deadline_at is not None and payload.deadline_at <= Clock.now():
        raise HttpError(422, "마감은 지금보다 뒤여야 합니다.")

    before: dict = {}
    after: dict = {}

    with transaction.atomic():
        if payload.title is not None:
            sanitized_title = sanitize_free_text(payload.title)
            if not sanitized_title:
                raise HttpError(422, "제목이 비어 있습니다.")
            _reject_if_banned_public_text(sanitized_title, "제목")
            if sanitized_title != contest.title:
                before["title"] = contest.title
                after["title"] = sanitized_title
            contest.title = sanitized_title

        if payload.description is not None:
            sanitized_description = sanitize_free_text(payload.description)
            _reject_if_banned_public_text(sanitized_description, "설명")
            if sanitized_description != contest.description:
                before["description"] = contest.description
                after["description"] = sanitized_description
            contest.description = sanitized_description

        if payload.category_id is not None:
            try:
                category = Category.objects.get(id=payload.category_id, is_active=True)
            except Category.DoesNotExist as exc:
                raise HttpError(422, "존재하지 않는 카테고리입니다.") from exc
            if category.id != contest.category_id:
                before["category_id"] = contest.category_id
                after["category_id"] = category.id
            contest.category = category

        if payload.deadline_at is not None:
            if payload.deadline_at != contest.deadline_at:
                before["deadline_at"] = contest.deadline_at.isoformat()
                after["deadline_at"] = payload.deadline_at.isoformat()
            contest.deadline_at = payload.deadline_at

        deliverable_types_changed = False
        if payload.deliverable_type_ids is not None:
            if not payload.deliverable_type_ids:
                raise HttpError(422, "산출물 종류를 하나 이상 선택해야 합니다.")
            deliverable_types = list(
                DeliverableType.objects.filter(
                    id__in=payload.deliverable_type_ids, is_active=True
                )
            )
            if len(deliverable_types) != len(set(payload.deliverable_type_ids)):
                raise HttpError(422, "존재하지 않는 산출물 종류가 포함되어 있습니다.")
            previous_type_ids = sorted(contest.deliverable_types.values_list("id", flat=True))
            new_type_ids = sorted(dt.id for dt in deliverable_types)
            if previous_type_ids != new_type_ids:
                before["deliverable_type_ids"] = previous_type_ids
                after["deliverable_type_ids"] = new_type_ids
            contest.deliverable_types.set(deliverable_types)
            deliverable_types_changed = True

        if payload.prize is not None:
            if payload.prize != contest.prize:
                before["prize"] = contest.prize
                after["prize"] = payload.prize
            contest.prize = payload.prize

        if (
            contest.status == Contest.Status.DRAFT
            and not contest.is_free
            and (deliverable_types_changed or payload.prize is not None)
        ):
            # PUBLISHED에서는 이 스냅샷을 다시 계산하지 않는다 — 위 함수
            # 독스트링 참고(결제·Escrow가 이미 그 금액을 확정했다). 무료
            # 공모전은 상금 개념 자체가 없다(#415) — `prize`는 위에서 이미
            # 거절했고, 요구형태가 바뀌어도 `required_minimum_prize`·
            # `is_underfunded`는 항상 0/False로 남는다(생성 때와 같은 값).
            # 지금 붙어 있는 deliverable_types를 있는 그대로 합산한다 —
            # `_minimum_total`(생성/재개최가 "새로 고를 수 있는 것"을 거를 때
            # 쓰는 is_active=True 필터)을 여기 그대로 쓰면, 운영자가 그 사이
            # 비활성화한 타입이 응답의 deliverable_types 목록(_serialize_contest,
            # is_active를 보지 않는다)에는 여전히 나오는데 최소 상금 합계에서만
            # 조용히 빠진다 — 같은 응답 안에서 "무엇이 붙어 있는가"와 "최소
            # 상금이 얼마인가"가 서로 다른 집합을 가리키는 불일치다(코드리뷰
            # 지적). 그래서 여기서는 필터 없이 지금 붙어 있는 것 전부를 더한다.
            minimum_total = (
                contest.deliverable_types.aggregate(total=Sum("minimum_prize"))["total"] or 0
            )
            contest.required_minimum_prize = minimum_total
            contest.is_underfunded = contest.prize < minimum_total

        # 「클래스에서 들여오기」 허용은 참가 조건이 아니라 강사에게 여는 문이라
        # `ContestChange`·참가자 알림에 싣지 않는다 — 참가자에게 「공모전이 바뀌었다」는
        # 소음이다. 이미 들여온 공모전 문제는 알아야 하므로 신호만 낸다(#547, ADR-0054).
        import_allowance_changed = (
            payload.allows_classroom_import is not None
            and payload.allows_classroom_import != contest.allows_classroom_import
        )
        if payload.allows_classroom_import is not None:
            contest.allows_classroom_import = payload.allows_classroom_import

        contest.save()
        if import_allowance_changed:
            _announce_contest_source_changed(contest)

        if contest.status == Contest.Status.DRAFT and payload.prize is not None:
            # 결제가 문을 닫기 전까지는 결제 화면을 먼저 열어(POST /payments가
            # REQUESTED Payment를 만든다) 상금을 확인한 뒤에도 초안으로 돌아가
            # 다시 고칠 수 있다(#111의 "요구사항으로 돌아가기"). Escrow는
            # `Payment.prize_amount`로 예치되고 실제 Payout은 `Contest.prize`
            # 를 기준으로 나가므로(Payment.journal,
            # payouts/services.py) — 이 상금 변경 시점에 진행 중인(REQUESTED)
            # Payment가 있다면 그 스냅샷을 지금 값으로 맞춘다. **불변식: REQUESTED
            # Payment는 그것이 속한 Contest와 다른 금액을 가질 수 없다.** PAID는
            # 이미 굳어진(그리고 Contest를 published로 넘긴) 스냅샷이라 손대지
            # 않는다 — PAID가 존재한다는 것 자체가 이 Contest가 더 이상 DRAFT가
            # 아니라는 뜻이라 이 분기에 도달하지도 않는다(위에서 이미 prize를
            # 거절했다).
            Payment.objects.filter(
                contest=contest, status=Payment.Status.REQUESTED
            ).update(prize_amount=contest.prize)

    if after:
        _record_contest_change(contest, ContestChange.Action.UPDATED, before=before, after=after)

    contest.refresh_from_db()
    # DRAFT는 결제 전까지 참가할 수 없으므로 항상 0이지만, PUBLISHED는(#473)
    # 이미 참가작이 있을 수 있다 — create_contest/reopen_contest(둘 다 방금
    # 만든 draft라 0이 맞다)와 달리 여기서는 실제로 세야 한다.
    contest.submission_count = contest.submissions.count()
    return _serialize_contest(contest)


@router.post("/contests/{contest_id}/views", auth=None)
def record_contest_view(request: HttpRequest, contest_id: int):
    """브라우저가 Contest 상세를 연 뒤 알린다 (#109, 부모 #105, `ContestView`).

    서버 렌더(`get_contest`)는 이 엔드포인트를 부르지 않는다 — 클라이언트
    컴포넌트가 마운트된 뒤에만 이 경로를 친다(미리 불러오기·크롤러는
    브라우저를 마운트하지 않으므로 세지 않는다). 판정(날짜별 중복
    제거·Sponsor 자기 조회 배제)은 `contests.view_tracking.record_view`가
    전부 한다 — 이 함수는 대상 Contest가 공개된 것인지만 `get_contest`와
    같은 기준으로 확인한다.

    이 응답 자체에는 조회수를 싣지 않는다 — 이 엔드포인트는 "봤다"는 사건을
    받을 뿐이고, 그 사건이 반영된 숫자는 목록·큐레이션·지표 화면이 각자
    `Contest.view_count`(DB)를 읽어 보여준다(#446). #109 시절에는 조회수가
    Sponsor 전용이라 공개 표면 어디에도 실리지 않았지만, 지금은 공개 목록·
    랜딩 큐레이션 응답(`ContestOut.view_count`)이 그 숫자를 그대로 싣는다 —
    바뀐 것은 "누가 보는가"이지 이 엔드포인트의 응답 모양이 아니다.

    공모전 제품 스위치(#271)가 꺼지면 이 기록도 닫는다.
    """

    require_contest_product_enabled()

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

    if not Contest.Status.PUBLICLY_VISIBLE(contest.status):
        auth_user = getattr(request, "auth_user", None)
        is_owner = auth_user is not None and contest.sponsor.user_id == auth_user.id
        if not is_owner:
            raise HttpError(404, "공모전을 찾을 수 없습니다.")

    record_view(contest, request)
    return {"success": True}


@router.post("/contests/{contest_id}/reopen", response=ContestOut, auth=jwt_auth)
def reopen_contest(request: HttpRequest, contest_id: int, payload: ContestReopenIn):
    """유찰(참여자 0명 전액 환불, #17)된 Contest를 복제해 새 Contest를 draft로 만든다
    (#22, ADR-0001).

    요구사항(`Requirement`, 이 프로젝트의 "체크리스트")·`Category`·`DeliverableType`
    선택·제목·설명·**참고 이미지(`ContestImage`, #236)**는 원본에서 그대로
    복제된다 — Prize와 마감기한만 새로 받는다. 이미지는 순서까지 그대로
    복제되지만 바이트는 옮기지 않는다: 새 `ContestImage` 행이 원본과 **같은
    `object_key`**를 가리킨다(어댑터에 복사 메서드가 없다, ADR-0005/0032) — 그래서
    한 오브젝트를 원본과 사본 두 Contest가 함께 참조하게 되고, 어느 한쪽에서
    이미지를 빼도(`remove_contest_image`가 행만 지운다) 다른 쪽의 이미지는
    깨지지 않는다.

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

    본인확인을 요구하고 REFUNDED Payment(유료 결제의 흔적)를 전제하는 **유료**
    경로라, 새 개최와 같이 유료 공모전 스위치(#413)가 막는다.
    """

    require_paid_contest_product_enabled()

    with transaction.atomic():
        try:
            original = (
                Contest.objects.select_for_update()
                .select_related("category", "sponsor")
                .get(id=contest_id)
            )
        except Contest.DoesNotExist as exc:
            raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

        if original.sponsor.user_id != request.auth_user.id:
            raise HttpError(403, "본인이 개최한 공모전만 재개최할 수 있습니다.")

        if not Contest.Status.REOPENABLE(original.status):
            # 실제 판정 근거는 아래 REFUNDED Payment 존재 여부이지 이 status 값 자체가 아니다 —
            # 어느 status 가 해당하는지는 Contest.Status.REOPENABLE 이 답한다(#141).
            raise HttpError(409, "마감된 공모전만 재개최할 수 있습니다.")

        if not Payment.objects.filter(contest=original, status=Payment.Status.REFUNDED).exists():
            # CLOSED이지만 환불되지 않았다 — 참여자가 있어 정상적으로 마감됐거나
            # (Escrow: "참가자가 한 명이라도 있으면 Sponsor에게 되돌아가지 않는다"),
            # 아직 환불 스캔(#17)이 돌지 않았다. 어느 쪽이든 재개최 대상이 아니다.
            raise HttpError(409, "전액 환불된(유찰) 공모전만 재개최할 수 있습니다.")

        if original.reopenings.exists():
            # 이미 한 번 재개최됐다 — original 행을 위에서 잠갔으므로 이 확인과
            # 아래 생성 사이에 다른 요청이 끼어들 수 없다(리뷰 지적 5). 몇 번째
            # 사본인지는 source_contest_id 체인을 따라가면 된다(ADR-0001).
            raise HttpError(409, "이미 재개최된 공모전입니다.")

        if not Verification.objects.filter(
            user=request.auth_user, status=Verification.Status.VERIFIED
        ).exists():
            raise HttpError(403, "본인확인을 완료해야 공모전을 개최할 수 있습니다.")

        if not original.category.is_active:
            raise HttpError(422, "카테고리가 더 이상 활성화되어 있지 않습니다.")

        active_deliverable_types = list(original.deliverable_types.filter(is_active=True))
        if not active_deliverable_types:
            raise HttpError(
                422, "선택했던 산출물 종류가 더 이상 활성화되어 있지 않습니다."
            )

        minimum_total = sum(dt.minimum_prize for dt in active_deliverable_types)

        new_contest = Contest.objects.create(
            sponsor=original.sponsor,
            title=original.title,
            category=original.category,
            # `original`은 항상 공모전이다 — REOPENABLE은 REFUNDED Payment를
            # 요구하고(Assignment에는 결제 자체가 없다), 그래서 여기 도달하는
            # `original.kind`는 항상 CONTEST다. 그래도 손으로 못 박아 둔다(#213).
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

        # 참고 이미지도 순서까지 그대로 복제한다(#236) — 새 행이 원본과 같은
        # object_key를 가리킨다("지우지 않고 행만 뗀다", ADR-0032). 원본이 재개최
        # 시점에 이미 정원(`PlatformPolicy.max_contest_images`)을 지켰던 행이므로
        # 그 상한을 여기서 다시 확인할 이유가 없다 — 개수가 늘지 않는 복제다.
        ContestImage.objects.bulk_create(
            [
                ContestImage(
                    contest=new_contest,
                    object_key=image.object_key,
                    order=image.order,
                )
                for image in original.images.all()
            ]
        )

    new_contest.refresh_from_db()
    # 방금 만든 행이라 Submission이 있을 수 없다 — annotate 대신 직접 0을 채운다
    # (_serialize_contest 참고).
    new_contest.submission_count = 0
    return _serialize_contest(new_contest)


_ACTIVE_EXTENSION_PAYMENT_STATUSES = [JudgingExtensionPayment.Status.REQUESTED]


def _reject_if_judging_period_is_not_extendable(contest: Contest) -> None:
    if contest.is_free:
        # 무료 공모전에는 유료 심사기간 연장이 없다(#417, ADR-0048) — 유료
        # 스위치(#413)가 켜진 dev·CI에서도 무료 공모전 자신은 이 경로를 쓸 수
        # 없어야 한다. 스위치는 "이 기능이 배포에 있는가"만 보고, 이 검사는
        # "이 Contest 에 그 기능이 뜻이 있는가"를 본다 — 둘은 다른 질문이다.
        raise HttpError(409, "무료 공모전은 심사기간을 유료로 연장할 수 없습니다.")

    if not Contest.Status.JUDGING_EXTENDABLE(contest.status):
        raise HttpError(409, "지금은 심사기간을 연장할 수 있는 상태가 아닙니다.")

    # 시간 창은 Contest 가 안다(#143) — Award 가드·Sponsor 번역기와 같은 메서드다.
    if not contest.judging_window_open(Clock.now()):
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
    `POST .../extend-judging-period/{order_id}/confirm`뿐이다(#13 리뷰 지적 1).

    같은 Contest에 대해 두 요청이 동시에 들어와도 진행 중인(REQUESTED) 연장 결제가
    하나만 남아야 한다(#13 리뷰 지적 2) — `Contest` 행을 `select_for_update`로 잠가
    동시 요청을 직렬화하고, `unique_pending_judging_extension_payment_per_contest`
    부분 유니크 제약을 두 번째 방어선으로 둔다.

    **PG 호출은 그 잠금 밖에서 한다**(#126) — 벤더가 느리면 그 Contest 의 모든 쓰기가
    같이 멈추고 DB 커넥션을 물고 있게 된다. 행 생성까지만 트랜잭션 안이다.

    유료 공모전 스위치(#413)가 꺼지면 이 결제도 닫는다 — 과제에는 심사기간
    자체가 없다(ADR-0028), 무료 공모전에는 유료 심사기간 연장이 없다(ADR-0048).
    """

    require_paid_contest_product_enabled()

    with transaction.atomic():
        try:
            contest = Contest.objects.select_for_update().select_related("sponsor").get(
                id=contest_id
            )
        except Contest.DoesNotExist as exc:
            raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

        if contest.sponsor.user_id != request.auth_user.id:
            raise HttpError(403, "본인이 개최한 공모전만 심사기간을 연장할 수 있습니다.")

        _reject_if_judging_period_is_not_extendable(contest)

        # 이미 진행 중인 연장 결제가 있으면 새로 만들지 않고 그대로 돌려준다 —
        # 중복 클릭·재요청이 새 주문을 계속 만들어내지 않게 하는 멱등성이다.
        payment = (
            JudgingExtensionPayment.objects.filter(
                contest=contest, status__in=_ACTIVE_EXTENSION_PAYMENT_STATUSES
            )
            .order_by("-created_at")
            .first()
        )
        if payment is None:
            try:
                # 중첩 atomic(세이브포인트) — payments.api.initiate_payment와 같은
                # 이유. amount와 extension_days를 같은 policy 조회에서 함께
                # 스냅샷한다(#78 코드리뷰 지적 2).
                policy = current_policy()
                with transaction.atomic():
                    payment = JudgingExtensionPayment.objects.create(
                        contest=contest,
                        amount=policy.judging_extension_fee,
                        extension_days=policy.judging_extension_days,
                        extension_number=contest.judging_extension_count + 1,
                        status=JudgingExtensionPayment.Status.REQUESTED,
                    )
            except IntegrityError:
                # Contest 잠금에도 불구하고 부분 유니크 제약에 걸렸다 — 방어적 안전망이다.
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
    """연장 결제를 동기 확인한다 — Charge 확정 경로 하나(`payments.charges.settle_charge`).

    PG 호출은 어떤 `transaction.atomic()` 블록 밖에서 일어나고, 타임아웃이면 `query_status`
    로 확정하며, 그 재확인마저 실패하면 미확정으로 남긴다(#87 지적 4, #125). 벤더의
    명시적 거절은 502 다.

    유료 공모전 스위치(#413)가 꺼지면 이 확인도 닫는다 — 스위치가 꺼진 뒤로는
    `initiate_judging_period_extension`이 막혀 있어 새 진행 중 결제가 생기지 않는다.
    """

    require_paid_contest_product_enabled()

    charge_qs = JudgingExtensionPayment.objects.select_related("contest__sponsor")
    try:
        payment = charge_qs.get(order_id=order_id, contest_id=contest_id)
    except JudgingExtensionPayment.DoesNotExist as exc:
        raise HttpError(404, "연장 결제를 찾을 수 없습니다.") from exc

    if payment.contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 공모전의 연장 결제만 확인할 수 있습니다.")

    try:
        payment = settle_charge(
            charge_qs,
            order_id=order_id,
            adapter=get_adapter(),
            simulate=payload.simulate,
            payment_key=payload.payment_key,
        )
    except PGError as exc:
        raise HttpError(502, str(exc)) from exc

    return 200, _serialize_extension_payment(payment)


# --- AI grill — Requirement 체크리스트 대화형 생성 + Sponsor 수정/삭제/추가 (#20) -----


def _get_owned_contest(request: HttpRequest, contest_id: int) -> Contest:
    """소유자만 통과하는 읽기 전용 게이트 — 상태(draft/published/closed)는 안 본다.

    Sponsor 자신의 AI grill 대화 이력을 읽는 건 아무것도 바꾸지 않으므로, Contest가
    공개된 뒤에도 계속 볼 수 있어야 한다. 타인의 Contest는 존재 자체를 숨기려 404로
    응답한다(get_contest·test_owner_can_view_own_draft_but_stranger_cannot과 같은 이유).

    **공모전 제품 스위치(#271)를 여기 한 곳에서 본다.** 이 함수의 유일한 두
    호출부(`_get_owned_draft_contest`와 그 아래 `list_requirement_chat_messages`)가
    AI grill·Requirement CRUD·이미지 CRUD·`update_draft_contest`까지 이 저장소의
    공모전 전용 쓰기·읽기 표면 전부를 이 한 자리로 모은다 — 스위치가 꺼지면 그
    표면 전부가 이 게이트 하나에서 404 로 닫힌다.
    """

    require_contest_product_enabled()

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

    auth_user = getattr(request, "auth_user", None)
    if auth_user is None or contest.sponsor.user_id != auth_user.id:
        raise HttpError(404, "공모전을 찾을 수 없습니다.")

    return contest


def _get_owned_draft_contest(request: HttpRequest, contest_id: int) -> Contest:
    """AI grill 대화 전송·이미지 CRUD가 공통으로 쓰는 소유권·상태 게이트 — 소유자라도
    DRAFT를 벗어난 Contest는 막는다.

    **이 문은 #473 이후에도 그대로 DRAFT뿐이다.** 브리프·요구사항은 제출을 받는
    동안(published)에도 열렸지만(`_get_owned_content_editable_contest`), AI
    grill과 이미지는 열지 않기로 했다 — AI grill은 "체크리스트를 처음부터 함께
    만드는" 대화 스캐폴드라 이미 확정된 체크리스트를 직접 고치는 지금의 CRUD와
    쓰임이 겹치고, 이미지는 공개된 뒤에도 바뀌면 마감·채점과 무관하게 화면에 이미
    노출된 자료가 조용히 바뀌는 모양이라 이번 티켓의 근거(제출·심사·채점 기준의
    안정성)가 곧바로 적용되지 않는다. 둘 다 넓히지 않는 편이 이 티켓의 범위를
    "브리프 필드·요구사항 체크리스트"로 좁게 유지한다.

    **`Contest.Status.EDITABLE`이 아니라 `status == DRAFT`를 직접 비교한다.**
    이 게이트가 지키는 엔드포인트들이 결제 전 초안에서만 말이 되는 표면이기
    때문이다(#207 코드리뷰 회귀: test_only_draft_can_be_updated_no_status_
    silently_passes).
    """

    contest = _get_owned_contest(request, contest_id)

    if contest.status != Contest.Status.DRAFT:
        raise HttpError(409, "공개된 공모전의 요구사항 체크리스트는 더 이상 수정할 수 없습니다.")

    return contest


def _get_owned_content_editable_contest(request: HttpRequest, contest_id: int) -> Contest:
    """`update_contest`(브리프)·Requirement CRUD가 공통으로 쓰는 소유권·상태 게이트
    (#473, ADR-0051).

    `_get_owned_draft_contest`보다 넓다 — DRAFT뿐 아니라 제출을 받는 동안
    (PUBLISHED)에도 통과시킨다(`Contest.Status.CONTENT_EDITABLE`). 마감 뒤
    (CLOSED·AWARDED·JUDGING_ENDED)에는 그대로 막는다 — 채점 스냅샷(`Score`)이
    이미 그 체크리스트를 근거로 만들어졌고 그것은 append-only라(ADR-0006), 그
    뒤에 기준이 바뀌면 이의 심판이 "무엇을 근거로 판정했는가"를 재현할 수 없다.
    """

    contest = _get_owned_contest(request, contest_id)

    if not Contest.Status.CONTENT_EDITABLE(contest.status):
        raise HttpError(
            409,
            "마감된 공모전은 더 이상 수정할 수 없습니다 — 채점이 이미 지금의 요구사항을 "
            "근거로 진행되었거나 진행됩니다.",
        )

    return contest


def _record_contest_change(
    contest: Contest,
    action: "ContestChange.Action",
    *,
    before: dict,
    after: dict,
) -> None:
    """`ContestChange` 한 행을 남기고, 공개된(제출을 받는) Contest면 참가자에게도
    알린다 (#473, ADR-0051).

    **published일 때만 남긴다.** DRAFT 수정은 아직 아무도 그 조건을 보고
    참가하지 않았으니 감사 흔적으로서의 무게가 없다 — 결제 전에는 "무엇이든
    몇 번이든 고칠 수 있다"는 것이 이 저장소의 원래 전제(CONTEXT.md 「Contest」)이고,
    그 경로에 이력·알림을 얹으면 소음만 늘어난다.
    """

    if contest.status != Contest.Status.PUBLISHED:
        return

    now = Clock.now()
    ContestChange.objects.create(
        contest=contest, action=action, before=before, after=after, changed_at=now
    )
    notify_contest_updated(contest)
    _announce_contest_source_changed(contest)


def _announce_contest_source_changed(contest: Contest) -> None:
    """공개 중인 무료 공모전의 원본이 바뀌었다고 공유층에 알린다 (#547, ADR-0054) — 그
    공모전을 들여온 「공모전 문제」가 따라간다(#548). 커밋 뒤에 보낸다: 받는 쪽이 원본을
    다시 읽을 때 새 값이 보여야 한다. 유료 공모전·초안은 들여올 수 없으니 알릴 것이 없다."""

    if not contest.is_free or contest.status != Contest.Status.PUBLISHED:
        return
    contest_id = contest.pk
    transaction.on_commit(lambda: contest_source_changed.send(sender=Contest, contest_id=contest_id))


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
            "이 공모전의 AI grill 대화가 너무 길어졌습니다. 지금까지 나온 체크리스트로 "
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
    """AI 제안을 그대로, 또는 Sponsor가 고쳐 쓴 문구로 체크리스트에 실제로 추가한다.

    게이트는 `_get_owned_content_editable_contest` — DRAFT뿐 아니라 제출을 받는
    동안(PUBLISHED)에도 연다(#473, ADR-0051). PUBLISHED에서 실제로 추가되면
    `ContestChange`를 남기고 이미 제출한 참가자에게 알린다.
    """

    contest = _get_owned_content_editable_contest(request, contest_id)

    if payload.grade not in _VALID_GRADES:
        raise HttpError(422, "요구사항 등급은 필수 또는 선택 중 하나여야 합니다.")

    sanitized_text = sanitize_free_text(payload.text)
    if not sanitized_text:
        raise HttpError(422, "요구사항 내용이 비어 있습니다.")
    _reject_if_banned_public_text(sanitized_text, "요구사항")

    next_order = contest.requirements.count()
    requirement = Requirement.objects.create(
        contest=contest,
        text=sanitized_text,
        grade=payload.grade,
        order=next_order,
    )
    _record_contest_change(
        contest,
        ContestChange.Action.REQUIREMENT_ADDED,
        before={},
        after={"id": requirement.id, "text": requirement.text, "grade": requirement.grade},
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
    """Sponsor가 AI 제안이든 기존 항목이든 문구·등급·순서를 직접 고친다.

    게이트는 `add_requirement`와 같은 `_get_owned_content_editable_contest`
    (#473, ADR-0051)."""

    contest = _get_owned_content_editable_contest(request, contest_id)

    try:
        requirement = contest.requirements.get(id=requirement_id)
    except Requirement.DoesNotExist as exc:
        raise HttpError(404, "요구사항을 찾을 수 없습니다.") from exc

    before = {"text": requirement.text, "grade": requirement.grade}

    if payload.grade is not None:
        if payload.grade not in _VALID_GRADES:
            raise HttpError(422, "요구사항 등급은 필수 또는 선택 중 하나여야 합니다.")
        requirement.grade = payload.grade
    if payload.text is not None:
        sanitized = sanitize_free_text(payload.text)
        if not sanitized:
            raise HttpError(422, "요구사항 내용이 비어 있습니다.")
        _reject_if_banned_public_text(sanitized, "요구사항")
        requirement.text = sanitized
    if payload.order is not None:
        requirement.order = payload.order

    requirement.save(update_fields=["text", "grade", "order"])

    after = {"text": requirement.text, "grade": requirement.grade}
    if after != before:
        _record_contest_change(
            contest,
            ContestChange.Action.REQUIREMENT_UPDATED,
            before={"id": requirement.id, **before},
            after={"id": requirement.id, **after},
        )
    return RequirementOut(
        id=requirement.id, text=requirement.text, grade=requirement.grade, order=requirement.order
    )


@router.delete("/contests/{contest_id}/requirements/{requirement_id}", auth=jwt_auth)
def delete_requirement(request: HttpRequest, contest_id: int, requirement_id: int):
    """Sponsor가 AI 제안이든 기존 항목이든 체크리스트에서 뺀다.

    게이트는 `add_requirement`와 같은 `_get_owned_content_editable_contest`
    (#473, ADR-0051)."""

    contest = _get_owned_content_editable_contest(request, contest_id)

    try:
        requirement = contest.requirements.get(id=requirement_id)
    except Requirement.DoesNotExist as exc:
        raise HttpError(404, "요구사항을 찾을 수 없습니다.") from exc

    removed = {"id": requirement.id, "text": requirement.text, "grade": requirement.grade}
    requirement.delete()
    _record_contest_change(
        contest, ContestChange.Action.REQUIREMENT_REMOVED, before=removed, after={}
    )
    return {"success": True}


# --- ContestImage (#234/#236, ADR-0032) ---------------------------------------
#
# 발급·등록·순서변경·제거의 실제 로직은 `contests.images`에 있다 — 이 라우터는
# 자기 게이트(`_get_owned_draft_contest`: 소유자 + DRAFT)로
# 확인한 `Contest`를 그 함수들에 넘길 뿐이다. 과제 라우터(`contests.
# assignment_api`)도 한때 같은 함수들을 자신의 게이트(`_get_owned_editable_
# assignment`)로 불렀지만(#236) #361로 걷혔다 — 「무엇을 고칠 수 있는가」는
# 게이트가 답하고 「어떻게 고치는가」는 이 모듈이 답한다는 경계는 그대로다.
#
# **#473(ADR-0051)이 브리프·요구사항을 PUBLISHED에도 열었지만 이미지는 열지
# 않았다** — 여전히 `_get_owned_draft_contest`(DRAFT뿐)를 쓴다. 그 함수의
# 독스트링이 이유를 적는다.


@router.post(
    "/contests/{contest_id}/images/upload-url",
    response=ContestImageUploadUrlOut,
    auth=jwt_auth,
)
def request_contest_image_upload_url(
    request: HttpRequest, contest_id: int, payload: ContestImageUploadUrlIn
):
    """Sponsor가 참고 이미지를 올리기 전, 공개 이미지 버킷으로의 presigned POST를
    받는다 (#234).

    게이트는 Requirement와 같은 `_get_owned_draft_contest` — 소유자가 아니면
    404, DRAFT를 벗어났으면 409다("자기 공모전이 아니면 업로드를 발급받을 수
    없다", spec #225 acceptance criteria).

    presigned **POST**를 쓴다(presigned PUT이 아니다) — 크기 상한
    (`MAX_CONTEST_IMAGE_BYTES`)과 `content_type`을 서명된 정책 조건에 담아,
    브라우저를 믿지 않고 스토리지 자신이 위반을 거절하게 한다(ADR-0032). 실제로
    행이 생기는 것은 업로드 완료 뒤 `POST .../images`를 호출할 때다 — 이 엔드포인트는
    URL만 내준다.
    """

    contest = _get_owned_draft_contest(request, contest_id)
    return request_contest_image_upload_url_for(contest, payload)


@router.post(
    "/contests/{contest_id}/images", response=ContestImageOut, auth=jwt_auth
)
def add_contest_image(request: HttpRequest, contest_id: int, payload: ContestImageCreateIn):
    """브라우저가 presigned POST로 실제 바이트를 올린 뒤, 그 object_key를 이
    Contest의 이미지 목록에 등록한다 (#234)."""

    contest = _get_owned_draft_contest(request, contest_id)
    return create_contest_image_for(contest, payload)


@router.patch(
    "/contests/{contest_id}/images/{image_id}", response=ContestImageOut, auth=jwt_auth
)
def reorder_contest_image(
    request: HttpRequest, contest_id: int, image_id: int, payload: ContestImageReorderIn
):
    """Sponsor가 이미지의 노출 순서를 고친다 (#234) — Requirement.order와 같은 모양."""

    contest = _get_owned_draft_contest(request, contest_id)
    return reorder_contest_image_for(contest, image_id, payload)


@router.delete("/contests/{contest_id}/images/{image_id}", auth=jwt_auth)
def remove_contest_image(request: HttpRequest, contest_id: int, image_id: int):
    """이미지를 뺀다 — **이 행만 지운다.** object_key가 가리키는 오브젝트는 그대로
    남는다(어댑터에 삭제 메서드가 없다, ADR-0005/0032) — 재개최(#236)가 같은
    오브젝트를 가리키는 새 행을 만들 수 있기 때문이다."""

    contest = _get_owned_draft_contest(request, contest_id)
    remove_contest_image_for(contest, image_id)
    return {"success": True}
