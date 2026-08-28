"""Contest API — draft 개최, DeliverableType 견적, 공개 목록/상세.

결제·`Escrow`(#9)는 이 티켓 범위 밖이다. 여기서 만든 `Contest`는 항상 draft로 남고,
결제가 확인되면 #9가 `status`를 `published`로 전이시킬 훅만 남겨둔다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from core.clock import Clock
from payments.adapters import PGError, PGTimeoutError, get_adapter
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
    CategoryOut,
    ConfirmJudgingExtensionIn,
    ContestCreateIn,
    ContestOut,
    DeliverableTypeOut,
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
            with transaction.atomic():
                payment = JudgingExtensionPayment.objects.create(
                    contest=contest,
                    amount=settings.CONTEST_EXTENSION_FEE,
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
        result_status = adapter.confirm(order_id=str(order_id), simulate=payload.simulate)
    except PGTimeoutError:
        result_status = adapter.query_status(order_id=str(order_id))
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
