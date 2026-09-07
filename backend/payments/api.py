"""결제 · Escrow 예치 API (#9).

- `POST /payments` — Sponsor가 자신의 draft Contest에 대해 결제를 시작한다.
- `POST /payments/{order_id}/confirm` — Sponsor 쪽 동기 승인 확인(카드 위젯 완료 후
  클라이언트가 호출하는 것에 대응). 토스라면 이 자리에서 결제 승인 API를 동기
  호출한다.
- `POST /payments/webhook` — PG(Fake PG 포함)가 비동기로 결과를 통지하는 내부
  엔드포인트. 서명이 없거나 틀리면 거부한다(`payments.webhook_security`) — 인증이
  없는 엔드포인트라고 해서 검증까지 없는 건 아니다.

두 확정 경로(confirm/webhook) 모두 `payments.charges.apply_vendor_outcome`이라는
같은 조건부 UPDATE 관문을 통과한다 — 어느 쪽이 먼저 도착하든, 몇 번 재전송되든
원장에는 정확히 한 번만 분개가 남는다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from contests.models import Contest
from verification.models import Verification

from .adapters import PGError, checkout_flow_for_current_mode, get_adapter
from .charges import Outcome, apply_vendor_outcome, settle_charge
from .models import Payment, WebhookDelivery
from .schemas import (
    ConfirmPaymentIn,
    ErrorOut,
    InitiatePaymentIn,
    PaymentOut,
    WebhookIn,
    WebhookOut,
)
from .services import (
    mark_refund_failed,
    mark_refunded,
    request_refund,
)
from .webhook_security import verify_webhook_signature

logger = logging.getLogger(__name__)

router = Router(tags=["payments"])

_ACTIVE_PAYMENT_STATUSES = [Payment.Status.REQUESTED, Payment.Status.PAID]


def _serialize(payment: Payment, checkout_url: str | None = None) -> PaymentOut:
    return PaymentOut(
        order_id=payment.order_id,
        contest_id=payment.contest_id,
        prize_amount=payment.prize_amount,
        listing_fee_amount=payment.listing_fee_amount,
        total_amount=payment.total_amount,
        status=payment.status,
        checkout_url=checkout_url,
        checkout_flow=checkout_flow_for_current_mode(),
        created_at=payment.created_at,
    )


@router.post(
    "/payments",
    response={201: PaymentOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def initiate_payment(request: HttpRequest, payload: InitiatePaymentIn):
    """Sponsor가 자신이 개최한 draft Contest의 Prize + 개최 등록비 결제를 시작한다.

    같은 Contest에 대해 두 요청이 동시에 들어와도 활성 결제가 하나만 남아야
    한다(#9 리뷰 지적 3) — `Contest` 행을 `select_for_update`로 잠가 동시
    요청을 직렬화하고, `Payment.unique_active_payment_per_contest` 부분
    유니크 제약을 두 번째 방어선으로 둔다.

    **PG 등록은 그 잠금 밖에서 한다**(#127) — 벤더가 느리면 그 Contest 의 모든 쓰기가
    같이 멈추고 DB 커넥션을 물고 있게 된다. 행 확보까지만 트랜잭션 안이다.
    """

    from policies.scope import current_policy

    # 심층 방어(#207/#208 코드리뷰) — **잠금 밖, 소유권 확인보다도 먼저** 확인한다.
    # 정상 경로에서는 이미 `contests.api.create_contest`가 본인확인을 요구했으므로
    # 이 엔드포인트에 도달하는 모든 요청자는 이미 VERIFIED다. 이 검사가 실제로 막는
    # 것은 그 정상 경로를 통해 만들어지지 않은 Contest — Assignment(본인확인 없이
    # 만들어진다, ADR-0029)가 어떤 경로로든(오늘은 `_get_owned_draft_contest`가
    # `is_assignment`를 함께 거부해 막혔지만, DRAFT를 공모전과 공유하는 구조상 새
    # 게이트가 또 하나 빠질 수 있다) 이 엔드포인트까지 왔을 경우다.
    #
    # `contest.sponsor`가 아니라 **요청자 본인**(`request.auth_user`)의 Verification
    # 을 본다 — 아래에서 소유권이 확인되면(`contest.sponsor.user_id ==
    # request.auth_user.id`) 둘은 항상 같은 사람이므로 결과가 갈리지 않으면서도,
    # `select_for_update()` 로 행을 잠그기 전에 이 조회를 끝낼 수 있다. Contest 를
    # 아직 읽지 않아도 되는 검사를 잠금 뒤로 미루지 않는다 — "PG 등록은 그 잠금
    # 밖에서 한다"는 이 함수의 기존 규율(#127)과 같은 이유다.
    if not Verification.objects.filter(
        user_id=request.auth_user.id, status=Verification.Status.VERIFIED
    ).exists():
        raise HttpError(403, "본인확인을 완료해야 Contest를 개최할 수 있습니다.")

    with transaction.atomic():
        try:
            contest = (
                Contest.objects.select_for_update()
                .select_related("sponsor")
                .get(id=payload.contest_id)
            )
        except Contest.DoesNotExist as exc:
            raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

        if contest.sponsor.user_id != request.auth_user.id:
            raise HttpError(403, "본인이 개최한 Contest만 결제할 수 있습니다.")

        if not Contest.Status.PAYABLE(contest.status):
            raise HttpError(409, "이미 결제가 완료되어 공개된 Contest입니다.")

        # 이미 진행 중이거나 완료된 결제가 있으면 새로 만들지 않고 그대로 돌려준다 —
        # 중복 클릭·재요청이 새 주문을 계속 만들어내지 않게 하는 멱등성이다.
        payment = (
            Payment.objects.filter(contest=contest, status__in=_ACTIVE_PAYMENT_STATUSES)
            .order_by("-created_at")
            .first()
        )
        if payment is not None:
            # 방어선 두 번째 층 — 첫 번째는 contests.api.update_draft_contest가 상금을
            # 바꾸는 그 순간 REQUESTED Payment를 맞춰준다. **불변식: REQUESTED Payment는
            # 그것이 속한 Contest와 다른 금액을 가질 수 없다** — 그렇지 않으면
            # Escrow(Payment.prize_amount)와 실제 Payout(Contest.prize)이 서로 다른
            # 금액을 가리키게 된다.
            if payment.prize_amount != contest.prize:
                payment.prize_amount = contest.prize
                payment.save(update_fields=["prize_amount"])
        else:
            listing_fee_amount = current_policy().contest_listing_fee
            try:
                # 중첩 atomic(세이브포인트)으로 감싼다 — IntegrityError가 나면 Postgres는
                # 바깥 트랜잭션 전체를 "aborted" 상태로 만들어 그 뒤의 어떤 쿼리도 커밋
                # 전까지 막아버린다.
                with transaction.atomic():
                    payment = Payment.objects.create(
                        contest=contest,
                        prize_amount=contest.prize,
                        listing_fee_amount=listing_fee_amount,
                        status=Payment.Status.REQUESTED,
                    )
            except IntegrityError:
                # Contest 잠금에도 불구하고 unique_active_payment_per_contest에 걸렸다 —
                # 방어적 안전망이다. 이미 있는 활성 결제를 그대로 돌려준다.
                payment = Payment.objects.filter(
                    contest=contest, status__in=_ACTIVE_PAYMENT_STATUSES
                ).latest("created_at")

    adapter = get_adapter()
    result = adapter.request_payment(order_id=str(payment.order_id), amount=payment.total_amount)
    return 201, _serialize(payment, checkout_url=result.checkout_url)


@router.post(
    "/payments/{order_id}/confirm",
    response={200: PaymentOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def confirm_payment(request: HttpRequest, order_id: UUID, payload: ConfirmPaymentIn):
    """동기 승인 확인 — Charge 확정 경로 하나(`payments.charges.settle_charge`).

    PG 호출은 어떤 `transaction.atomic()` 밖에서 일어나고, 타임아웃이면 `query_status` 로
    확정하며, 그 재확인마저 실패하면 미확정으로 남긴다(#87 지적 3, #125). 벤더의 명시적
    거절은 502 다. 이미 다른 경로(웹훅 등)로 확정돼 있으면 벤더를 부르지 않고 현재 상태를
    돌려준다.
    """

    charge_qs = Payment.objects.select_related("contest__sponsor")
    try:
        payment = charge_qs.get(order_id=order_id)
    except Payment.DoesNotExist as exc:
        raise HttpError(404, "결제를 찾을 수 없습니다.") from exc

    if payment.contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest의 결제만 확인할 수 있습니다.")

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

    return 200, _serialize(payment)


@router.post(
    "/payments/webhook",
    response={200: WebhookOut, 401: ErrorOut, 404: ErrorOut},
    auth=None,
)
def receive_webhook(request: HttpRequest, payload: WebhookIn):
    """PG(Fake PG 포함)가 비동기로 보내는 웹훅. 재전송·순서 뒤바뀜에 안전하다.

    인증이 없는 내부 엔드포인트지만 서명은 반드시 검증한다(#9 리뷰 지적 2) —
    그렇지 않으면 누구나 자신의 `order_id`로 "paid"를 위조해 돈이 오가지 않은
    결제를 원장에 예치 분개로 남기고 Contest를 공개시킬 수 있다. 서명 검증은
    DB를 전혀 건드리기 전에 가장 먼저 한다 — 실패하면 Payment 조회도,
    `WebhookDelivery` 기록도, 원장 반영도 전부 일어나지 않는다.
    """

    from django.conf import settings

    if not verify_webhook_signature(
        webhook_id=payload.webhook_id,
        order_id=str(payload.order_id),
        status=payload.status,
        signature=payload.signature,
        secret=settings.PAYMENT_WEBHOOK_SECRET,
    ):
        raise HttpError(401, "웹훅 서명이 없거나 올바르지 않습니다.")

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

    if payload.status in ("paid", "failed"):
        # confirm 응답과 같은 함수로 들어간다 — 웹훅이 confirm 보다 먼저 와도, 같은
        # 웹훅이 두 번 와도 조건부 UPDATE 가 한 번만 이긴다.
        payment = apply_vendor_outcome(
            Payment.objects.select_related("contest"),
            order_id=payload.order_id,
            outcome=Outcome.parse(payload.status),
        )
    elif payload.status == "refunded":
        # #17 — 환불 스캔(payment-refund-request)이 동기적으로 이미 확정했을 수도
        # 있는 결과를 PG가 비동기로 다시 통지한다. mark_refunded는 REFUND_REQUESTED
        # 에서만 전이하므로, 재전송이든 스캔보다 늦게 도착했든 원장에는 정확히
        # 한 번만 반대 분개가 남는다.
        #
        # 하지만 PG 콘솔에서 직접 환불했거나 차지백이 들어온 경우, 이 Payment는
        # 아직 우리 스캔이 request_refund로 선점하지 않아 PAID에 머물러 있을 수
        # 있다 — 그 상태에서 곧장 mark_refunded만 부르면 REFUND_REQUESTED 조건부
        # UPDATE의 rowcount가 0이라 아무 것도 하지 않고 조용히 넘어가, 반대
        # 분개가 전혀 남지 않은 채 예치금만 원장에 계속 잡혀 있게 된다(리뷰 지적).
        # 여기서 먼저 PAID -> REFUND_REQUESTED로 선점한 뒤(이미 REFUND_REQUESTED/
        # REFUNDED/REFUND_FAILED/FAILED면 request_refund가 아무 것도 하지 않고
        # None을 돌려준다) mark_refunded로 확정한다 — PAID 이외의 상태에서는
        # 기존의 멱등 규율을 그대로 따른다.
        request_refund(payload.order_id)
        payment = mark_refunded(payload.order_id)
    elif payload.status == "refund_failed":
        payment = mark_refund_failed(payload.order_id)
    else:
        raise HttpError(
            422, "status는 paid, failed, refunded, refund_failed 중 하나여야 합니다."
        )

    return 200, WebhookOut(received=True, order_id=payload.order_id, status=payment.status)
