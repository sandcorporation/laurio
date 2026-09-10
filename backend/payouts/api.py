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
- `POST /payouts/{idempotency_key}/seller-contact` — 토스 셀러 등록에 필요한
  연락처(전화번호·이메일)를 제출한다(#168). 부분 제출을 허용한다 — 옛 전화번호
  전용 경로(`seller-phone`)를 넓힌 것이라 그 경로는 남기지 않는다.
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

# `from __future__ import annotations` 를 쓰지 않는다. #149 가 `@paginate` 때문에 뺐고,
# #151 이 그 데코레이터를 커서 페이지네이션으로 바꾸면서 그 이유는 사라졌지만 되돌리지
# 않는다 — 되돌릴 이유가 없고, 되돌렸다가 다음에 누가 `@paginate` 를 다시 붙이면 같은
# 함정(`QueryParams is not fully defined` 로 500)을 다시 밟는다.

import json
import logging
from uuid import UUID

from django.db.models import Count
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core.keyset import decode_cursor, keyset_page
from core.operator_auth import OperatorAuth
from distributions.models import DistributionShare
from handovers.models import Handover
from payments.webhook_security import verify_webhook_signature
from policies.scope import current_policy

logger = logging.getLogger(__name__)

from .progress import (
    BLOCKED_ON_VALUES,
    Hold,
    HoldKind,
    advance,
    blocked_on_q,
    blocked_q,
    hold_of,
    next_action_message,
    with_blocked_on,
    with_hold_facts,
    with_seller_registration_status,
)
from .adapters import PayoutError, get_adapter
from .adapters_toss import verify_toss_webhook_signature
from .models import Payout, PayoutWebhookDelivery, Seller, TaxIdentity
from .schemas import (
    ConfirmPayoutIn,
    ErrorOut,
    IdentitySubmitIn,
    OperatorPayoutCountsOut,
    OperatorPayoutOut,
    OperatorPayoutPageOut,
    PayoutOut,
    SellerContactSubmitIn,
    SellerRegistrationRetryIn,
    SellerWebhookOut,
    WebhookIn,
    WebhookOut,
)
from .services import (
    PayoutNotOperatorActionable,
    advance_seller_pending_payouts,
    get_or_create_payout,
    resolve_transfer_webhook,
    retry_payout_for_operator,
    retry_seller_registration,
    submit_identity,
    submit_seller_contact,
)

router = Router(tags=["payouts"])
# Operator 표면 — appeals.api.operator_router와 같은 원칙으로 라우터 전체가
# 기본 거부다(#44).
logger = logging.getLogger(__name__)

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
        has_seller_email=bool(seller is not None and seller.email),
        seller_status=seller.status if seller is not None else None,
        next_action_message=next_action_message(hold),
        created_at=payout.created_at,
    )


def _get_owned_handover(request: HttpRequest, contest_id: int) -> Handover:
    try:
        handover = Handover.objects.select_related(
            "award__contest", "award__submission__developer"
        ).get(award__contest_id=contest_id)
    except Handover.DoesNotExist as exc:
        raise HttpError(404, "이 공모전은 아직 선정되지 않아 인수 정보가 없습니다.") from exc

    if handover.award.submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 선정된 제출물의 참가자만 접근할 수 있습니다.")
    return handover


@router.post(
    "/contests/{contest_id}/payout",
    response={201: PayoutOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def request_payout(request: HttpRequest, contest_id: int):
    handover = _get_owned_handover(request, contest_id)

    if handover.status != Handover.Status.RELEASED:
        raise HttpError(409, "아직 예치금이 해제되지 않아 지급을 요청할 수 없습니다.")

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
            raise HttpError(403, "본인이 선정된 제출물의 참가자만 접근할 수 있습니다.")
    elif not DistributionShare.objects.filter(
        distribution__contest_id=contest_id, submission__developer__user_id=user_id
    ).exists():
        raise HttpError(
            404, "이 공모전은 아직 선정되지 않았고, 배분 대상도 아닙니다."
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
            409, "지급대행사 수취인 등록 대기 또는 실이체 실패 상태에서만 재시도할 수 있습니다."
        )

    payout = retry_seller_registration(payout, simulate=payload.simulate)
    return 200, _serialize(payout)


@router.post(
    "/payouts/{idempotency_key}/seller-contact",
    response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def submit_payout_seller_contact(
    request: HttpRequest, idempotency_key: UUID, payload: SellerContactSubmitIn
):
    """토스 셀러 등록(businessType=INDIVIDUAL)의 individual 객체가 요구하는
    연락처(전화번호·이메일)를 제출한다(#57 추가 인수조건, #168 이 이메일까지 넓힌다).

    옛 전화번호 전용 경로(`seller-phone`)를 이 경로 하나로 합쳤다 — 소비자가
    우리 프론트뿐이라 옛 경로를 남기지 않는다(#153 과 같은 규율). **부분 제출을
    허용한다** — 전화번호만, 이메일만 내도 낸 것은 보존된다(둘 다 생략하면
    422 다).

    `submit_payout_identity`와 달리 Payout 상태를 확인하지 않는다 — Seller는
    Developer 단위 개념이라 연락처도 마찬가지다(Payout이 아직 REQUESTED여도
    미리 받아 둘 수 있다). 저장 직후 CONFIRMED_SELLER_PENDING에 머물던 같은
    Developer의 Payout이 있으면 곧바로 재시도한다(`submit_seller_contact`).
    """

    if payload.phone_number is None and payload.email is None:
        raise HttpError(422, "전화번호나 이메일 중 하나는 제출해야 합니다.")

    payout = _get_owned_payout(request, idempotency_key)
    submit_seller_contact(
        payout.developer, phone_number=payload.phone_number, email=payload.email
    )

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
    # 404 는 더 이상 나지 않는다(#170) — 모르는 참조는 200 이다.
    response={200: WebhookOut, 400: ErrorOut, 401: ErrorOut, 422: ErrorOut},
    auth=None,
)
def receive_toss_payout_webhook(request: HttpRequest):
    """실제 토스가 보내는 `payout.changed` 웹훅. 서명은 DB를 건드리기 전에
    가장 먼저 검증한다(#9 리뷰 지적 2와 같은 순서).

    **봉투는 `entityBody` 다**(#173, 벤더 문서 확인 + #97 실측 — 403 응답
    본문이 `{"version",…,"entityBody":null,"entityType":null,"error":{…}}`
    모양 그대로였다). 이전에는 `body["data"]`를 읽었는데, 그건 문서가 규정한
    적 없는 최선의 추정이었고 실제로는 존재하지 않는 키였다 — 실물 웹훅은
    서명은 통과하고 이 자리에서 전부 422 로 죽었다. `refPayoutId`(우리
    idempotency_key)를 찾지 못하면 벤더가 만든 자기 식별자(`entityBody.id`)로
    조회한다.

    **`entityBody.id` 는 우리 참조가 아니다**(#91) — 이전에는 그것을 `refPayoutId` 인 양
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

    entity_body = body.get("entityBody")
    if not isinstance(entity_body, dict):
        # entityBody 자체가 없다 — 「우리 추정이 또 틀렸다」는 신호다(#173). #170
        # 이 200으로 덮은 것은 「서명은 맞는데 모르는 참조」이지 「본문을 못
        # 읽는다」가 아니다 — 여기서도 422를 유지한다.
        raise HttpError(422, "웹훅 본문에서 entityBody를 찾을 수 없습니다.")

    ref_payout_id = entity_body.get("refPayoutId") or ""
    vendor_payout_id = entity_body.get("id") or ""
    vendor_status = entity_body.get("status")
    webhook_id = request.headers.get("tosspayments-webhook-transmission-id", "")

    if not ref_payout_id and not vendor_payout_id:
        raise HttpError(422, "웹훅 본문에서 지급 식별자를 찾을 수 없습니다.")

    from .adapters_toss import parse_vendor_ref

    # **읽을 수 없는 참조는 없는 참조와 같이 다룬다**(#91, 코드리뷰) — 폴백을
    # 「refPayoutId 가 아예 없을 때」로만 열어 두면, 벤더가 접미어 없는 옛 참조를
    # 돌려주거나 값이 잘려 오는 순간 그 웹훅은 재전송을 몇 번 받든 영구히 422 다.
    # 폴백이 막으려던 것이 정확히 그 상황이다.
    parsed = parse_vendor_ref(str(ref_payout_id)) if ref_payout_id else None

    if parsed is not None:
        idempotency_key = UUID(parsed[0])
        webhook_attempt = parsed[1]
        try:
            known_payout = Payout.objects.get(idempotency_key=idempotency_key)
        except Payout.DoesNotExist:
            # 우리 것이 아니다 — 「전달 실패」가 아니라 「내 것이 아니다」이므로
            # 200 으로 끝낸다(#170). 같은 토스 상점의 웹훅을 두 환경이 나눠 받으면
            # (실측: dev·staging 이 같은 보안 키로 서명한 요청을 둘 다 통과시킨다)
            # 모든 이벤트가 양쪽에 다 가고 그 Payout 은 한쪽에만 있다. 없는 쪽이
            # 404 를 내면 벤더는 재전송하는데, 재전송해도 그 키는 영원히 없다.
            #
            # **대가를 알고 한다**: 「우리 것인데 못 찾는다」는 진짜 결함도 함께
            # 조용해진다 — 그래서 로그로만 남는다.
            logger.warning(
                "모르는 idempotency_key 의 payout.changed 웹훅을 200 으로 흘려보낸다"
                "(idempotency_key=%s, vendor_payout_id=%r) — 다른 환경의 이벤트이거나,"
                " 우리 것인데 찾지 못한 것이다.",
                idempotency_key,
                vendor_payout_id,
            )
            return 200, WebhookOut(received=True, idempotency_key=idempotency_key, status="unknown")
    elif vendor_payout_id:
        known_payout = Payout.objects.filter(vendor_payout_id=str(vendor_payout_id)).first()
        if known_payout is None:
            # 위와 같은 이유로 200 이다(#170). 폴백이 열렸다고 아무 식별자나
            # 통과시키지 않는다는 #91 의 요구는 상태 코드가 아니라 「아무 Payout 도
            # 건드리지 않는다」이고, 그것은 여기서 그대로 지켜진다.
            logger.warning(
                "모르는 지급 식별자의 payout.changed 웹훅을 200 으로 흘려보낸다"
                "(vendor_payout_id=%r, refPayoutId=%r).",
                vendor_payout_id,
                ref_payout_id,
            )
            return 200, WebhookOut(received=True, idempotency_key=None, status="unknown")
        idempotency_key = known_payout.idempotency_key
        # 벤더 식별자는 언제나 **현재** attempt 의 것이다 — 새 시도를 선점할 때마다
        # `vendor_payout_id` 를 반드시 비우기 때문이다(`adapters_toss` 상단 주석).
        # 그러니 아래 attempt 대조는 이 경로에서 항상 통과해야 맞다.
        webhook_attempt = known_payout.transfer_attempt
    else:
        raise HttpError(
            422, "웹훅의 지급 식별자가 유효한 형식(idempotency_key-attempt)이 아닙니다."
        )

    from .adapters_toss import (
        _PENDING_PAYOUT_STATUSES,
        _FAILED_PAYOUT_STATUSES,
        _PAID_PAYOUT_STATUSES,
    )

    # 어댑터(_request_real_payout/query_status)와 **같은 표**를 본다(#174) — 예전에는
    # 어댑터가 CANCELED·DELETED·REJECTED에 예외를 던지는데 이 웹훅은 같은 문자열을
    # "진행 중"으로 조용히 읽어, 같은 벤더 사실을 두 경로가 다르게 다뤘다.
    if vendor_status in _PAID_PAYOUT_STATUSES:
        our_status = "paid"
    elif vendor_status in _FAILED_PAYOUT_STATUSES:
        our_status = "failed"
    else:
        if vendor_status not in _PENDING_PAYOUT_STATUSES:
            # 문서의 일곱 값 중 어디에도 없다 — 벤더가 새 값을 보내는 날이다(#174 AC).
            # 이 Payout 하나의 문제로 스캔 전체를 죽이지 않되(그래서 예외를 던지지
            # 않는다), 조용히 "진행 중"으로 삼키지도 않는다 — 크게 남긴다.
            logger.error(
                "토스 payout.changed 웹훅에 알 수 없는 status가 왔다(idempotency_key=%s): %r",
                ref_payout_id or vendor_payout_id,
                vendor_status,
            )
        # 아직 REQUESTED/IN_PROGRESS(또는 알 수 없는 값)다 — 확정할 수 없으니
        # 기록만 하고 상태는 건드리지 않는다.
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
    # 404 는 더 이상 나지 않는다(#170) — 모르는 Seller 는 200 이다.
    response={200: SellerWebhookOut, 400: ErrorOut, 401: ErrorOut, 422: ErrorOut},
    auth=None,
)
def receive_toss_seller_webhook(request: HttpRequest):
    """실제 토스가 보내는 `seller.changed` 웹훅 — Seller가 등록 이후 비동기로
    (본인인증·KYC 심사 결과) 상태를 바꿀 때 온다. `register()`를 우리가 다시
    부르지 않아도 이 경로로 Seller.status가 갱신되고, 그 즉시 이 Developer의
    CONFIRMED_SELLER_PENDING Payout들을 다음 단계로 밀어준다
    (`advance_seller_pending_payouts`).

    **봉투는 `entityBody` 다**(#173) — `payout.changed`와 같은 결함, 같은 수정.
    """

    if not _toss_webhook_signature_ok(request):
        raise HttpError(401, "웹훅 서명이 없거나 올바르지 않습니다.")

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HttpError(400, "웹훅 본문이 JSON이 아닙니다.") from exc

    entity_body = body.get("entityBody")
    if not isinstance(entity_body, dict):
        raise HttpError(422, "웹훅 본문에서 entityBody를 찾을 수 없습니다.")

    ref_seller_id = entity_body.get("refSellerId") or ""
    # 벤더 문서의 Seller 객체 필드는 `id` 다 — `sellerId` 는 없다(#173, 웹
    # 확인). `refSellerId` 로 찾는(우리가 등록 시 보낸 `laurio-developer-{id}`)
    # 기존 경로는 그대로 두고, 폴백만 고친다.
    seller_id = entity_body.get("id") or ""
    vendor_status = entity_body.get("status")

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
        # 같은 이유로 200 이다(#170) — 다른 환경의 Developer 에 대한 이벤트다.
        logger.warning(
            "모르는 Seller 의 seller.changed 웹훅을 200 으로 흘려보낸다"
            "(refSellerId=%r, sellerId=%r).",
            ref_seller_id,
            seller_id,
        )
        return 200, SellerWebhookOut(received=True, seller_id=seller_id, status="unknown")

    # 벤더 문서의 Seller 객체에는 weeklyLimit 필드가 없다(#173, 웹 확인) —
    # 벤더가 한도를 알려주지 않으므로 정책의 기본 한도(ADR-0020, 토스가 정한
    # 사실)를 쓴다. `payouts.adapters_toss.TossSellerAdapter`가 같은 이유로
    # `weekly_limit_hint`를 쓰는 것과 같은 판단이다 — 이 자리는 HTTP 요청
    # 스코프 안이라 `current_policy()`를 직접 읽는다(#145).
    new_weekly_limit = (
        current_policy().seller_weekly_limit_amount if our_status == "partially_approved" else None
    )

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
    #
    # (#174) `_SELLER_STATUS_MAP`은 이제 어떤 벤더 문자열도 "rejected"로
    # 옮기지 않는다 — 문서가 확인해 주는 벤더 거절 경로는 등록 응답의 4xx뿐이다
    # (`TossSellerAdapter._parse_seller_response`가 그 자리에서 직접
    # `status="rejected"`를 만든다). 그래서 `our_status`가 이 웹훅에서
    # `Seller.Status.REJECTED`가 되는 경우는 지금은 없다 — 이 분기는 그 근거가
    # 다시 나오거나 문서가 벤더의 비동기 거절 통지를 확인해 줄 때를 대비한
    # 방어선으로 남긴다.
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


@operator_router.get("/payouts/counts", response=OperatorPayoutCountsOut)
def count_payouts_for_operator(request: HttpRequest):
    """운영자 홈의 배지 숫자 셋 (#149) — 한 요청, 한 질의, 직렬화되는 행 0개.

    이전에는 홈이 `?blocked_on=` 목록 셋을 통째로 받아 `.length` 를 셌다. 홈을 한 번
    여는 데 Payout 전체를 세 번 긁어 전부 직렬화하고, 숫자 셋만 남기고 버렸다.
    """

    payouts = with_hold_facts(Payout.objects.all())
    return payouts.aggregate(
        # 갈래 목록은 `BLOCKED_ON_OF` 표에서 나온다 — 손으로 적어 두면 갈래가 늘 때
        # 홈만 조용히 옛 셋을 센다. 스키마 필드와의 대조는 모듈 로드 시점에 한다.
        **{
            value: Count("pk", filter=blocked_on_q(value))
            for value in BLOCKED_ON_VALUES
        }
    )


# 한 페이지에 몇 행인가. 오프셋 시절의 `page_size=20` 을 그대로 이어받는다.
_QUEUE_PAGE_SIZE = 20


@operator_router.get("/payouts", response={200: OperatorPayoutPageOut, 422: ErrorOut})
def list_payouts_for_operator(
    request: HttpRequest, blocked_on: str | None = None, after: str | None = None
):
    """Operator가 어느 Payout이 두 대기 중 어느 쪽에 막혀 있는지 본다(#50 AC).

    `blocked_on=identity`나 `blocked_on=seller`로 필터링할 수 있다 — 운영자가
    "지금 내가 처리해야 할 것은 어느 쪽인가"에 바로 답할 수 있어야 한다는 요구가
    여기 있다.

    **좁히기는 전부 SQL 이 한다**(#149). 값을 주지 않으면 **막혀 있는 것 전부**를
    최신순으로 본다 — 확정 전(REQUESTED)이거나 이미 끝난(CONFIRMED·FAILED) Payout 은
    애초에 오지 않는다. 이전에는 이 엔드포인트가 `Payout` 테이블을 통째로 가져와
    파이썬 루프의 `continue` 로 걸렀다: 필터가 좁히는 것이 질의가 아니라 응답뿐이라
    `blocked_on=identity` 를 줘도 DB 에서 오는 행 수는 같았고, `developer_id__in`
    목록이 행 수만큼 자라 개발자가 많아지면 느려지는 게 아니라 바인드 파라미터
    한도에서 **500** 이 났다. 판정 자체는 여전히 `progress.py` 하나가 소유한다 —
    여기 Q 는 그 표에서 파생되고, 둘의 일치는 `tests/test_operator_payout_queue.py`
    가 모든 조합에서 증명한다.

    정렬 마지막 키에 `id` 를 붙인다 — `created_at` 이 같은 두 행의 순서를 DB 가
    보장할 이유가 없고, 페이지마다 순서가 흔들리면 **같은 Payout 이 두 페이지에
    나오고 다른 하나는 어느 페이지에도 안 나온다**(#39 가 공개 목록에서 겪은
    그것). 운영자 큐에서 그 누락은 「처리해야 할 것을 못 본다」다.

    **자르기는 커서다**(#151) — 「몇 번째부터」가 아니라 「마지막으로 본 행 다음부터」를
    묻는다. 오프셋은 목록이 **머리 쪽에서** 자라면 경계가 밀려 2페이지가 1페이지의 행을
    다시 돌려주고 그 사이 행 하나가 어느 페이지에도 안 나오는데, 이 큐는 스캔이 60초마다
    Payout 을 확정하므로 운영자가 「더 보기」를 누르는 그 몇 초 사이에 실제로 일어난다.
    커서가 가리키는 것(`created_at`, `id`)과 위 정렬 키가 같은 것이어야 성립한다.
    """

    if blocked_on is not None and blocked_on not in BLOCKED_ON_VALUES:
        # 알 수 없는 값은 500 도 「0건」도 아니다(`contests.api.list_contests` 와 같은
        # 규율) — 빈 큐는 「처리할 것이 없다」는 뜻이라 오타 하나가 그렇게 읽히면
        # 운영자가 밀린 일을 못 본 채 지나간다.
        raise HttpError(422, f"blocked_on 은 {', '.join(BLOCKED_ON_VALUES)} 중 하나여야 합니다.")

    if after is not None and decode_cursor(after) is None:
        # 같은 이유로 읽을 수 없는 커서도 조용히 처음부터가 아니다 — 그러면 「더 보기」를
        # 눌렀는데 목록이 처음으로 되돌아간 화면이 되고, 운영자는 무엇을 봤고 무엇을
        # 못 봤는지 알 수 없게 된다.
        raise HttpError(422, "읽을 수 없는 커서입니다.")

    payouts = (
        with_seller_registration_status(with_blocked_on(with_hold_facts(Payout.objects.with_target())))
        .filter(blocked_q())
        .order_by("-created_at", "-id")
    )
    if blocked_on is not None:
        payouts = payouts.filter(blocked_on_q(blocked_on))

    items, next_cursor = keyset_page(payouts, after=after, page_size=_QUEUE_PAGE_SIZE)
    # `count` 는 이 페이지의 길이가 아니라 **전체** 건수다 — 화면이 「막혀 있는 지급 N건」을
    # 말하고, 홈 배지와 그 숫자가 맞는지를 e2e 가 단언한다.
    return 200, {"items": items, "count": payouts.count(), "next": next_cursor}


@operator_router.post(
    "/payouts/{idempotency_key}/retry",
    response={200: OperatorPayoutOut, 404: ErrorOut, 409: ErrorOut},
)
def retry_payout_for_operator_view(request: HttpRequest, idempotency_key: UUID):
    """Operator가 큐에서 막힌 Payout을 진행시킨다(#182) — 「이체 재시도 필요」라고
    적어 놓고 그것을 할 방법이 없던 결함을 닫는다.

    **행동은 기존 도메인 경로를 그대로 지난다**(#182 AC) — 운영자 전용 재시도
    로직이 따로 없다. `payouts.services.retry_payout_for_operator`가 Hold 를 계산해
    정확히 세 갈래(수취인 등록 거절·자력 회복 포기(#178)·확정 후 실이체 실패)만
    받고, 각각 Developer 의 「다시 시도」와 같은 함수(`retry_seller_registration`)
    또는 다른 모든 실이체 재시도가 쓰는 것과 같은 함수(`payouts.progress.
    retry_confirmed_transfer`)를 그대로 부른다. 그 밖(`UNKNOWN` 포함)은 409다 —
    `OperatorPayoutOut.operator_actionable` 이 큐 화면에서 이미 그 사실을 미리
    알려준다.

    **권한 등급은 `OperatorAuth`다**(이 라우터 기본값, #182 AC — 근거를 남긴다).
    정책 변경(`SuperuserOperatorAuth`, ADR-0023)은 앞으로의 모든 돈에 영향을
    주는 요율 변경이라 상위 등급을 요구하지만, 이 행동은 이의 심판
    (`appeals.api`, ADR-0022 — 같은 `OperatorAuth`)처럼 **이미 존재하는 개별
    사례**에 대해 이미 정해진 절차(등록 재시도·실이체 재시도)를 실행할 뿐이다 —
    새 정책을 만들지 않는다.

    **누가 눌렀는지 남는다**(`OperatorPayoutAction`) — 돈을 움직이는 운영자
    행위를 정책 변경·이의 심판과 같은 무게로 다룬다(ADR-0022/0023).
    """

    payout = Payout.objects.with_target().filter(idempotency_key=idempotency_key).first()
    if payout is None:
        raise HttpError(404, "지급 요청을 찾을 수 없습니다.")

    try:
        retry_payout_for_operator(payout, operator=request.auth)
    except PayoutNotOperatorActionable as exc:
        raise HttpError(409, str(exc)) from exc

    row = with_seller_registration_status(
        with_blocked_on(with_hold_facts(Payout.objects.with_target()))
    ).get(pk=payout.pk)
    return 200, row
