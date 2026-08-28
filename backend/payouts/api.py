"""Payout 실행 API (#15, ADR-0004, ADR-0007, ADR-0008).

- `POST /contests/{contest_id}/payout` — Developer가 자신의 Award된 Contest에
  대해 지급을 요청한다. Escrow가 아직 해제되지 않았으면(Handover가 released가
  아니면) 409다. 멱등하다 — 이미 요청되어 있으면 새 idempotency_key를 만들지
  않고 그대로 어댑터에 재요청한다(payments.api.initiate_payment와 같은 관용구).
- `GET /contests/{contest_id}/payout` — Developer 본인이 총액·수수료·원천징수·
  실지급액 내역을 조회한다.
- `POST /payouts/{idempotency_key}/confirm` — 동기 확인. 타임아웃이 나도 곧바로
  실패로 처리하지 않고 조회로 확정한다.
- `POST /payouts/webhook` — 토스(Fake 포함)가 비동기로 통지하는
  `payout.changed` 웹훅. 서명이 없거나 틀리면 거부한다.
- `POST /payouts/{idempotency_key}/identity` — 지급이 확정된(CONFIRMED_IDENTITY_
  PENDING 이상) 뒤에만 Developer가 주민등록번호를 제출해 최종 확정한다.

두 확정 경로(confirm/webhook) 모두 `payouts.services.mark_confirmed`/
`mark_failed`라는 같은 조건부 UPDATE 관문을 통과한다 — 어느 쪽이 먼저 도착하든,
몇 번 재전송되든 원장에는 정확히 한 번만 분개가 남는다.
"""

from __future__ import annotations

from uuid import UUID

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from handovers.models import Handover
from payments.webhook_security import verify_webhook_signature

from .adapters import PayoutError, PayoutTimeoutError, get_adapter
from .models import Payout, PayoutWebhookDelivery, TaxIdentity
from .schemas import ConfirmPayoutIn, ErrorOut, IdentitySubmitIn, PayoutOut, WebhookIn, WebhookOut
from .services import get_or_create_payout, mark_confirmed, mark_failed, submit_identity

router = Router(tags=["payouts"])


def _serialize(payout: Payout) -> PayoutOut:
    return PayoutOut(
        idempotency_key=payout.idempotency_key,
        contest_id=payout.handover.award.contest_id,
        prize_amount=payout.prize_amount,
        platform_fee_amount=payout.platform_fee_amount,
        withholding_tax_amount=payout.withholding_tax_amount,
        net_amount=payout.net_amount,
        status=payout.status,
        has_identity=TaxIdentity.objects.filter(payout=payout).exists(),
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

    payout = get_or_create_payout(handover)

    adapter = get_adapter()
    adapter.request_payout(idempotency_key=str(payout.idempotency_key), amount=payout.net_amount)

    return 201, _serialize(payout)


@router.get(
    "/contests/{contest_id}/payout", response={200: PayoutOut, 403: ErrorOut, 404: ErrorOut}, auth=jwt_auth
)
def get_payout(request: HttpRequest, contest_id: int):
    handover = _get_owned_handover(request, contest_id)

    payout = Payout.objects.filter(handover=handover).select_related(
        "handover__award__contest"
    ).first()
    if payout is None:
        raise HttpError(404, "아직 지급 요청이 없습니다.")

    return 200, _serialize(payout)


def _get_owned_payout(request: HttpRequest, idempotency_key: UUID) -> Payout:
    try:
        payout = Payout.objects.select_related(
            "handover__award__contest", "handover__award__submission__developer"
        ).get(idempotency_key=idempotency_key)
    except Payout.DoesNotExist as exc:
        raise HttpError(404, "지급 요청을 찾을 수 없습니다.") from exc

    if payout.handover_id is None:
        # Distribution(#16) 경로의 Payout이다 — 이 라우터는 Award/Handover 경로
        # 전용이라 여기서는 존재 자체를 숨긴다(Handover가 없는 Contest를 조회할
        # 때와 같은 404).
        raise HttpError(404, "지급 요청을 찾을 수 없습니다.")

    if payout.handover.award.submission.developer.user_id != request.auth_user.id:
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
        payout = mark_confirmed(idempotency_key)
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

    if payout.status not in (Payout.Status.CONFIRMED_IDENTITY_PENDING, Payout.Status.CONFIRMED):
        raise HttpError(
            409, "지급이 확정된 뒤에만 신원 정보를 제출할 수 있습니다."
        )

    payout = submit_identity(payout, payload.resident_registration_number)
    return 200, _serialize(payout)
