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

두 확정 경로(confirm/webhook) 모두 `payouts.progress.advance`라는 같은 조건부 UPDATE
관문을 통과한다 — 어느 쪽이 먼저 도착하든, 몇 번 재전송되든 원장에는 정확히 한 번만
분개가 남는다. 첫 홈은
안에서 Seller 등록도 함께 시작한다(ADR-0020).
"""

from __future__ import annotations

import json
from uuid import UUID

from django.db.models import Exists, OuterRef
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core.operator_auth import OperatorAuth
from distributions.models import DistributionShare
from handovers.models import Handover
from payments.webhook_security import verify_webhook_signature

from .progress import Hold, HoldKind, advance, assert_covers_all_kinds, hold_of
from .adapters import PayoutError, get_adapter
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
    resolve_transfer_webhook,
    retry_seller_registration,
    submit_identity,
    submit_seller_phone,
)

router = Router(tags=["payouts"])
# Operator 표면 — appeals.api.operator_router와 같은 원칙으로 라우터 전체가
# 기본 거부다(#44).
operator_router = Router(tags=["operator", "payouts"], auth=OperatorAuth())

# seller.changed 웹훅의 out-of-order/재전송 방어에 쓰는 순위(코드리뷰 지적 9)
# — 숫자가 클수록 더 진행된 상태다. REJECTED는 별도 취급(항상 적용 허용,
# receive_toss_seller_webhook 참고)이라 여기 순위는 실질적으로 쓰이지 않지만
# allowed_source_statuses 계산에서 자기 자신은 항상 포함돼야 하므로 값을
# 채워 둔다.
_SELLER_STATUS_RANK = {
    Seller.Status.PENDING: 0,
    Seller.Status.APPROVAL_REQUIRED: 1,
    Seller.Status.UNDER_REVIEW: 1,
    Seller.Status.PARTIALLY_APPROVED: 2,
    Seller.Status.APPROVED: 3,
    Seller.Status.REJECTED: 0,
}


# 다음 행동 안내(#50 AC — "Developer가 자기 Payout이 무엇을 기다리는지와 다음에
# 무엇을 해야 하는지 볼 수 있다"). 판정은 `payouts.progress.hold_of` 가 하고(#130), 여기는
# Hold → 사람이 읽을 문장의 번역표다 — 침묵은 상금이 사라진 것으로 읽힌다.
_NEXT_ACTION_MESSAGES: dict[HoldKind, str] = {
    HoldKind.REQUESTED: "지급 확인 절차가 진행 중입니다. 잠시만 기다려주세요.",
    HoldKind.IDENTITY: "세무 신고를 위해 주민등록번호를 제출해주세요.",
    HoldKind.IDENTITY_RECORDED: "세무 신고를 위해 주민등록번호를 제출해주세요.",
    HoldKind.SELLER_PHONE: "지급대행사 수취인 등록에 전화번호가 필요합니다 — 아래에서 제출해주세요.",
    HoldKind.SELLER_AUTH: (
        "지급대행사(토스페이먼츠)가 보낸 본인인증 문자로 인증을 완료해주세요 — "
        "이미 본인확인을 하셨더라도 지급대행사 자체 의무라 다시 인증이 "
        "필요합니다. 인증이 끝나면 자동으로 다음 단계로 넘어갑니다."
    ),
    HoldKind.SELLER_REVIEW: (
        "지급대행사 심사가 진행 중입니다(주간 지급 한도 초과 또는 추가 확인 "
        "요청) — 상금은 안전하게 보관되어 있으며 심사가 끝나면 자동으로 다음 "
        "단계로 넘어갑니다."
    ),
    HoldKind.SELLER_REJECTED: (
        "지급대행사 수취인 등록이 거절되었습니다. 상금은 원장에 그대로 "
        "남아 있습니다 — 운영자에게 문의해주세요."
    ),
    HoldKind.SELLER_PENDING: "지급대행사 수취인 등록이 진행 중입니다. 완료되면 자동으로 다음 단계로 넘어갑니다.",
    HoldKind.TRANSFER_CONFIRMING: "실이체 확인이 진행 중입니다. 잠시만 기다려주세요.",
    HoldKind.TRANSFER_RETRY: (
        "지급대행사 등록은 끝났지만 실제 이체가 거절되었습니다 — 상금은 "
        "원장에 그대로 남아 있습니다. 아래에서 다시 시도해주세요."
    ),
    HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED: (
        "실제 이체가 실패로 확인되었습니다 — 상금은 원장에 그대로 남아 "
        "있습니다. 세무 신고를 위한 주민등록번호는 계속 제출해주세요."
    ),
    HoldKind.TRANSFER_OPERATOR: (
        "지급이 확정되었지만 실제 이체가 실패로 확인되었습니다 — 상금은 "
        "원장에 그대로 남아 있습니다. 운영자가 확인 후 다시 진행합니다."
    ),
    HoldKind.COMPLETE: "지급이 완료되었습니다.",
    HoldKind.FAILED: "지급 요청이 실패했습니다. 다시 시도해주세요.",
    HoldKind.UNKNOWN: "지급 상태를 확인하는 중입니다. 운영자가 확인 후 안내드립니다.",
}
assert_covers_all_kinds(_NEXT_ACTION_MESSAGES, name="_NEXT_ACTION_MESSAGES")

# 신원 미제출 상태에서 실이체 실패도 함께 확인된 경우 — 신원 제출을 막을 이유는 없지만
# (독립적인 두 축), 실이체가 실패했다는 사실을 감추지 않는다(#57 코드리뷰 지적 4).
_IDENTITY_AFTER_TRANSFER_FAILURE_MESSAGE = _NEXT_ACTION_MESSAGES[
    HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED
]


def _next_action_message(hold: Hold) -> str:
    if hold.kind is HoldKind.IDENTITY and hold.transfer_failed:
        return _IDENTITY_AFTER_TRANSFER_FAILURE_MESSAGE
    return _NEXT_ACTION_MESSAGES[hold.kind]


def _serialize(payout: Payout) -> PayoutOut:
    seller = payout.seller
    has_identity = TaxIdentity.objects.filter(payout=payout).exists()
    hold = hold_of(payout, seller=seller, has_identity=has_identity)
    return PayoutOut(
        idempotency_key=payout.idempotency_key,
        contest_id=payout.contest.id,
        prize_amount=payout.prize_amount,
        platform_fee_amount=payout.platform_fee_amount,
        withholding_tax_amount=payout.withholding_tax_amount,
        net_amount=payout.net_amount,
        status=payout.status,
        transfer_status=payout.transfer_status,
        has_identity=has_identity,
        has_seller_phone=bool(seller is not None and seller.phone_number),
        seller_status=seller.status if seller is not None else None,
        next_action_message=_next_action_message(hold),
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

    payout = get_or_create_payout(handover.payout_target())

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

    user_id = request.auth_user.id

    # 소유권은 지급 사유 쪽이 말한다 — Award 경로는 Handover 가(남의 것이면 403), Distribution
    # 경로는 그 Developer 의 몫이 있는지가(없으면 404). Payout 자체의 조회는 어느 경로든
    # 하나다(#128).
    handover = (
        Handover.objects.select_related("award__submission__developer")
        .filter(award__contest_id=contest_id)
        .first()
    )
    if handover is not None:
        if handover.award.submission.developer.user_id != user_id:
            raise HttpError(403, "본인이 Award된 Submission의 Developer만 접근할 수 있습니다.")
    elif not DistributionShare.objects.filter(
        distribution__contest_id=contest_id, submission__developer__user_id=user_id
    ).exists():
        raise HttpError(
            404, "이 Contest는 아직 Award되지 않았고, Distribution 대상도 아닙니다."
        )

    payout = Payout.objects.with_target().for_contest(contest_id).owned_by(user_id).first()
    if payout is None:
        raise HttpError(404, "아직 지급 요청이 없습니다.")
    return 200, _serialize(payout)


def _get_owned_payout(request: HttpRequest, idempotency_key: UUID) -> Payout:
    try:
        payout = Payout.objects.with_target().get(idempotency_key=idempotency_key)
    except Payout.DoesNotExist as exc:
        raise HttpError(404, "지급 요청을 찾을 수 없습니다.") from exc

    if payout.developer.user_id != request.auth_user.id:
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

    # 벤더 확인·실이체·Seller 등록·원장 분개 전부 advance 가 한다(#133, #135) — 이 엔드포인트는
    # 소유권과 fake 시나리오만 넘긴다. 벤더의 명시적 거절은 502 다.
    try:
        payout = advance(
            payout,
            register_seller=True,
            adapter=get_adapter(),
            confirm_with_vendor=True,
            simulate=payload.simulate,
            seller_simulate=payload.seller_simulate,
        )
    except PayoutError as exc:
        raise HttpError(502, str(exc)) from exc

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
        payout = advance(known_payout, confirmed_by_vendor=True, register_seller=True)
    elif payload.status == "failed":
        payout = advance(known_payout, confirmed_by_vendor=False, register_seller=False)
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

    # CONFIRMED_SELLER_PENDING(Seller 자체가 아직 READY가 아님)뿐 아니라
    # CONFIRMED_IDENTITY_PENDING이면서 transfer_status가 FAILED인 경우도
    # 받는다(코드리뷰 지적 6/7/8, 3차) — Seller는 이미 READY인데 실이체만
    # 실패한 상태다. 프런트는 seller_status가 아니라 transfer_status만 보고
    # "다시 시도" 버튼을 띄우므로(#57 2차), 여기서 CONFIRMED_SELLER_PENDING만
    # 받으면 그 버튼이 항상 409를 돌려받는다.
    retryable = payout.status == Payout.Status.CONFIRMED_SELLER_PENDING or (
        payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
        and payout.transfer_status == Payout.TransferStatus.FAILED
    )
    if not retryable:
        raise HttpError(
            409, "Seller 등록 대기 또는 실이체 실패 상태에서만 재시도할 수 있습니다."
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
    submit_seller_phone(payout.developer, payload.phone_number)

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
    idempotency_key)를 찾지 못하면 벤더가 만든 자기 식별자(`data.id`)로 조회한다.

    **`data.id` 는 우리 참조가 아니다**(#91) — 이전에는 그것을 `refPayoutId` 인 양
    `parse_vendor_ref` 에 넘겼는데, 벤더 식별자는 UUID 도 아니고 attempt 접미어도
    없으니 파싱이 언제나 실패해 이 폴백은 **있는데 반드시 422 로 끝나는** 경로였다.
    그 값을 저장해 두는 자리가 이미 있으므로(`Payout.vendor_payout_id` —
    `TossPayoutAdapter` 가 POST 응답의 `id` 를 거기 넣는다) 그 열로 조회한다.

    **지급 식별자는 `{idempotency_key}-{transfer_attempt}` 형식이다**(코드리뷰
    지적 1, 5차 — 이전에는 접미어 없는 순수 UUID만 기대해 `UUID(str(...))`가
    무조건 `ValueError`를 던졌다. 실제 벤더가 보내는 웹훅은 우리가 보낸
    `refPayoutId`를 그대로 돌려주므로, 이 형식이 아닌 웹훅은 전부 이 엔드포인트
    에서 422가 났다). `adapters_toss.parse_vendor_ref`로 `(idempotency_key,
    attempt)`를 갈라내고, attempt가 Payout의 **현재** `transfer_attempt`와
    다르면(설계 결정, 5차 코드리뷰) 낡은(또는 알 수 없는) 시도의 지연 배달로
    보고 조용히 버린다 — 진행 중이거나 이미 확정된 attempt를 잘못 덮어쓰지
    않기 위해서다.
    """

    if not _toss_webhook_signature_ok(request):
        raise HttpError(401, "웹훅 서명이 없거나 올바르지 않습니다.")

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError(400, "웹훅 본문이 JSON이 아닙니다.") from exc

    data = body.get("data") or {}
    ref_payout_id = data.get("refPayoutId") or ""
    vendor_payout_id = data.get("id") or ""
    vendor_status = data.get("status")
    webhook_id = request.headers.get("tosspayments-webhook-transmission-id", "")

    if not ref_payout_id and not vendor_payout_id:
        raise HttpError(422, "웹훅 본문에서 지급 식별자를 찾을 수 없습니다.")

    from .adapters_toss import parse_vendor_ref

    if ref_payout_id:
        parsed = parse_vendor_ref(str(ref_payout_id))
        if parsed is None:
            raise HttpError(
                422, "웹훅의 지급 식별자가 유효한 형식(idempotency_key-attempt)이 아닙니다."
            )
        idempotency_key = UUID(parsed[0])
        webhook_attempt = parsed[1]
        try:
            known_payout = Payout.objects.get(idempotency_key=idempotency_key)
        except Payout.DoesNotExist as exc:
            raise HttpError(404, "알 수 없는 idempotency_key 입니다.") from exc
    else:
        known_payout = Payout.objects.filter(vendor_payout_id=str(vendor_payout_id)).first()
        if known_payout is None:
            raise HttpError(404, "알 수 없는 지급 식별자입니다.")
        idempotency_key = known_payout.idempotency_key
        # 벤더 식별자는 언제나 **현재** attempt 의 것이다 — 새 시도를 선점할 때마다
        # `vendor_payout_id` 를 반드시 비우기 때문이다(`adapters_toss` 상단 주석).
        # 그러니 아래 attempt 대조는 이 경로에서 항상 통과해야 맞다.
        webhook_attempt = known_payout.transfer_attempt

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

    if webhook_attempt != known_payout.transfer_attempt:
        # 지금 진행 중인(또는 이미 확정된) attempt에 대한 배달이 아니다
        # (설계 결정, 5차 코드리뷰) — 낡은 attempt의 지연 배달이 새 시도를
        # 잘못 덮어쓰지 않도록 조용히 버린다. 배달 자체는 위에서 이미
        # PayoutWebhookDelivery로 남겼다(감사 추적은 유지한다).
        return 200, WebhookOut(
            received=True, idempotency_key=idempotency_key, status=known_payout.status
        )

    # Payout이 이미 REQUESTED를 지나 두 대기 어딘가로 넘어간 뒤에 이 웹훅이
    # 도착해도 조용히 버려지지 않는다(코드리뷰 지적 4) — resolve_transfer_webhook
    # 이 REQUESTED에서는 기존 advance 조건부 UPDATE를 그대로
    # 타고, 그 이후 도착이면 transfer_status에 결과를 남긴다(FAILED여도
    # Payout.status를 되돌리지 않는다 — 원장 분개는 그대로다).
    payout = resolve_transfer_webhook(idempotency_key, our_status)

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
    new_weekly_limit = weekly_limit_body.get("amount") if our_status == "partially_approved" else None

    if our_status == seller.status:
        # 완전히 같은 상태의 재전송이다(코드리뷰 지적 4, 3차 — "동급 rank가
        # 서로 덮어쓴다"의 핵심은 이 경우다: 새 정보가 전혀 없는 중복 배달도
        # 예전 조건(rank <= incoming_rank)을 통과해 advance_seller_pending_
        # payouts를 다시 불렀다). 값 자체(주간 한도 등)는 최신화해도 안전하지만,
        # 실이체 재시도 표면을 다시 두드릴 이유가 없다.
        Seller.objects.filter(pk=seller.pk).update(
            seller_id=seller_id or seller.seller_id, weekly_limit_amount=new_weekly_limit
        )
        return 200, SellerWebhookOut(
            received=True, seller_id=seller_id or seller.seller_id, status=seller.status
        )

    # 재전송·역순 도착에 안전해야 한다(코드리뷰 지적 9, 2차) — payout.changed
    # 웹훅이 조건부 UPDATE(status=OLD인 행만 WHERE로 걸어 갱신)로 지켜지는
    # 것과 같은 규율이다. 여기서는 "이전보다 진행이 뒤처지는 값으로는
    # 덮어쓰지 않는다"가 그 규율의 구체화다 — 순위 없이 그대로 덮어쓰면 늦게
    # 도착한 오래된 이벤트(예: 먼저 보낸 APPROVAL_REQUIRED가 네트워크 지연으로
    # PARTIALLY_APPROVED보다 늦게 도착)가 APPROVED→APPROVAL_REQUIRED로
    # 되돌리고 이미 없어진 주간 한도를 다시 씌운다.
    #
    # REJECTED는 *incoming*으로는 순위와 무관하게 항상 허용하지만(벤더가
    # 언제든 내릴 수 있는 결정), *source*(현재 이미 REJECTED인 Seller)는
    # 이 웹훅 경로로 되돌리지 않는다(코드리뷰 지적 3, 3차) — REJECTED의
    # 순위를 0으로 두면 rank <= incoming_rank 조건이 "REJECTED에서는 무엇으로든
    # 넘어갈 수 있다"고 잘못 허용해, 거절 *이전*에 발송됐다가 뒤늦게 도착한
    # 오래된 이벤트(예: APPROVAL_REQUIRED)가 거절을 지우고 곧바로
    # advance_seller_pending_payouts를 거쳐 실이체를 재발사할 길을 연다.
    # 거절 이후의 진짜 새 진행은 재등록(ensure_seller_registered->register())의
    # 동기 응답이 Seller.status를 직접 갱신하는 경로로만 일어난다 — 이
    # 비동기 웹훅만으로는 "오래된 이벤트"와 "거절 이후의 새 진행"을 구별할
    # 수 없으므로 항상 보수적으로 거절을 유지한다.
    incoming_rank = _SELLER_STATUS_RANK.get(our_status, 0)
    allowed_source_statuses = [
        status
        for status, rank in _SELLER_STATUS_RANK.items()
        if status != Seller.Status.REJECTED
        and (our_status == Seller.Status.REJECTED or rank <= incoming_rank)
    ]

    updated = Seller.objects.filter(pk=seller.pk, status__in=allowed_source_statuses).update(
        seller_id=seller_id or seller.seller_id,
        status=our_status,
        weekly_limit_amount=new_weekly_limit,
    )

    if updated:
        advance_seller_pending_payouts(seller.developer)
        seller.refresh_from_db()

    return 200, SellerWebhookOut(received=True, seller_id=seller_id or seller.seller_id, status=seller.status)


# --- Operator 표면 (#50 AC) ------------------------------------------------------


@operator_router.get("/payouts", response=list[OperatorPayoutOut])
def list_payouts_for_operator(request: HttpRequest, blocked_on: str | None = None):
    """Operator가 어느 Payout이 두 대기 중 어느 쪽에 막혀 있는지 본다(#50 AC).

    `blocked_on=identity`나 `blocked_on=seller`로 필터링할 수 있다 — 운영자가
    "지금 내가 처리해야 할 것은 어느 쪽인가"에 바로 답할 수 있어야 한다는 요구가
    여기 있다. 값을 주지 않으면 전체를 최신순으로 본다.

    **행마다 조회하지 않는다**(#91) — `hold_of` 는 "조회를 내지 않는다, 호출부가
    Seller 와 신원 제출 여부를 미리 가져온다"고 못 박아 두었는데(`progress.py`) 이
    큐만 그 규율을 어겨 행마다 Seller 1회 + TaxIdentity 1회를 쳤고, 그것도
    `blocked_on` 으로 걸러내기 **전에** 쳤다. 운영자 홈이 세 큐를 병렬로 부르므로
    그대로 3배가 된다. 신원은 `contests.sponsorship` 과 같은 `Exists` 관용구로 붙이고,
    Seller 는 FK 가 아니라 Developer 단위 개념이라(`Payout.seller` 는 속성이다)
    한 질의로 모아 사상한다.
    """

    payouts = list(
        Payout.objects.with_target()
        .annotate(identity_submitted=Exists(TaxIdentity.objects.filter(payout=OuterRef("pk"))))
        .order_by("-created_at")
    )
    sellers_by_developer = {
        seller.developer_id: seller
        for seller in Seller.objects.filter(
            developer_id__in={payout.developer.id for payout in payouts}
        )
    }

    results: list[OperatorPayoutOut] = []
    for payout in payouts:
        seller = sellers_by_developer.get(payout.developer.id)
        has_identity = payout.identity_submitted
        blocked = hold_of(payout, seller=seller, has_identity=has_identity).blocked_on
        if blocked_on is not None and blocked != blocked_on:
            continue

        results.append(
            OperatorPayoutOut(
                idempotency_key=payout.idempotency_key,
                contest_id=payout.contest.id,
                developer_user_id=payout.developer.user_id,
                net_amount=payout.net_amount,
                status=payout.status,
                transfer_status=payout.transfer_status,
                blocked_on=blocked,
                seller_status=seller.status if seller is not None else None,
                has_identity=has_identity,
                created_at=payout.created_at,
            )
        )

    return results
