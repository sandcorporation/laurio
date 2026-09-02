"""Payout 실행 API (#15, #50, ADR-0004, ADR-0007, ADR-0008, ADR-0020).

- `POST /contests/{contest_id}/payout` — Developer가 자신의 Award된 Contest에
  대해 지급을 요청한다. Escrow가 아직 해제되지 않았으면(Handover가 released가
  아니면) 409다. 멱등하다 — 이미 요청되어 있으면 새 idempotency_key를 만들지
  않고 그대로 어댑터에 재요청한다(payments.api.initiate_payment와 같은 관용구).
- `GET /contests/{contest_id}/payout` — Developer 본인이 총액·수수료·원천징수·
  실지급액 내역과, 무엇을 기다리고 있으며 다음에 뭘 해야 하는지를 조회한다.
- `POST /payouts/{idempotency_key}/confirm` — 동기 확인. 타임아웃이 나도 곧바로
  실패로 처리하지 않고 조회로 확정한다.
- `POST /payouts/webhook` — 토스(Fake 포함)가 비동기로 통지하는
  `payout.changed` 웹훅. 서명이 없거나 틀리면 거부한다.
- `POST /payouts/{idempotency_key}/identity` — 지급이 확정된(CONFIRMED_IDENTITY_
  PENDING 이상) 뒤에만 Developer가 주민등록번호를 제출한다.
- `POST /payouts/{idempotency_key}/seller-registration` — CONFIRMED_SELLER_
  PENDING에서 Seller 등록을 다시 시도한다(#50). 실물 어댑터가 붙기 전까지는
  fake 시나리오 재현용이기도 하다.
- `GET /operator/payouts` — Operator가 두 대기(신원/Seller) 중 어느 쪽이 막혀
  있는지 본다(#50 AC).

두 확정 경로(confirm/webhook) 모두 `payouts.services.mark_confirmed`/
`mark_failed`라는 같은 조건부 UPDATE 관문을 통과한다 — 어느 쪽이 먼저 도착하든,
몇 번 재전송되든 원장에는 정확히 한 번만 분개가 남는다. `mark_confirmed`는 그
안에서 Seller 등록도 함께 시작한다(ADR-0020).
"""

from __future__ import annotations

import json
from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core.operator_auth import OperatorAuth
from distributions.models import DistributionShare
from handovers.models import Handover
from payments.webhook_security import verify_webhook_signature
from policies.services import get_current_policy

from .adapters import PayoutError, PayoutTimeoutError, get_adapter
from .adapters_toss import verify_toss_webhook_signature
from .models import Payout, PayoutWebhookDelivery, Seller, TaxIdentity
from .schemas import (
    ConfirmPayoutIn,
    ErrorOut,
    IdentitySubmitIn,
    OperatorPayoutOut,
    PayoutOut,
    SellerPhoneSubmitIn,
    SellerRegistrationRetryIn,
    SellerWebhookOut,
    WebhookIn,
    WebhookOut,
)
from .services import (
    advance_seller_pending_payouts,
    get_or_create_payout,
    mark_confirmed,
    mark_failed,
    retry_seller_registration,
    submit_identity,
    submit_seller_phone,
)

router = Router(tags=["payouts"])
# Operator 표면 — appeals.api.operator_router와 같은 원칙으로 라우터 전체가
# 기본 거부다(#44).
operator_router = Router(tags=["operator", "payouts"], auth=OperatorAuth())


def _payout_contest_id(payout: Payout) -> int:
    """이 Payout이 속한 Contest — Handover(Award) 경로거나 DistributionShare(#16)
    경로거나 정확히 하나를 통해서만 판정된다(payout_exactly_one_target 제약).
    """

    if payout.handover_id is not None:
        return payout.handover.award.contest_id
    return payout.distribution_share.distribution.contest_id


def _payout_owner_user_id(payout: Payout) -> int:
    """이 Payout을 받을 Developer의 user_id — 위와 같은 이유로 두 경로 중 하나를
    통해 판정된다.
    """

    if payout.handover_id is not None:
        return payout.handover.award.submission.developer.user_id
    return payout.distribution_share.submission.developer.user_id


def _payout_developer_id(payout: Payout) -> int:
    """이 Payout을 받을 `accounts.DeveloperProfile`의 pk — Seller는 이 단위로
    등록된다(payouts.services._resolve_developer와 같은 판정).
    """

    if payout.handover_id is not None:
        return payout.handover.award.submission.developer_id
    return payout.distribution_share.submission.developer_id


# 다음 행동 안내(#50 AC — "Developer가 자기 Payout이 무엇을 기다리는지와 다음에
# 무엇을 해야 하는지 볼 수 있다"). status·seller_status 조합마다 사람이 읽을
# 문장을 고정해 둔다 — 침묵은 상금이 사라진 것으로 읽힌다.
def _next_action_message(payout: Payout, seller: Seller | None) -> str:
    if payout.status == Payout.Status.REQUESTED:
        return "지급 확인 절차가 진행 중입니다. 잠시만 기다려주세요."
    if payout.status == Payout.Status.CONFIRMED_SELLER_PENDING:
        if seller is not None and seller.status == Seller.Status.UNDER_REVIEW:
            return (
                "지급대행사 심사가 진행 중입니다(주간 지급 한도 초과 또는 추가 확인 "
                "요청) — 상금은 안전하게 보관되어 있으며 심사가 끝나면 자동으로 다음 "
                "단계로 넘어갑니다."
            )
        if seller is not None and seller.status == Seller.Status.REJECTED:
            return (
                "지급대행사 수취인 등록이 거절되었습니다. 상금은 원장에 그대로 "
                "남아 있습니다 — 운영자에게 문의해주세요."
            )
        if seller is not None and seller.status == Seller.Status.APPROVAL_REQUIRED:
            # #57 추가 인수조건 — "PENDING과 APPROVAL_REQUIRED가 화면에서
            # 다르게 읽힌다." 이건 Developer의 차례다: 이미 포트원으로 본인확인을
            # 했더라도 토스가 지급대행사로서 별도로 본인인증 문자를 보낸다
            # (ADR-0020 — 벤더가 갈려 두 번 일어난다).
            return (
                "지급대행사(토스페이먼츠)가 보낸 본인인증 문자로 인증을 완료해주세요 — "
                "이미 본인확인을 하셨더라도 지급대행사 자체 의무라 다시 인증이 "
                "필요합니다. 인증이 끝나면 자동으로 다음 단계로 넘어갑니다."
            )
        if (
            seller is None or seller.status == Seller.Status.PENDING
        ) and not (seller is not None and seller.phone_number):
            # PENDING이면서 전화번호도 아직 없다 — "우리가 응답을 기다린다"가
            # 아니라 "Developer가 낼 것이 있다"는 뜻이다. PENDING을 "아무도 할
            # 일이 없다"로 뭉뚱그리면 이 경우를 놓친다(#57 추가 인수조건).
            return (
                "지급대행사 수취인 등록에 전화번호가 필요합니다 — 아래에서 제출해주세요."
            )
        return "지급대행사 수취인 등록이 진행 중입니다. 완료되면 자동으로 다음 단계로 넘어갑니다."
    if payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING:
        return "세무 신고를 위해 주민등록번호를 제출해주세요."
    if payout.status == Payout.Status.CONFIRMED:
        return "지급이 완료되었습니다."
    if payout.status == Payout.Status.FAILED:
        return "지급 요청이 실패했습니다. 다시 시도해주세요."
    return ""  # pragma: no cover - 위 분기가 Status 전체를 다룬다.


def _serialize(payout: Payout) -> PayoutOut:
    seller = Seller.objects.filter(developer_id=_payout_developer_id(payout)).first()
    return PayoutOut(
        idempotency_key=payout.idempotency_key,
        contest_id=_payout_contest_id(payout),
        prize_amount=payout.prize_amount,
        platform_fee_amount=payout.platform_fee_amount,
        withholding_tax_amount=payout.withholding_tax_amount,
        net_amount=payout.net_amount,
        status=payout.status,
        has_identity=TaxIdentity.objects.filter(payout=payout).exists(),
        seller_status=seller.status if seller is not None else None,
        next_action_message=_next_action_message(payout, seller),
        created_at=payout.created_at,
    )


def _get_owned_handover(request: HttpRequest, contest_id: int) -> Handover:
    try:
        handover = Handover.objects.select_related(
            "award__contest", "award__submission__developer"
        ).get(award__contest_id=contest_id)
    except Handover.DoesNotExist as exc:
        raise HttpError(404, "이 Contest는 아직 Award되지 않아 Handover가 없습니다.") from exc

    if handover.award.submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 Award된 Submission의 Developer만 접근할 수 있습니다.")
    return handover


@router.post(
    "/contests/{contest_id}/payout",
    response={201: PayoutOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def request_payout(request: HttpRequest, contest_id: int):
    handover = _get_owned_handover(request, contest_id)

    if handover.status != Handover.Status.RELEASED:
        raise HttpError(409, "아직 Escrow가 해제되지 않아 지급을 요청할 수 없습니다.")

    # 이 요청 스코프에서 정책을 한 번만 읽는다(#75, ADR-0023) — core.api.tick이
    # Clock.now()를 한 번만 구해 재사용하는 것과 같은 관용구.
    policy = get_current_policy()
    payout = get_or_create_payout(handover, policy=policy)

    adapter = get_adapter()
    adapter.request_payout(idempotency_key=str(payout.idempotency_key), amount=payout.net_amount)

    return 201, _serialize(payout)


@router.get(
    "/contests/{contest_id}/payout", response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut}, auth=jwt_auth
)
def get_payout(request: HttpRequest, contest_id: int):
    """Developer 본인의 지급 내역을 조회한다.

    Award/Handover 경로(수동 요청)와 Distribution 경로(#16, 내부 스캔이 자동으로
    요청)를 모두 본다 — 이전에는 Handover가 없는 Contest(=무응답 1/N 배분으로
    지급된 Contest)를 조회하면 무조건 404였다. Distribution으로 지급받은
    Developer가 자기 지급 내역을 확인할 방법 자체가 없었던 것이 이 조회의
    핵심 결함이었다.
    """

    handover = (
        Handover.objects.select_related("award__contest", "award__submission__developer")
        .filter(award__contest_id=contest_id)
        .first()
    )
    if handover is not None:
        if handover.award.submission.developer.user_id != request.auth_user.id:
            raise HttpError(403, "본인이 Award된 Submission의 Developer만 접근할 수 있습니다.")

        payout = Payout.objects.filter(handover=handover).select_related(
            "handover__award__contest"
        ).first()
        if payout is None:
            raise HttpError(404, "아직 지급 요청이 없습니다.")
        return 200, _serialize(payout)

    share = (
        DistributionShare.objects.select_related("distribution__contest", "submission__developer")
        .filter(
            distribution__contest_id=contest_id,
            submission__developer__user_id=request.auth_user.id,
        )
        .first()
    )
    if share is None:
        raise HttpError(
            404, "이 Contest는 아직 Award되지 않았고, Distribution 대상도 아닙니다."
        )

    payout = Payout.objects.filter(distribution_share=share).select_related(
        "distribution_share__distribution__contest"
    ).first()
    if payout is None:
        raise HttpError(404, "아직 지급 요청이 없습니다.")

    return 200, _serialize(payout)


def _get_owned_payout(request: HttpRequest, idempotency_key: UUID) -> Payout:
    try:
        payout = Payout.objects.select_related(
            "handover__award__contest",
            "handover__award__submission__developer",
            "distribution_share__distribution__contest",
            "distribution_share__submission__developer",
        ).get(idempotency_key=idempotency_key)
    except Payout.DoesNotExist as exc:
        raise HttpError(404, "지급 요청을 찾을 수 없습니다.") from exc

    if _payout_owner_user_id(payout) != request.auth_user.id:
        raise HttpError(403, "본인의 지급 요청만 접근할 수 있습니다.")
    return payout


@router.post(
    "/payouts/{idempotency_key}/confirm",
    response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def confirm_payout(request: HttpRequest, idempotency_key: UUID, payload: ConfirmPayoutIn):
    payout = _get_owned_payout(request, idempotency_key)

    if payout.status != Payout.Status.REQUESTED:
        # 이미 다른 경로(웹훅 등)로 확정·실패되어 있다 — 그대로 현재 상태를
        # 돌려준다(재전송에 안전).
        return 200, _serialize(payout)

    adapter = get_adapter()
    try:
        result_status = adapter.confirm(
            idempotency_key=str(idempotency_key), simulate=payload.simulate
        )
    except PayoutTimeoutError:
        # 타임아웃은 실패가 아니다 — 실제 결과를 조회로 확정한다(ADR-0008).
        result_status = adapter.query_status(idempotency_key=str(idempotency_key))
    except PayoutError as exc:
        raise HttpError(502, str(exc)) from exc

    if result_status == "paid":
        payout = mark_confirmed(idempotency_key, seller_simulate=payload.seller_simulate)
    elif result_status == "failed":
        payout = mark_failed(idempotency_key)
    else:
        # 아직 확정할 수 없다(pending) — 함부로 실패 처리하지 않는다. 이후
        # 웹훅이나 재조회가 마저 확정한다.
        payout.refresh_from_db()

    return 200, _serialize(payout)


@router.post(
    "/payouts/webhook",
    response={200: WebhookOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=None,
)
def receive_webhook(request: HttpRequest, payload: WebhookIn):
    """`payout.changed` 웹훅. 재전송·순서 뒤바뀜에 안전하다.

    서명은 DB를 건드리기 전에 가장 먼저 검증한다 — 실패하면 Payout 조회도,
    `PayoutWebhookDelivery` 기록도, 원장 반영도 전부 일어나지 않는다
    (payments.api.receive_webhook과 같은 순서, #9 리뷰 지적 2).
    """

    from django.conf import settings

    if not verify_webhook_signature(
        webhook_id=payload.webhook_id,
        order_id=str(payload.idempotency_key),
        status=payload.status,
        signature=payload.signature,
        secret=settings.PAYOUT_WEBHOOK_SECRET,
    ):
        raise HttpError(401, "웹훅 서명이 없거나 올바르지 않습니다.")

    try:
        known_payout = Payout.objects.get(idempotency_key=payload.idempotency_key)
    except Payout.DoesNotExist as exc:
        raise HttpError(404, "알 수 없는 idempotency_key 입니다.") from exc

    PayoutWebhookDelivery.objects.create(
        payout_id=known_payout.id,
        webhook_id=payload.webhook_id,
        idempotency_key=payload.idempotency_key,
        event_status=payload.status,
    )

    if payload.status == "paid":
        payout = mark_confirmed(payload.idempotency_key)
    elif payload.status == "failed":
        payout = mark_failed(payload.idempotency_key)
    else:
        raise HttpError(422, "status는 paid 또는 failed 여야 합니다.")

    return 200, WebhookOut(
        received=True, idempotency_key=payload.idempotency_key, status=payout.status
    )


@router.post(
    "/payouts/{idempotency_key}/identity",
    response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def submit_payout_identity(
    request: HttpRequest, idempotency_key: UUID, payload: IdentitySubmitIn
):
    """지급이 확정된(CONFIRMED_IDENTITY_PENDING 이상) 뒤에만 주민등록번호를
    받는다(ADR-0008) — 가입 시점이나 지급 요청 시점에는 수집하지 않는다.
    """

    payout = _get_owned_payout(request, idempotency_key)

    # CONFIRMED_SELLER_PENDING도 신원 제출을 받는다 — 두 대기는 서로 독립적이다
    # (#50, ADR-0020). Seller 등록이 아직 안 끝났다는 이유로 신원 제출까지
    # 막으면, 먼저 끝난 쪽이 있어도 아무것도 진행할 수 없다.
    if payout.status not in (
        Payout.Status.CONFIRMED_IDENTITY_PENDING,
        Payout.Status.CONFIRMED_SELLER_PENDING,
        Payout.Status.CONFIRMED,
    ):
        raise HttpError(
            409, "지급이 확정된 뒤에만 신원 정보를 제출할 수 있습니다."
        )

    payout = submit_identity(payout, payload.resident_registration_number)
    return 200, _serialize(payout)


@router.post(
    "/payouts/{idempotency_key}/seller-registration",
    response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def retry_payout_seller_registration(
    request: HttpRequest, idempotency_key: UUID, payload: SellerRegistrationRetryIn
):
    """CONFIRMED_SELLER_PENDING에서 Seller 등록을 다시 시도한다(#50, ADR-0020).

    실물 어댑터가 붙기 전까지는 fake 시나리오(한도 초과·심사 필요·거절)가 결국
    부분 승인으로 풀리는 것을 재현하는 유일한 경로이기도 하다 — 실제 토스
    지급대행은 이 자리를 웹훅이나 배치 재조회로 대신하게 된다(#57).
    """

    payout = _get_owned_payout(request, idempotency_key)

    if payout.status != Payout.Status.CONFIRMED_SELLER_PENDING:
        raise HttpError(
            409, "Seller 등록 대기 상태에서만 재시도할 수 있습니다."
        )

    payout = retry_seller_registration(payout, simulate=payload.simulate)
    return 200, _serialize(payout)


@router.post(
    "/payouts/{idempotency_key}/seller-phone",
    response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def submit_payout_seller_phone(
    request: HttpRequest, idempotency_key: UUID, payload: SellerPhoneSubmitIn
):
    """토스 셀러 등록(businessType=INDIVIDUAL)의 individual 객체가 요구하는
    전화번호를 제출한다(#57 추가 인수조건).

    `submit_payout_identity`와 달리 Payout 상태를 확인하지 않는다 — Seller는
    Developer 단위 개념이라 전화번호도 마찬가지다(Payout이 아직 REQUESTED여도
    미리 받아 둘 수 있다). 저장 직후 CONFIRMED_SELLER_PENDING에 머물던 같은
    Developer의 Payout이 있으면 곧바로 재시도한다(`submit_seller_phone`).
    """

    payout = _get_owned_payout(request, idempotency_key)
    developer_id = _payout_developer_id(payout)

    from accounts.models import DeveloperProfile

    developer = DeveloperProfile.objects.get(pk=developer_id)
    submit_seller_phone(developer, payload.phone_number)

    payout.refresh_from_db()
    return 200, _serialize(payout)


# --- 실물 토스 웹훅 (#57) ----------------------------------------------------------
#
# `/payouts/webhook`(위)은 Fake 어댑터·기존 테스트가 쓰는 우리 자체 HMAC
# 스킴이다(payments.webhook_security 재사용). 실제 토스는 `payout.changed`/
# `seller.changed`에만 다른 서명 스킴(헤더 기반, 보안 키로 HMAC)을 쓴다 —
# `adapters_toss.verify_toss_webhook_signature`가 그 스킴을 검증한다. 두
# 엔드포인트를 분리해 두는 이유는 기존 Fake 기반 테스트(#50/#15)가 하나도
# 깨지지 않게 하기 위해서다 — 실물 웹훅 URL은 배포 환경에서만 등록된다(#52,
# 이 티켓 범위 밖).


def _toss_webhook_signature_ok(request: HttpRequest) -> bool:
    from django.conf import settings

    return verify_toss_webhook_signature(
        payload=request.body,
        transmission_time=request.headers.get("tosspayments-webhook-transmission-time", ""),
        signature_header=request.headers.get("tosspayments-webhook-signature"),
        secure_key=settings.TOSS_API_SECURE_KEY,
    )


@router.post(
    "/payouts/webhook/toss",
    response={200: WebhookOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=None,
)
def receive_toss_payout_webhook(request: HttpRequest):
    """실제 토스가 보내는 `payout.changed` 웹훅. 서명은 DB를 건드리기 전에
    가장 먼저 검증한다(#9 리뷰 지적 2와 같은 순서).

    본문 구조는 벤더 문서가 공개한 뼈대(`eventType`/`data`)를 최선으로
    추정한 것이다 — staging에서 실제로 한 번 받아 확인하기 전까지는 정확한
    필드명을 단정하지 않는다(#57 알아둘 것). `refPayoutId`(우리
    idempotency_key)를 찾지 못하면 다른 방식(`data.id`)도 시도한다.
    """

    if not _toss_webhook_signature_ok(request):
        raise HttpError(401, "웹훅 서명이 없거나 올바르지 않습니다.")

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError(400, "웹훅 본문이 JSON이 아닙니다.") from exc

    data = body.get("data") or {}
    ref_payout_id = data.get("refPayoutId") or data.get("id")
    vendor_status = data.get("status")
    webhook_id = request.headers.get("tosspayments-webhook-transmission-id", "")

    if not ref_payout_id:
        raise HttpError(422, "웹훅 본문에서 지급 식별자를 찾을 수 없습니다.")

    try:
        idempotency_key = UUID(str(ref_payout_id))
    except ValueError as exc:
        raise HttpError(422, "웹훅의 지급 식별자가 유효한 UUID가 아닙니다.") from exc

    try:
        known_payout = Payout.objects.get(idempotency_key=idempotency_key)
    except Payout.DoesNotExist as exc:
        raise HttpError(404, "알 수 없는 idempotency_key 입니다.") from exc

    from .adapters_toss import _FAILED_PAYOUT_STATUSES, _PAID_PAYOUT_STATUSES

    if vendor_status in _PAID_PAYOUT_STATUSES:
        our_status = "paid"
    elif vendor_status in _FAILED_PAYOUT_STATUSES:
        our_status = "failed"
    else:
        # 아직 REQUESTED/IN_PROGRESS다 — 확정할 수 없으니 조용히 기록만 하고
        # 상태는 건드리지 않는다.
        our_status = "pending"

    PayoutWebhookDelivery.objects.create(
        payout_id=known_payout.id,
        webhook_id=webhook_id,
        idempotency_key=idempotency_key,
        event_status=our_status,
    )

    if our_status == "paid":
        payout = mark_confirmed(idempotency_key)
    elif our_status == "failed":
        payout = mark_failed(idempotency_key)
    else:
        payout = known_payout

    return 200, WebhookOut(received=True, idempotency_key=idempotency_key, status=payout.status)


@router.post(
    "/payouts/webhook/toss-seller",
    response={200: SellerWebhookOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=None,
)
def receive_toss_seller_webhook(request: HttpRequest):
    """실제 토스가 보내는 `seller.changed` 웹훅 — Seller가 등록 이후 비동기로
    (본인인증·KYC 심사 결과) 상태를 바꿀 때 온다. `register()`를 우리가 다시
    부르지 않아도 이 경로로 Seller.status가 갱신되고, 그 즉시 이 Developer의
    CONFIRMED_SELLER_PENDING Payout들을 다음 단계로 밀어준다
    (`advance_seller_pending_payouts`).
    """

    if not _toss_webhook_signature_ok(request):
        raise HttpError(401, "웹훅 서명이 없거나 올바르지 않습니다.")

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError(400, "웹훅 본문이 JSON이 아닙니다.") from exc

    data = body.get("data") or {}
    ref_seller_id = data.get("refSellerId") or ""
    seller_id = data.get("sellerId") or ""
    vendor_status = data.get("status")

    from .adapters_toss import _SELLER_STATUS_MAP

    our_status = _SELLER_STATUS_MAP.get(vendor_status)
    if our_status is None:
        raise HttpError(422, f"알 수 없는 status 입니다: {vendor_status!r}")

    seller = None
    if ref_seller_id.startswith("laurio-developer-"):
        developer_id_str = ref_seller_id.removeprefix("laurio-developer-")
        if developer_id_str.isdigit():
            seller = Seller.objects.filter(developer_id=int(developer_id_str)).first()
    if seller is None and seller_id:
        seller = Seller.objects.filter(seller_id=seller_id).first()
    if seller is None:
        raise HttpError(404, "알 수 없는 Seller 입니다.")

    weekly_limit_body = data.get("weeklyLimit") or {}
    Seller.objects.filter(pk=seller.pk).update(
        seller_id=seller_id or seller.seller_id,
        status=our_status,
        weekly_limit_amount=weekly_limit_body.get("amount") if our_status == "partially_approved" else None,
    )

    advance_seller_pending_payouts(seller.developer)

    return 200, SellerWebhookOut(received=True, seller_id=seller_id or seller.seller_id, status=our_status)


# --- Operator 표면 (#50 AC) ------------------------------------------------------


def _blocked_on(payout: Payout) -> str | None:
    if payout.status == Payout.Status.CONFIRMED_SELLER_PENDING:
        return "seller"
    if payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING:
        return "identity"
    return None


@operator_router.get("/payouts", response=list[OperatorPayoutOut])
def list_payouts_for_operator(request: HttpRequest, blocked_on: str | None = None):
    """Operator가 어느 Payout이 두 대기 중 어느 쪽에 막혀 있는지 본다(#50 AC).

    `blocked_on=identity`나 `blocked_on=seller`로 필터링할 수 있다 — 운영자가
    "지금 내가 처리해야 할 것은 어느 쪽인가"에 바로 답할 수 있어야 한다는 요구가
    여기 있다. 값을 주지 않으면 전체를 최신순으로 본다.
    """

    payouts = (
        Payout.objects.select_related(
            "handover__award__contest",
            "handover__award__submission__developer",
            "distribution_share__distribution__contest",
            "distribution_share__submission__developer",
        )
        .order_by("-created_at")
    )

    results: list[OperatorPayoutOut] = []
    for payout in payouts:
        blocked = _blocked_on(payout)
        if blocked_on is not None and blocked != blocked_on:
            continue

        seller = Seller.objects.filter(developer_id=_payout_developer_id(payout)).first()
        results.append(
            OperatorPayoutOut(
                idempotency_key=payout.idempotency_key,
                contest_id=_payout_contest_id(payout),
                developer_user_id=_payout_owner_user_id(payout),
                net_amount=payout.net_amount,
                status=payout.status,
                blocked_on=blocked,
                seller_status=seller.status if seller is not None else None,
                has_identity=TaxIdentity.objects.filter(payout=payout).exists(),
                created_at=payout.created_at,
            )
        )

    return results
