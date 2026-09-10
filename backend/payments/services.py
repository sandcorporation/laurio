"""결제 확정 도메인 로직.

API 레이어(`payments.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기
함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

핵심 규율(ADR-0003과 같은 조건부 UPDATE): `Payment.status`를
`UPDATE ... WHERE order_id=? AND status='requested'`로만 `paid`/`failed`로
전이시키고, rowcount가 1일 때만 원장에 분개를 남기고 Contest를 공개한다. 이 하나의
규율이 세 가지 장애 흐름을 전부 막는다:

- 같은 웹훅이 두 번 온다 — 두 번째 UPDATE는 rowcount 0이라 아무 것도 하지 않는다.
- 웹훅이 동기 confirm보다 먼저 도착한다 — 먼저 도착한 쪽이 rowcount 1을 가져가고,
  나중 것은 이미 바뀐 상태를 보고 조용히 넘어간다. 어느 쪽이 이기든 결과는 같다.
- confirm 호출이 타임아웃됐지만 실제로는 성공했다 — 타임아웃을 실패로 오인해 바로
  `failed`로 적으면 안 되므로, 호출자는 `query_status`로 진짜 결과를 확인한 뒤에만
  이 함수들을 부른다.
"""

from __future__ import annotations

from django.db import transaction

from contests.models import Contest
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from submissions.models import Submission

from core.contest_switch import contest_product_enabled
from core.scans import ScanSpec, scan_params

from .adapters import PGError, PGTimeoutError, get_adapter
from .models import Payment


# --- 참여자 0명 전액 환불 (#17, ADR-0004) ------------------------------------
#
# Charge 확정(payments.charges.apply_vendor_outcome)과 같은 조건부 UPDATE 규율을 그대로 반복하되, 절대
# 되돌아가지 않는다는 규율까지 함께 지킨다:
#
# 1) request_refund가 PAID -> REFUND_REQUESTED로 조건부 전이시켜 "이 스캔이 이
#    Payment의 환불을 시작할 권리를 가져갔다"를 표시한다. 두 스캔이 동시에 같은
#    Payment를 집어도 하나만 rowcount==1을 가져간다.
# 2) PG 어댑터의 확정 결과에 따라 mark_refunded(REFUNDED) 또는
#    mark_refund_failed(REFUND_FAILED)를 부른다. 이 두 종결 상태 중 어느 쪽에도
#    도달한 뒤에는 다시는 REFUND_REQUESTED로도, PAID로도 되돌아가지 않는다 —
#    Charge 확정이 REQUESTED에서 한 번만 전이하고 끝나는 것과 같은
#    성격이다. 되돌아가는 경로를 허용하면(과거 버전이 REFUND_REQUESTED ->
#    PAID로 되돌렸던 것처럼) 재전송된 실패 웹훅이 그 사이 새로 시작된 다른(더
#    최신) 환불 시도를 잘못 취소시켜, 실제로는 PG에서 성공한 환불이 원장에
#    반영되지 않고 다음 스캔이 같은 결제를 또 환불하는 이중 환불로 이어진다
#    (리뷰 지적 1).
# 3) adapter.refund()가 확정하지 못하고 "pending"으로 끝나면(타임아웃 후
#    query_refund_status로도 아직 안 끝났거나, 실제 어댑터가 진짜 비동기라서)
#    Payment는 REFUND_REQUESTED에 머문다. `payment-refund-reconcile` 스캔이 매번
#    이런 미확정 건도 함께 조회해 query_refund_status로만(=새 refund() 호출
#    없이) 재확인한다 — PAID만 후보로 삼으면 이 건들은 웹훅이 끝내 오지 않는 한
#    영원히 멈춰 있는다(리뷰 지적 3).


def request_refund(order_id) -> Payment | None:
    """PAID 결제를 refund_requested로 조건부 전이시킨다.

    다른 스캔이 이미 선점했거나(REFUND_REQUESTED/REFUNDED/REFUND_FAILED), 애초에
    PAID가 아니면 None을 돌려준다 — 호출자는 그 Payment를 건드리지 않고 넘어가야
    한다.
    """

    updated = Payment.objects.filter(order_id=order_id, status=Payment.Status.PAID).update(
        status=Payment.Status.REFUND_REQUESTED
    )
    if updated != 1:
        return None
    return Payment.objects.select_related("contest").get(order_id=order_id)


def mark_refunded(order_id) -> Payment:
    """환불을 완료로 확정한다. REFUND_REQUESTED 상태에서만 전이하며, 이겼을 때만
    (rowcount==1) 원장에 반대 분개를 남긴다.

    반대 분개는 Payment.journal 이 남긴 예치 분개의 각 라인 차/대변을 그대로 뒤집는다 —
    발주자 예치금은 다시 대변(환불), 개발자 미지급금(Prize)과 플랫폼 수수료 수익
    (개최 등록비)은 차변으로 취소된다. 세 라인 모두 원본과 금액이 같으므로 이
    Contest의 원장 순합계는 정확히 0으로 돌아온다.
    """

    with transaction.atomic():
        updated = Payment.objects.filter(
            order_id=order_id, status=Payment.Status.REFUND_REQUESTED
        ).update(status=Payment.Status.REFUNDED)
        payment = Payment.objects.select_related("contest").get(order_id=order_id)

        if updated != 1:
            # REFUND_REQUESTED가 아니었다 — 같은 웹훅 재전송이거나, 스캔이 동기적
            # 으로 이미 확정(REFUNDED/REFUND_FAILED)한 뒤에 뒤늦게 도착한 신호다.
            # REFUND_REQUESTED에서만 전이하고 다시는 되돌아가지 않으므로, 이 경우
            # 원장에는 손대지 않는다(REFUND_FAILED로 이미 종결된 시도를 뒤늦은
            # "성공" 신호가 되살리지도 않는다 — 그 시도는 끝났다).
            return payment

        entry = post_journal_entry(
            contest_id=payment.contest.ledger_id,
            reverses_id=payment.journal_entry_id,
            memo=(
                f"Contest #{payment.contest_id} 환불 — 참여자 0명 전액 환불 "
                f"(상금 {payment.prize_amount:,}원 + 개최 등록비 {payment.listing_fee_amount:,}원)"
            ),
            lines=[
                LineInput(
                    account=Account.DEVELOPER_PAYABLE,
                    side=EntrySide.DEBIT,
                    amount=payment.prize_amount,
                ),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.DEBIT,
                    amount=payment.listing_fee_amount,
                ),
                LineInput(
                    account=Account.SPONSOR_DEPOSIT,
                    side=EntrySide.CREDIT,
                    amount=payment.total_amount,
                ),
            ],
        )

        Payment.objects.filter(pk=payment.pk).update(refund_journal_entry_id=entry.id)
        payment.refund_journal_entry_id = entry.id

    return payment


def mark_refund_failed(order_id) -> Payment:
    """환불 실패를 REFUND_FAILED로 종결한다. PAID로 되돌리지 않는다.

    Payment.FAILED와 같은 성격의 종결 상태다 — 원장에는 아무 흔적도
    남기지 않는다(돈이 움직이지 않았거나, 움직였더라도 이 신호만으로는 확정할 수
    없다). REFUND_REQUESTED에서만 전이하므로 같은 실패 신호가 재전송돼도 두 번째
    호출은 rowcount 0으로 아무 일도 하지 않는다 — REFUND_REQUESTED -> PAID처럼
    되돌아가는 경로가 없으므로, 그 사이 이 Payment가 새 시도로 다시
    REFUND_REQUESTED에 들어갔더라도 그 새 시도를 잘못 취소시키지 않는다(리뷰
    지적 1). 이 스캔은 REFUND_FAILED를 자동으로 다시 집지 않는다 — 결제 실패가
    새 Payment(새 order_id)를 요구하는 것처럼, 이 환불도 재시도하려면 별도의
    명시적 조치가 필요하다.
    """

    Payment.objects.filter(order_id=order_id, status=Payment.Status.REFUND_REQUESTED).update(
        status=Payment.Status.REFUND_FAILED
    )
    return Payment.objects.get(order_id=order_id)


def _result(payment: Payment, status: str, *, claimed: bool, error: str | None = None) -> dict:
    """스캔 결과 한 줄.

    `claimed` 가 이 스캔이 **직접 환불을 수행했는지**를 말한다 — 이 필드가 없으면
    "내가 환불했다"와 "남이 시작한 환불을 확인했을 뿐이다"가 응답에서 구분되지
    않는다. 실제로 그 모호함 때문에 동시성 테스트가 뒤집힌 단언을 하고 있었다
    (#48): 두 스캔이 진짜로 겹치면 하나는 선점하고 다른 하나는 재확인해 결과가
    2줄이 되는데, `count` 만 보고 "환불이 두 번 일어났다"고 읽었다. 그래서 그
    테스트는 **경합이 실제로 일어날 때만 실패**했다.

    `count`(=len(results))의 뜻은 그대로 "이번 스캔이 처리한 행 수"다. 바뀐 것은
    각 행이 자기가 무엇을 했는지 말한다는 것뿐이다.
    """

    row = {
        "payment_id": payment.id,
        "contest_id": payment.contest_id,
        "status": status,
        "claimed": claimed,
    }
    if error is not None:
        row["error"] = error
    return row


def _settle_new_refund_attempt(adapter, claimed: Payment, *, simulate: str | None) -> dict:
    """방금 request_refund로 선점한 Payment에 대해 새 refund() 호출을 시도하고
    확정한다.

    어댑터가 던지는 예외는 이 함수 밖으로 내보내지 않는다 — 배치 하나(이 한 행)의
    실패가 나머지 배치를 막으면 안 된다(리뷰 지적 2, 4; chain A의 스케줄러 틱,
    scoring.services 의 submission-scoring 스캔과 같은 이유). PGTimeoutError는 실패가
    아니므로 query_refund_status로 재확인하는데, 그 재확인 호출 자체도 실패할 수
    있어 같은 방식으로 감싼다(리뷰 지적 2) — 감싸지 않으면 그 예외가 스캔 전체를
    500으로 죽이고, 이 Payment는 REFUND_REQUESTED에 갇힌 채(후보 쿼리가 PAID만
    보던 시절에는) 영원히 남았다.

    **REFUND_FAILED로 종결시키는 것은 `PGError`(PG가 명시적으로 거부했다는 확인된
    결과)뿐이다.** 그 밖의 예기치 못한 예외(어댑터 버그, 네트워크 오류가 다른
    예외 타입으로 새는 경우 등)는 "PG가 거부했다"는 확인이 아니라 "결과를 아직
    모른다"는 뜻이므로, REFUND_FAILED로 굳히면 안 된다 — REFUND_REQUESTED로 그냥
    남겨 다음 스캔의 재확인(_reconcile_pending_refund)이 마저 확정하게 한다.
    REFUND_FAILED를 종결 상태로 둔 것 자체는 이중 환불을 막기 위해 의도된
    설계이지만(#17), 그 방아쇠는 반드시 확인된 거부여야 한다 — 아니면 일시적
    장애 하나가 재시도 경로 없는 영구 실패로 굳어버린다.
    """

    order_id = str(claimed.order_id)
    try:
        status = adapter.refund(order_id=order_id, amount=claimed.total_amount, simulate=simulate)
    except PGTimeoutError:
        try:
            status = adapter.query_refund_status(order_id=order_id)
        except Exception as exc:  # noqa: BLE001 - 이 행만 실패시키고 배치는 계속한다.
            return _result(
                claimed, "pending", claimed=True, error=f"{type(exc).__name__}: {exc}"
            )
    except PGError as exc:
        # PG가 명시적으로 거부했다는 확인된 결과다 — 이때만 종결한다.
        mark_refund_failed(claimed.order_id)
        return _result(claimed, "failed", claimed=True, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - 확인되지 않은 예외는 재시도 대상으로 남긴다.
        return _result(
            claimed, "pending", claimed=True, error=f"{type(exc).__name__}: {exc}"
        )

    return _apply_refund_status(claimed, status, claimed=True)


def _reconcile_pending_refund(adapter, payment: Payment) -> dict:
    """이미 REFUND_REQUESTED인(=이전 스캔이 확정하지 못하고 남겨둔) Payment를 새
    refund() 호출 없이 query_refund_status로만 재확인한다.

    새로 refund()를 다시 부르지 않는 것이 핵심이다 — 이 Payment는 이미 한 번
    선점되어 PG에 환불이 요청된 상태이므로, 여기서 또 refund()를 부르면 같은
    금액이 PG에 중복 요청될 수 있다. 순수 조회만 반복해 안전하게 확정을
    기다린다(리뷰 지적 3).
    """

    try:
        status = adapter.query_refund_status(order_id=str(payment.order_id))
    except Exception as exc:  # noqa: BLE001 - 이 행만 실패시키고 배치는 계속한다.
        return _result(
            payment, "pending", claimed=False, error=f"{type(exc).__name__}: {exc}"
        )

    return _apply_refund_status(payment, status, claimed=False)


def _apply_refund_status(payment: Payment, status: str, *, claimed: bool) -> dict:
    if status == "refunded":
        mark_refunded(payment.order_id)
        return _result(payment, "refunded", claimed=claimed)
    if status == "failed":
        mark_refund_failed(payment.order_id)
        return _result(payment, "failed", claimed=claimed)
    # pending — 아직 확정할 수 없다. REFUND_REQUESTED로 남겨두고 다음 스캔의
    # 재확인(_reconcile_pending_refund)이나 웹훅이 마저 확정한다.
    return _result(payment, "pending", claimed=claimed)


# --- 참여자 0명 전액 환불 스캔 둘 (#17, #140, ADR-0003) -------------------------------
#
# Submission이 하나라도 있으면 이 스캔은 그 Contest의 Payment를 절대 건드리지 않는다 —
# 참여자 0명 전액 환불은 ADR-0004가 허용하는 유일한 환불 경로다. 후보가 두 종류라 스캔도
# 둘이다(리뷰 지적 3·4):
#
# 1) `payment-refund-request` — PAID인 새 후보. request_refund로 선점하고 새 refund()를 부른다.
# 2) `payment-refund-reconcile` — 이미 REFUND_REQUESTED인 미확정 후보. 새 refund()를 다시
#    부르지 않고 query_refund_status로만 재확인한다.
#
# `simulate`(scan_params)는 새 refund() 호출(1번)에만 적용되는 fake PG 전용 시나리오 선택
# 값이다(`payments.api.ConfirmPaymentIn.simulate`와 같은 원칙 — 실제 어댑터는 무시한다).
# 재확인(2번)은 새 요청을 만들지 않는 순수 조회이므로 시나리오 선택이 의미가 없다 —
# FakePGAdapter가 최초 refund() 호출 시점에 기억해 둔 결과를 그대로 돌려준다.
_ADAPTER_KEY = f"{__name__}:adapter"


def _adapter(ctx):
    if _ADAPTER_KEY not in ctx:
        ctx[_ADAPTER_KEY] = get_adapter()
    return ctx[_ADAPTER_KEY]


def _eligible_contests():
    # CLOSED뿐 아니라 JUDGING_ENDED도 봐야 한다(#13이 JUDGING_ENDED를 도입한 뒤 반영되지
    # 않은 채 남아 있던 격차) — 스케줄러가 judging_ends_at이 지나면 CLOSED -> JUDGING_ENDED로
    # 무조건 전이시키므로(award 여부와 무관), 참여자 0명인 Contest도 이 스캔이 따라잡기 전에
    # JUDGING_ENDED로 넘어갈 수 있다. CLOSED만 보면 그 순간부터 이 Payment는 영원히 이
    # 스캔의 후보 집합 밖으로 빠져 Escrow에 갇힌다 — "새 상태, 낡은 호출부" 패턴 그대로다.
    #
    # refund_disabled인 Contest는 제외한다(#13이 만든 필드의 유일한 소비처) — REQUEST.md:
    # 유료 연장 2회 이상이면 환불 불가로 영구 확정된다. 이 플래그가 True인 Contest는 설령
    # 참여자가 0명이어도 이 경로로 환불하지 않는다.
    contests_with_submissions = Submission.objects.values_list("contest_id", flat=True)
    return Contest.objects.filter(
        status__in=Contest.Status.REFUNDABLE.statuses,
        refund_disabled=False,
    ).exclude(id__in=contests_with_submissions)


def _new_refund_candidates(as_of, ctx):
    return Payment.objects.filter(
        status=Payment.Status.PAID, contest__in=_eligible_contests()
    ).select_related("contest")


def _request_and_settle(payment, as_of, ctx):
    claimed = request_refund(payment.order_id)
    if claimed is None:
        # 다른 스캔이 이미 이 Payment의 환불을 선점했다 — 건드리지 않는다.
        return None
    return _settle_new_refund_attempt(_adapter(ctx), claimed, simulate=scan_params(ctx).get("simulate"))


def _pending_refund_candidates(as_of, ctx):
    return Payment.objects.filter(
        status=Payment.Status.REFUND_REQUESTED, contest__in=_eligible_contests()
    ).select_related("contest")


def _reconcile(payment, as_of, ctx):
    return _reconcile_pending_refund(_adapter(ctx), payment)


# 배치 50은 뼈대 기본값 그대로다 — 무제한 스캔은 백로그가 쌓였을 때 이 스캔을 호출하는 HTTP
# 요청 자체를 타임아웃으로 몰아넣는다(리뷰 지적 4). 배치를 넘는 잔여 분량은 다음 실행이 마저
# 처리한다.
#
# `enabled=contest_product_enabled`(#271) — 공모전 제품 스위치가 꺼지면 이 둘은
# 등록부에서 사라진 것처럼 군다. 환불은 상금이 있는 공모전에만 존재하므로
# (Assignment 에는 Payment 자체가 없다) 이 스위치가 유일하게 지키려는 "돈이 실제
# 결제 대행사로 나가는 경로" 그 자체다.
REFUND_SCANS = (
    ScanSpec(
        name="payment-refund-request",
        candidates=_new_refund_candidates,
        handle_row=_request_and_settle,
        enabled=contest_product_enabled,
    ),
    ScanSpec(
        name="payment-refund-reconcile",
        candidates=_pending_refund_candidates,
        handle_row=_reconcile,
        enabled=contest_product_enabled,
    ),
)
