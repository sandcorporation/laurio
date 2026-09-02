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
- **HTTP 5xx·타임아웃은 `PGTimeoutError`로 통일한다.** 어느 쪽이든 "요청이
  벤더에 도달해 처리됐는지 알 수 없다"는 점에서 같다 — 호출자는 `query_status`/
  `query_refund_status`로 실제 상태를 확정해야 한다(ADR-0008이 지급 웹훅에 적용한
  규율).
- **주문을 찾지 못한 조회(404)는 예외가 아니라 "pending"이다.** `confirm`이
  타임아웃되기 전에는 토스가 이 주문을 아직 몰라도 정상이다 — "아직 벤더에
  도달하지 못했다"는 것도 "아직 확정되지 않았다"의 한 형태다. `FakePGAdapter`가
  모르는 order_id에 "pending"을 돌려주는 것과 같은 기본값이다.
- **벤더가 우리가 모르는 상태 문자열을 답하면 로그를 남기고 예외를 던진다.**
  "성공"이나 "실패"로 임의로 뭉개면 그 상태가 실제로 무엇을 뜻하는지 아무도
  다시 확인하지 않는다.
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
_REFUNDED_STATUSES = {"CANCELED", "PARTIAL_CANCELED"}

# 이 코드가 우리 쪽 설정 문제(자격증명·요청 자체가 잘못됨)라고 판단하는 HTTP
# 상태다 — 이때만 PGError를 던져 재시도 없이 배포를 고치도록 유도한다. 그 외의
# 4xx는 벤더가 이 결제 시도를 정상적으로 거절한 것으로 본다(카드 거절 등).
_OUR_INTEGRATION_ERROR_STATUSES = {401, 403}


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
            raise PGError(
                f"토스 결제 조회 요청이 실패했다(order_id={order_id}): {exc}"
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
            raise PGError(
                f"토스 결제 승인 요청이 실패했다(order_id={order_id}): {exc}"
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
            # 카드 거절 등 정상적인 결제 실패다 — Payment를 종결시켜야 한다.
            logger.info(
                "토스 결제 승인이 거절됐다(order_id=%s, code=%s): %s", order_id, code, message
            )
            return "failed"

        body = response.json()
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

        body = response.json()
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
            raise PGError(f"환불하려는 주문을 토스에서 찾을 수 없다(order_id={order_id}).")
        if order_response.status_code >= 400:
            body = _safe_json(order_response)
            raise PGError(
                f"환불 전 주문 조회가 실패했다(order_id={order_id}, "
                f"status={order_response.status_code}): {body}"
            )

        payment_key = order_response.json().get("paymentKey")
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
            raise PGError(f"토스 환불 요청이 실패했다(order_id={order_id}): {exc}") from exc

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
            logger.info(
                "토스 환불이 거절됐다(order_id=%s, code=%s): %s", order_id, code, message
            )
            return "failed"

        body = response.json()
        status = body.get("status")
        if status in _REFUNDED_STATUSES:
            return "refunded"
        logger.error(
            "토스 환불 응답에 알 수 없는 status가 왔다(order_id=%s): %r", order_id, status
        )
        raise PGError(f"토스 환불 응답의 status를 알 수 없다(order_id={order_id}): {status!r}")

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

        body = response.json()
        status = body.get("status")
        if status in _REFUNDED_STATUSES:
            return "refunded"
        if status in _PAID_STATUSES or status in _PENDING_STATUSES:
            # 아직 취소가 벤더 쪽에 반영되지 않았다 — 확정된 실패가 아니라
            # 재확인 대상이다.
            return "pending"
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
