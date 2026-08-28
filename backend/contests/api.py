"""Contest API — draft 개최, DeliverableType 견적, 공개 목록/상세.

결제·`Escrow`(#9)는 이 티켓 범위 밖이다. 여기서 만든 `Contest`는 항상 draft로 남고,
결제가 확인되면 #9가 `status`를 `published`로 전이시킬 훅만 남겨둔다.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from accounts.models import SponsorProfile
from accounts.sanitize import sanitize_free_text
from verification.models import Verification

from .models import Category, Contest, DeliverableType, Requirement, RequirementChatMessage
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
    ContestCreateIn,
    ContestOut,
    DeliverableTypeOut,
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


# --- AI grill — Requirement 체크리스트 대화형 생성 + Sponsor 수정/삭제/추가 (#20) -----


def _get_owned_draft_contest(request: HttpRequest, contest_id: int) -> Contest:
    """AI grill 대화·Requirement CRUD가 공통으로 쓰는 소유권·상태 게이트.

    타인의 Contest는 draft여도 (get_contest·test_owner_can_view_own_draft_but_stranger_cannot
    과 같은 이유로) 존재 자체를 숨기려 404로 응답한다. 소유자라도 DRAFT를 벗어난
    Contest는 편집을 막는다 — 공개된 뒤 체크리스트가 흔들리면 제출·심사·채점이
    기준으로 삼는 대상 자체가 바뀌어 버린다.
    """

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    auth_user = getattr(request, "auth_user", None)
    if auth_user is None or contest.sponsor.user_id != auth_user.id:
        raise HttpError(404, "Contest를 찾을 수 없습니다.")

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

    prompt = build_chat_prompt(chat_input)

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
    """지금까지의 AI grill 대화 이력 — 다시 들어와도 이어갈 수 있게 한다."""

    contest = _get_owned_draft_contest(request, contest_id)
    return [_turn_out(m) for m in contest.requirement_chat_messages.all()]


@router.post(
    "/contests/{contest_id}/requirements", response=RequirementOut, auth=jwt_auth
)
def add_requirement(request: HttpRequest, contest_id: int, payload: RequirementCreateIn):
    """AI 제안을 그대로, 또는 Sponsor가 고쳐 쓴 문구로 체크리스트에 실제로 추가한다."""

    contest = _get_owned_draft_contest(request, contest_id)

    if payload.grade not in _VALID_GRADES:
        raise HttpError(422, "Requirement grade는 required 또는 optional 이어야 합니다.")

    next_order = contest.requirements.count()
    requirement = Requirement.objects.create(
        contest=contest,
        text=sanitize_free_text(payload.text),
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
