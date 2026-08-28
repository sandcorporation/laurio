"""결제 · Escrow 예치 API (#9).

- `POST /payments` — Sponsor가 자신의 draft Contest에 대해 결제를 시작한다.
- `POST /payments/{order_id}/confirm` — Sponsor 쪽 동기 승인 확인(카드 위젯 완료 후
  클라이언트가 호출하는 것에 대응). 토스라면 이 자리에서 결제 승인 API를 동기
  호출한다.
- `POST /payments/webhook` — PG(Fake PG 포함)가 비동기로 결과를 통지하는 내부
  엔드포인트. 실제 토스 연동 시 서명 검증이 필요하지만 이 티켓 범위 밖이다(#23).

두 확정 경로(confirm/webhook) 모두 `payments.services.mark_paid`/`mark_failed`라는
같은 조건부 UPDATE 관문을 통과한다 — 어느 쪽이 먼저 도착하든, 몇 번 재전송되든
원장에는 정확히 한 번만 분개가 남는다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from contests.models import Contest

from .adapters import PGError, PGTimeoutError, get_adapter
from .models import Payment, WebhookDelivery
from .schemas import ConfirmPaymentIn, ErrorOut, InitiatePaymentIn, PaymentOut, WebhookIn, WebhookOut
from .services import mark_failed, mark_paid

router = Router(tags=["payments"])


def _serialize(payment: Payment, checkout_url: str | None = None) -> PaymentOut:
    return PaymentOut(
        order_id=payment.order_id,
        contest_id=payment.contest_id,
        prize_amount=payment.prize_amount,
        listing_fee_amount=payment.listing_fee_amount,
        total_amount=payment.total_amount,
        status=payment.status,
        checkout_url=checkout_url,
        created_at=payment.created_at,
    )


@router.post(
    "/payments",
    response={201: PaymentOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def initiate_payment(request: HttpRequest, payload: InitiatePaymentIn):
    """Sponsor가 자신이 개최한 draft Contest의 Prize + 개최 등록비 결제를 시작한다."""

    from django.conf import settings

    try:
        contest = Contest.objects.select_related("sponsor").get(id=payload.contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest만 결제할 수 있습니다.")

    if contest.status == Contest.Status.PUBLISHED:
        raise HttpError(409, "이미 결제가 완료되어 공개된 Contest입니다.")

    # 이미 진행 중이거나 완료된 결제가 있으면 새로 만들지 않고 그대로 돌려준다 —
    # 중복 클릭·재요청이 새 주문을 계속 만들어내지 않게 하는 초보적 멱등성이다.
    existing = (
        Payment.objects.filter(contest=contest, status__in=[Payment.Status.REQUESTED, Payment.Status.PAID])
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        adapter = get_adapter()
        result = adapter.request_payment(order_id=str(existing.order_id), amount=existing.total_amount)
        return 201, _serialize(existing, checkout_url=result.checkout_url)

    listing_fee_amount = settings.CONTEST_LISTING_FEE
    payment = Payment.objects.create(
        contest=contest,
        prize_amount=contest.prize,
        listing_fee_amount=listing_fee_amount,
        status=Payment.Status.REQUESTED,
    )

    adapter = get_adapter()
    result = adapter.request_payment(order_id=str(payment.order_id), amount=payment.total_amount)

    return 201, _serialize(payment, checkout_url=result.checkout_url)


@router.post(
    "/payments/{order_id}/confirm",
    response={200: PaymentOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def confirm_payment(request: HttpRequest, order_id: str, payload: ConfirmPaymentIn):
    """동기 승인 확인. 타임아웃이 나도 곧바로 실패로 처리하지 않고 조회로 확정한다."""

    try:
        payment = Payment.objects.select_related("contest__sponsor").get(order_id=order_id)
    except Payment.DoesNotExist as exc:
        raise HttpError(404, "결제를 찾을 수 없습니다.") from exc

    if payment.contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest의 결제만 확인할 수 있습니다.")

    if payment.status != Payment.Status.REQUESTED:
        # 이미 다른 경로(웹훅 등)로 확정되어 있다 — 그대로 현재 상태를 돌려준다.
        return 200, _serialize(payment)

    adapter = get_adapter()
    try:
        result_status = adapter.confirm(order_id=str(order_id), simulate=payload.simulate)
    except PGTimeoutError:
        # 타임아웃은 실패가 아니다 — 실제 결과를 조회로 확정한다(ADR-0008의 지급 웹훅
        # 규율을 결제 확인에도 동일하게 적용).
        result_status = adapter.query_status(order_id=str(order_id), simulate=payload.simulate)
    except PGError as exc:
        raise HttpError(502, str(exc)) from exc

    if result_status == "paid":
        payment = mark_paid(order_id)
    elif result_status == "failed":
        payment = mark_failed(order_id)
    else:
        # 아직 확정할 수 없다(pending) — 함부로 실패 처리하지 않고 현재 상태를
        # 그대로 돌려준다. 이후 웹훅이나 재조회가 마저 확정한다.
        payment.refresh_from_db()

    return 200, _serialize(payment)


@router.post("/payments/webhook", response={200: WebhookOut, 404: ErrorOut}, auth=None)
def receive_webhook(request: HttpRequest, payload: WebhookIn):
    """PG(Fake PG 포함)가 비동기로 보내는 웹훅. 재전송·순서 뒤바뀜에 안전하다.

    인증이 없는 내부 엔드포인트다 — 실제 토스 연동 시 서명 검증이 필요하지만 이
    티켓 범위 밖이다(#23이 다룬다).
    """

    try:
        known_payment = Payment.objects.get(order_id=payload.order_id)
    except Payment.DoesNotExist as exc:
        raise HttpError(404, "알 수 없는 order_id 입니다.") from exc

    WebhookDelivery.objects.create(
        payment_id=known_payment.id,
        webhook_id=payload.webhook_id,
        order_id=payload.order_id,
        event_status=payload.status,
    )

    if payload.status == "paid":
        payment = mark_paid(payload.order_id)
    elif payload.status == "failed":
        payment = mark_failed(payload.order_id)
    else:
        raise HttpError(422, "status는 paid 또는 failed 여야 합니다.")

    return 200, WebhookOut(received=True, order_id=payload.order_id, status=payment.status)
