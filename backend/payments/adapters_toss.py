"""토스페이먼츠 결제 어댑터 실물 구현 (#87, ADR-0007, ADR-0008).

`payments.adapters.PGAdapter` 계약만 만족시킨다 — Fake PG와 나란히 놓고 봐야
이해되는 코드다:

- **`confirm`은 벤더가 명시적으로 거절한 경우 예외를 던지지 않고 "failed"를
  돌려준다.** `FakePGAdapter.confirm`이 `simulate="failed"`를 그대로 "failed"로
  돌려주고, `PGError`는 "알 수 없는 시나리오"(=우리 쪽 프로그래밍 오류)에만
  쓰는 것과 같은 구분이다 — `PGError`를 던지면 `payments.api.confirm_payment`가
  이를 502로 바꾸고 `Payment`는 REQUESTED에 그대로 머문다(재시도해도 다시 502).
  카드 거절처럼 **결제 시도 자체가 정상적으로 끝난 결과**는 "failed"로 돌려줘야
  `mark_failed`가 Payment를 종결시키고, Sponsor가 "다시 시도"로 새 결제를 시작할
  수 있다. `PGError`는 우리 쪽 자격증명·요청 자체가 잘못된 경우(401/403)에만
  쓴다 — 그건 이 결제 건의 문제가 아니라 이 배포의 설정 문제이므로 종결시키면
  안 된다.
- **하지만 "거절" 버킷에는 "이미 성공했다"는 뜻인 코드가 섞여 있다(#87
  코드리뷰 지적 1·2).** 타임아웃 뒤 재시도가 받는 `ALREADY_PROCESSED_PAYMENT`
  (confirm)와 `ALREADY_CANCELED_PAYMENT`(refund)는 HTTP 4xx로 오지만 "돈이
  이미 성공적으로 움직였다"는 뜻이다 — 이 둘을 "failed"로 뭉개면 카드는
  긁혔는데 Payment는 실패로 남고 원장에 예치 분개가 없는, 정확히 돈이 새는
  경로가 된다. 이 두 코드만 별도로 골라내 실제 상태를 조회해 확정한다
  (`_resolve_confirm_via_query`/`_resolve_refund_via_query`) — "성공"이라고
  다시 뭉개는 게 아니라, 조회로 진짜 상태를 다시 확인한다.
- **HTTP 5xx·타임아웃·그 밖의 네트워크 예외는 전부 `PGTimeoutError`로
  통일한다(#87 코드리뷰 지적 5).** `requests.Timeout`뿐 아니라 커넥션 리셋 같은
  일반 `requests.RequestException`도 "요청이 벤더에 도달해 처리됐는지 알 수
  없다"는 점에서 같다 — 이걸 `PGError`로 던지면 환불 스캔(`services.
  _settle_new_refund_attempt`)이 "PG가 명시적으로 거부했다"로 읽어
  REFUND_FAILED로 영구 종결시킨다. 네트워크 실패는 "모른다"이지 "아니다"가
  아니므로 호출자는 `query_status`/`query_refund_status`로 실제 상태를
  확정해야 한다(ADR-0008이 지급 웹훅에 적용한 규율).
- **주문을 찾지 못한 조회(404)는 예외가 아니라 "아직 모른다"다.** `query_status`/
  `query_refund_status`는 "pending"을 돌려준다 — confirm이 벤더에 아직
  도달하지 못했을 수 있다. `refund`는 이미 PAID였던 주문만 대상으로 하므로
  "failed"를 돌려줄 수 없다(#87 코드리뷰 지적 8) — 대신 `PGTimeoutError`를
  던져 호출자가 `query_refund_status`로 재확인하게 한다. 벤더가 이 주문을
  아직 모른다는 사실 자체는 `query_*`와 `refund` 양쪽에서 "확정된 거부"가
  아니라는 같은 판단으로 다룬다.
- **벤더가 우리가 모르는 상태 문자열(또는 JSON이 아닌 본문)을 답하면 로그를
  남기고 예외를 던진다.** "성공"이나 "실패"로 임의로 뭉개면 그 상태가
  실제로 무엇을 뜻하는지 아무도 다시 확인하지 않는다.
- **부분 취소는 전액 환불이 아니다(#87 코드리뷰 지적 7).** 이 시스템은
  참여자 0명 전액 환불만 지원한다(ADR-0004) — `refund`는 항상 전체 금액을
  취소 요청하므로, 벤더가 `PARTIAL_CANCELED`로 답하면 우리가 기대한 전액
  취소가 아니라는 뜻이다. "refunded"로 뭉개지 않고 예외를 던진다.
"""

from __future__ import annotations

import logging
from base64 import b64encode

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .adapters import PaymentRequestResult, PGError, PGTimeoutError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tosspayments.com"
_TIMEOUT_SECONDS = 10

# 토스 결제 상태(PaymentStatus) — 공식 문서에 정의된 값만 인식한다. 여기 없는
# 문자열을 벤더가 새로 보내면(스펙 변경·오타·우리가 놓친 상태) "성공"이나 "실패"로
# 임의로 뭉개지 않고 예외를 던진다.
_PAID_STATUSES = {"DONE"}
_FAILED_STATUSES = {"CANCELED", "PARTIAL_CANCELED", "ABORTED", "EXPIRED"}
_PENDING_STATUSES = {"READY", "IN_PROGRESS", "WAITING_FOR_DEPOSIT"}
# 전액 취소만 "refunded"다 — PARTIAL_CANCELED는 별도로 다룬다(모듈 독스트링,
# 코드리뷰 지적 7).
_FULLY_REFUNDED_STATUS = "CANCELED"
_PARTIALLY_REFUNDED_STATUS = "PARTIAL_CANCELED"

# 이 코드가 우리 쪽 설정 문제(자격증명·요청 자체가 잘못됨)라고 판단하는 HTTP
# 상태다 — 이때만 PGError를 던져 재시도 없이 배포를 고치도록 유도한다. 그 외의
# 4xx는 벤더가 이 결제 시도를 정상적으로 거절한 것으로 본다(카드 거절 등).
_OUR_INTEGRATION_ERROR_STATUSES = {401, 403}

# "거절"처럼 보이는 4xx지만 실제로는 이미 성공했다는 뜻인 벤더 코드다(코드리뷰
# 지적 1·2) — 이 코드를 만나면 "failed"로 뭉개지 않고 실제 상태를 조회해
# 확정한다.
_CONFIRM_ALREADY_SUCCEEDED_CODES = {"ALREADY_PROCESSED_PAYMENT"}
_REFUND_ALREADY_SUCCEEDED_CODES = {"ALREADY_CANCELED_PAYMENT"}


class TossPGAdapter:
    """`PAYMENT_ADAPTER_MODE=payments.adapters_toss.TossPGAdapter`로 켠다.

    인자 없이 생성된다(`core.adapters.resolve_adapter`) — 자격증명은 전부 환경
    (`settings.TOSS_API_SECRET_KEY`)에서 읽는다. 비어 있으면 즉시
    `ImproperlyConfigured`를 던진다 — 배포 환경에서는
    `core.adapters.check_adapter_mode`가 이 생성 실패를 잡아 부팅 자체를
    거부한다(`core.E002`). dev에서는 이 클래스를 가리키도록 명시적으로 설정하지
    않는 한 생성되지 않는다(기본값은 여전히 fake).
    """

    def __init__(self) -> None:
        secret_key = settings.TOSS_API_SECRET_KEY
        if not secret_key:
            raise ImproperlyConfigured(
                "TOSS_API_SECRET_KEY 가 비어 있다 — PAYMENT_ADAPTER_MODE 를 실물 토스 "
                "어댑터로 켜려면 환경에 시크릿 키를 반드시 주입해야 한다(#87)."
            )
        self._secret_key = secret_key
        self._api_version = settings.TOSS_API_VERSION

    def _headers(self) -> dict[str, str]:
        # 토스는 시크릿 키를 HTTP Basic Auth의 username으로, password는 빈
        # 문자열로 받는다(벤더 문서 규약) — OAuth 토큰이 아니다.
        credentials = b64encode(f"{self._secret_key}:".encode()).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "TossPayments-api-version": self._api_version,
        }

    def _get_order(self, order_id: str) -> requests.Response:
        try:
            return requests.get(
                f"{_BASE_URL}/v1/payments/orders/{order_id}",
                headers=self._headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise PGTimeoutError(
                f"토스 결제 조회 요청이 타임아웃됐다(order_id={order_id})."
            ) from exc
        except requests.RequestException as exc:
            # 타임아웃이 아닌 일반 네트워크 예외(커넥션 리셋 등)도 "요청이
            # 벤더에 도달했는지 알 수 없다"는 점에서 타임아웃과 같다(#87
            # 코드리뷰 지적 5) — PGError로 던지면 refund()의 호출부가 이를
            # "PG가 명시적으로 거부했다"로 읽어 REFUND_FAILED로 영구 종결시킨다.
            raise PGTimeoutError(
                f"토스 결제 조회 요청이 네트워크 오류로 실패했다(order_id={order_id}): {exc}"
            ) from exc

    def request_payment(self, *, order_id: str, amount: int) -> PaymentRequestResult:
        """토스 결제위젯은 서버가 아니라 브라우저 SDK(clientKey)가 직접 연다 —
        Stripe Checkout Session 같은, 사전에 결제 세션을 서버가 만들어 URL을
        받는 API가 토스에는 없다. 그래서 이 메서드는 벤더를 전혀 호출하지 않고
        계약의 자리만 채운다 — `checkout_url`은 현재 프론트(#86)가 쓰지 않는다."""

        return PaymentRequestResult(
            order_id=order_id, checkout_url=f"https://checkout.tosspayments.com/{order_id}"
        )

    def confirm(
        self,
        *,
        order_id: str,
        simulate: str | None = None,
        payment_key: str | None = None,
        amount: int | None = None,
    ) -> str:
        # simulate는 Fake 전용 시나리오 선택 값이다 — 계약대로 받되 쓰지 않는다
        # (PGAdapter.confirm 문서 참고).
        del simulate

        if not payment_key:
            raise PGError(
                f"토스 결제 승인에는 payment_key가 필요하다(order_id={order_id}) — "
                "브라우저 위젯이 성공했을 때만 생기는 값이라 비어 있으면 위젯이 "
                "아직 성공하지 않았다는 뜻이다."
            )
        if amount is None:
            raise PGError(
                f"토스 결제 승인에는 amount가 필요하다(order_id={order_id})."
            )

        try:
            response = requests.post(
                f"{_BASE_URL}/v1/payments/confirm",
                json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
                headers=self._headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise PGTimeoutError(
                f"토스 결제 승인 요청이 타임아웃됐다(order_id={order_id}) — "
                "실제 결과는 query_status로 확정해야 한다."
            ) from exc
        except requests.RequestException as exc:
            raise PGTimeoutError(
                f"토스 결제 승인 요청이 네트워크 오류로 실패했다(order_id={order_id}): {exc} — "
                "실제 결과는 query_status로 확정해야 한다."
            ) from exc

        if response.status_code >= 500:
            # 벤더 쪽 오류 — 요청이 실제로 처리됐는지 알 수 없다. 타임아웃과
            # 같은 규율로 다룬다: 호출자가 query_status로 확정해야 한다.
            raise PGTimeoutError(
                f"토스가 결제 승인에서 서버 오류를 응답했다(order_id={order_id}, "
                f"status={response.status_code}) — 실제 결과는 query_status로 확정해야 한다."
            )

        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code") if body else None
            message = body.get("message") if body else response.text
            if response.status_code in _OUR_INTEGRATION_ERROR_STATUSES:
                raise PGError(
                    f"토스 결제 승인이 우리 쪽 설정 문제로 거부됐다(order_id={order_id}, "
                    f"code={code}): {message}"
                )
            if code in _CONFIRM_ALREADY_SUCCEEDED_CODES:
                # "거절"이 아니라 "이미 성공했다"는 뜻이다 — 타임아웃 뒤 재시도
                # 등으로 이미 확정된 paymentKey를 다시 confirm했을 때 온다(#87
                # 코드리뷰 지적 1). "failed"로 뭉개면 카드는 긁혔는데 Payment는
                # 실패로 종결된다.
                logger.info(
                    "토스 결제 승인이 '이미 처리됨'으로 응답했다 — 실제 상태를 "
                    "조회해 확정한다(order_id=%s, code=%s)",
                    order_id,
                    code,
                )
                return self._resolve_confirm_via_query(order_id)
            # 카드 거절 등 정상적인 결제 실패다 — Payment를 종결시켜야 한다.
            logger.info(
                "토스 결제 승인이 거절됐다(order_id=%s, code=%s): %s", order_id, code, message
            )
            return "failed"

        body = _require_json(response, context=f"결제 승인 응답, order_id={order_id}")
        status = body.get("status")
        if status in _PAID_STATUSES:
            return "paid"
        if status in _FAILED_STATUSES:
            return "failed"
        logger.error(
            "토스 결제 승인 응답에 알 수 없는 status가 왔다(order_id=%s): %r", order_id, status
        )
        raise PGError(
            f"토스 결제 승인 응답의 status를 알 수 없다(order_id={order_id}): {status!r}"
        )

    def _resolve_confirm_via_query(self, order_id: str) -> str:
        """`ALREADY_PROCESSED_PAYMENT` 뒤 실제 상태를 조회로 확정한다.

        `query_status`는 "paid"/"failed"/"pending" 중 하나를 돌려준다.
        "pending"이면 confirm()이 "failed"로 확정지을 수 없으므로(protocol은
        "paid"/"failed"만 허용한다) `PGTimeoutError`를 던져 호출자가 이미 갖고
        있는 재확인 경로(`payments.api.confirm_payment`의 `except
        PGTimeoutError` 블록)를 그대로 타게 한다.
        """

        status = self.query_status(order_id=order_id)
        if status == "pending":
            raise PGTimeoutError(
                f"토스가 '이미 처리됨'이라 답했지만 실제 상태를 아직 확정할 수 "
                f"없다(order_id={order_id}) — query_status로 다시 확인해야 한다."
            )
        return status

    def query_status(self, *, order_id: str) -> str:
        response = self._get_order(order_id)

        if response.status_code == 404:
            # 토스가 이 주문을 아직 모른다 — confirm이 벤더에 도달하기 전이거나
            # 애초에 존재하지 않는 주문이다. 어느 쪽이든 "아직 확정할 수 없다"는
            # 뜻이지 예외 상황이 아니다.
            return "pending"

        if response.status_code >= 400:
            body = _safe_json(response)
            raise PGError(
                f"토스 결제 조회가 실패했다(order_id={order_id}, "
                f"status={response.status_code}): {body}"
            )

        body = _require_json(response, context=f"결제 조회 응답, order_id={order_id}")
        status = body.get("status")
        if status in _PAID_STATUSES:
            return "paid"
        if status in _FAILED_STATUSES:
            return "failed"
        if status in _PENDING_STATUSES:
            return "pending"
        logger.error(
            "토스 결제 조회 응답에 알 수 없는 status가 왔다(order_id=%s): %r", order_id, status
        )
        raise PGError(f"토스 결제 조회 응답의 status를 알 수 없다(order_id={order_id}): {status!r}")

    def refund(self, *, order_id: str, amount: int, simulate: str | None = None) -> str:
        del simulate

        order_response = self._get_order(order_id)
        if order_response.status_code == 404:
            # refund()는 이미 PAID로 확정됐던 Payment에만 호출된다 — 그 시점엔
            # 토스가 이 주문을 반드시 알고 있어야 한다. 그런데도 404라면 "이
            # 환불이 실패했다"고 확정할 근거가 없다(#87 코드리뷰 지적 8,
            # query_status의 404 판정과 같은 원칙) — refund()는 "failed"를
            # 돌려줄 수 없으므로(이미 PAID였던 주문의 "결제 자체가 실패했다"는
            # 뜻이 되어버린다) PGTimeoutError로 "아직 모른다"를 표현한다.
            raise PGTimeoutError(
                f"환불하려는 주문을 토스에서 아직 찾을 수 없다(order_id={order_id}) — "
                "query_refund_status로 재확인해야 한다."
            )
        if order_response.status_code >= 400:
            body = _safe_json(order_response)
            raise PGError(
                f"환불 전 주문 조회가 실패했다(order_id={order_id}, "
                f"status={order_response.status_code}): {body}"
            )

        order_body = _require_json(
            order_response, context=f"환불 전 주문 조회 응답, order_id={order_id}"
        )
        payment_key = order_body.get("paymentKey")
        if not payment_key:
            raise PGError(
                f"토스 주문 조회 응답에 paymentKey가 없다(order_id={order_id}) — "
                "취소할 결제 건을 특정할 수 없다."
            )

        try:
            response = requests.post(
                f"{_BASE_URL}/v1/payments/{payment_key}/cancel",
                json={"cancelReason": "Laurio 환불 정책에 따른 자동 환불", "cancelAmount": amount},
                headers=self._headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise PGTimeoutError(
                f"토스 환불 요청이 타임아웃됐다(order_id={order_id}) — "
                "실제 결과는 query_refund_status로 확정해야 한다."
            ) from exc
        except requests.RequestException as exc:
            raise PGTimeoutError(
                f"토스 환불 요청이 네트워크 오류로 실패했다(order_id={order_id}): {exc} — "
                "실제 결과는 query_refund_status로 확정해야 한다."
            ) from exc

        if response.status_code >= 500:
            raise PGTimeoutError(
                f"토스가 환불에서 서버 오류를 응답했다(order_id={order_id}, "
                f"status={response.status_code}) — 실제 결과는 query_refund_status로 확정해야 한다."
            )

        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code") if body else None
            message = body.get("message") if body else response.text
            if response.status_code in _OUR_INTEGRATION_ERROR_STATUSES:
                raise PGError(
                    f"토스 환불이 우리 쪽 설정 문제로 거부됐다(order_id={order_id}, "
                    f"code={code}): {message}"
                )
            if code in _REFUND_ALREADY_SUCCEEDED_CODES:
                # "거절"이 아니라 "이미 환불됐다"는 뜻이다(#87 코드리뷰 지적 2)
                # — "failed"로 뭉개면 REFUND_FAILED로 영구 종결되고 원장에
                # 반대분개도 남지 않는다.
                logger.info(
                    "토스 환불이 '이미 취소됨'으로 응답했다 — 실제 상태를 조회해 "
                    "확정한다(order_id=%s, code=%s)",
                    order_id,
                    code,
                )
                return self._resolve_refund_via_query(order_id)
            logger.info(
                "토스 환불이 거절됐다(order_id=%s, code=%s): %s", order_id, code, message
            )
            return "failed"

        body = _require_json(response, context=f"환불 응답, order_id={order_id}")
        status = body.get("status")
        if status == _FULLY_REFUNDED_STATUS:
            return "refunded"
        if status == _PARTIALLY_REFUNDED_STATUS:
            # 이 시스템은 전액 환불만 요청한다(ADR-0004) — 그런데도 벤더가
            # 부분 취소로 답했다면 요청 금액과 실제 취소 금액이 어긋났다는
            # 뜻이다(#87 코드리뷰 지적 7). "refunded"로 뭉개 원장에 전액
            # 반대분개를 남기면 안 된다.
            logger.error(
                "토스 환불이 부분 취소로 끝났다 — 이 시스템은 전액 환불만 "
                "지원한다(order_id=%s, 요청 금액=%s)",
                order_id,
                amount,
            )
            raise PGError(
                f"토스 환불이 부분 취소로 끝났다(order_id={order_id}) — 요청한 "
                "전액이 취소되지 않았다."
            )
        logger.error(
            "토스 환불 응답에 알 수 없는 status가 왔다(order_id=%s): %r", order_id, status
        )
        raise PGError(f"토스 환불 응답의 status를 알 수 없다(order_id={order_id}): {status!r}")

    def _resolve_refund_via_query(self, order_id: str) -> str:
        """`ALREADY_CANCELED_PAYMENT` 뒤 실제 환불 상태를 조회로 확정한다.

        `query_refund_status`가 "pending"을 돌려주면(아직 벤더 쪽에 완전히
        반영되지 않았다) refund()도 "failed"로 확정지을 수 없으므로
        `PGTimeoutError`를 던져 호출자의 기존 재확인 경로를 그대로 타게 한다.
        """

        status = self.query_refund_status(order_id=order_id)
        if status == "pending":
            raise PGTimeoutError(
                f"토스가 '이미 취소됨'이라 답했지만 실제 상태를 아직 확정할 수 "
                f"없다(order_id={order_id}) — query_refund_status로 다시 확인해야 한다."
            )
        return status

    def query_refund_status(self, *, order_id: str) -> str:
        response = self._get_order(order_id)

        if response.status_code == 404:
            return "pending"

        if response.status_code >= 400:
            body = _safe_json(response)
            raise PGError(
                f"토스 환불 조회가 실패했다(order_id={order_id}, "
                f"status={response.status_code}): {body}"
            )

        body = _require_json(response, context=f"환불 조회 응답, order_id={order_id}")
        status = body.get("status")
        if status == _FULLY_REFUNDED_STATUS:
            return "refunded"
        if status in _PAID_STATUSES or status in _PENDING_STATUSES:
            # 아직 취소가 벤더 쪽에 반영되지 않았다 — 확정된 실패가 아니라
            # 재확인 대상이다.
            return "pending"
        if status == _PARTIALLY_REFUNDED_STATUS:
            # refund()와 같은 판단이다(#87 코드리뷰 지적 7) — 이 시스템은
            # 전액 환불만 지원하므로 부분 취소는 "refunded"로 뭉갤 수 없다.
            logger.error(
                "토스 환불 조회가 부분 취소 상태를 답했다(order_id=%s)", order_id
            )
            raise PGError(
                f"토스 환불 조회가 부분 취소 상태를 답했다(order_id={order_id}) — "
                "이 시스템은 전액 환불만 지원한다."
            )
        logger.error(
            "토스 환불 조회 응답에 알 수 없는 status가 왔다(order_id=%s): %r", order_id, status
        )
        raise PGError(
            f"토스 환불 조회 응답의 status를 알 수 없다(order_id={order_id}): {status!r}"
        )


def _safe_json(response: requests.Response) -> dict | None:
    try:
        return response.json()
    except ValueError:
        return None


def _require_json(response: requests.Response, *, context: str) -> dict:
    """2xx 응답인데 본문이 JSON이 아니면(#87 코드리뷰 지적 9) `response.json()`이
    `ValueError`를 그대로 던져 `PGError`도 `PGTimeoutError`도 아닌 계약 밖
    예외(결국 500)로 샌다 — 여기서 잡아 `PGError`로 바꾼다."""

    body = _safe_json(response)
    if body is None:
        raise PGError(f"토스 응답 본문이 JSON이 아니다({context}): {response.text!r}")
    return body
