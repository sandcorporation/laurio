"""결제 · Escrow 예치 API (#9).

- `POST /payments` — Sponsor가 자신의 draft Contest에 대해 결제를 시작한다.
- `POST /payments/{order_id}/confirm` — Sponsor 쪽 동기 승인 확인(카드 위젯 완료 후
  클라이언트가 호출하는 것에 대응). 토스라면 이 자리에서 결제 승인 API를 동기
  호출한다.
- `POST /payments/webhook` — PG(Fake PG 포함)가 비동기로 결과를 통지하는 내부
  엔드포인트. 서명이 없거나 틀리면 거부한다(`payments.webhook_security`) — 인증이
  없는 엔드포인트라고 해서 검증까지 없는 건 아니다.

두 확정 경로(confirm/webhook) 모두 `payments.services.mark_paid`/`mark_failed`라는
같은 조건부 UPDATE 관문을 통과한다 — 어느 쪽이 먼저 도착하든, 몇 번 재전송되든
원장에는 정확히 한 번만 분개가 남는다.
"""

from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from contests.models import Contest
from core.auth import InternalAuth

from .adapters import PGError, PGTimeoutError, get_adapter
from .models import Payment, WebhookDelivery
from .schemas import (
    ConfirmPaymentIn,
    ErrorOut,
    InitiatePaymentIn,
    PaymentOut,
    RunRefundsIn,
    WebhookIn,
    WebhookOut,
)
from .services import (
    mark_failed,
    mark_paid,
    mark_refund_failed,
    mark_refunded,
    request_refund,
    run_pending_refunds,
)
from .webhook_security import verify_webhook_signature

router = Router(tags=["payments"])

# 참여자 0명 전액 환불(#17) 전용 내부 스캔 엔드포인트. core의 내부 틱 엔드포인트,
# scoring.api의 `/internal/scoring/run-pending`과 같은 `InternalAuth` +
# "CLOSED Contest를 주기적으로 스캔한다" 구조를 그대로 따른다 — 사람이 아니라 운영
# 인프라(Celery beat)가 호출한다.
internal_router = Router(tags=["internal", "payments"], auth=InternalAuth())

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
    유니크 제약을 두 번째 방어선으로 둔다. 잠금을 잡지 못한 예외 경로가
    생기더라도 DB 제약이 최후에 막아준다.
    """

    from django.conf import settings

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

        if contest.status != Contest.Status.DRAFT:
            # PUBLISHED(이미 결제·공개됨)뿐 아니라 CLOSED(마감 전이까지 지난 뒤)도
            # 새 결제를 시작할 이유가 없다 — 원래는 PUBLISHED만 봤는데, #11이
            # CLOSED 상태를 추가하면서 이 가드가 새 상태를 놓치고 있었다(#12 리뷰
            # 지적). 결제를 다시 시작할 수 있는 상태는 DRAFT뿐이다.
            raise HttpError(409, "이미 결제가 완료되어 공개된 Contest입니다.")

        # 이미 진행 중이거나 완료된 결제가 있으면 새로 만들지 않고 그대로
        # 돌려준다 — 중복 클릭·재요청이 새 주문을 계속 만들어내지 않게 하는
        # 멱등성이다. Contest 행을 위에서 잠갔으므로 이 조회는 동시 요청과
        # 경합하지 않는다.
        existing = (
            Payment.objects.filter(contest=contest, status__in=_ACTIVE_PAYMENT_STATUSES)
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            adapter = get_adapter()
            result = adapter.request_payment(
                order_id=str(existing.order_id), amount=existing.total_amount
            )
            return 201, _serialize(existing, checkout_url=result.checkout_url)

        listing_fee_amount = settings.CONTEST_LISTING_FEE
        try:
            # 중첩 atomic(세이브포인트)으로 감싼다 — IntegrityError가 나면
            # Postgres는 바깥 트랜잭션 전체를 "aborted" 상태로 만들어 그 뒤의
            # 어떤 쿼리도 커밋 전까지 막아버린다. 세이브포인트가 없으면 아래
            # except 절의 조회(`Payment.objects.filter(...).latest(...)`)조차
            # `TransactionManagementError`로 실패한다 — 그러면 방어적 안전망이
            # 오히려 500을 새로 만드는 꼴이 된다.
            with transaction.atomic():
                payment = Payment.objects.create(
                    contest=contest,
                    prize_amount=contest.prize,
                    listing_fee_amount=listing_fee_amount,
                    status=Payment.Status.REQUESTED,
                )
        except IntegrityError:
            # Contest 잠금에도 불구하고 unique_active_payment_per_contest에
            # 걸렸다 — 방어적 안전망이다(정상 경로에서는 위 select_for_update가
            # 이미 직렬화했으므로 도달하지 않아야 한다). 이미 있는 활성 결제를
            # 그대로 돌려준다.
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
        # 규율을 결제 확인에도 동일하게 적용). query_status는 order_id만 받는
        # 순수 조회다 — `simulate`는 confirm과 같은 어댑터 인스턴스가 이미 기억하고
        # 있다(PGAdapter 계약, #9 리뷰 지적 4).
        result_status = adapter.query_status(order_id=str(order_id))
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

    if payload.status == "paid":
        payment = mark_paid(payload.order_id)
    elif payload.status == "failed":
        payment = mark_failed(payload.order_id)
    elif payload.status == "refunded":
        # #17 — 환불 스캔(run_pending_refunds)이 동기적으로 이미 확정했을 수도
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


@internal_router.post("/run-refunds")
def run_refunds(request: HttpRequest, payload: RunRefundsIn = RunRefundsIn()):
    """CLOSED Contest 중 Submission이 0건인 채 결제가 완료된 것을 스캔해 전액 환불한다.

    core의 마감 전이(#11)가 Contest를 PUBLISHED -> CLOSED로 옮긴 뒤, 같은 스케줄러
    체계(ADR-0003) 안에서 Celery beat가 이 엔드포인트를 짧은 주기로 반복 호출한다 —
    scoring.api의 `/internal/scoring/run-pending`, notifications.api의
    `/internal/notifications/dispatch-due`와 같은 구조다. 같은 시각에 두 번 쏴도
    (`payments.services.request_refund`의 조건부 UPDATE 덕분에) 각 Payment는
    정확히 한 번만 환불된다.

    `simulate`는 이 스캔이 집는 모든 후보에게 그대로 전달되는 fake PG 전용
    시나리오 선택 값이다(`ConfirmPaymentIn.simulate`와 같은 원칙 — 실제 어댑터는
    무시한다).
    """

    results = run_pending_refunds(simulate=payload.simulate)
    return {"count": len(results), "results": results}
