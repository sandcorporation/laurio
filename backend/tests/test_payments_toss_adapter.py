"""토스 결제 어댑터 실물 구현 단위 테스트 (#87, ADR-0007).

`TossPGAdapter`는 벤더 경계 코드다 — 마운트된 API를 거쳐 검증할 수 있는 "우리
애플리케이션 로직"이 아니라 "토스가 무엇을 답하든 우리가 계약대로 해석하는가"를
검증한다(CLAUDE.md의 HTTP 시임 규율은 서비스·엔드포인트에 적용된다 — 이 파일은
S3StorageAdapter를 boto3 mocking으로 검증하는 것과 같은 층위다). 네트워크는 항상
`unittest.mock.patch`로 대체한다 — 기본 스위트는 결정적이고 오프라인이어야
한다(AC).

실제 벤더를 치는 것은 `test_live_adapters.py`의 몫이다(옵인, `@live_vendor`).

코드리뷰(#87)로 드러난 "거절처럼 보이지만 사실은 성공/이미 성공/네트워크
불확실"의 세 버킷을 각각 못 박아 둔다 — 특히 `ALREADY_CANCELED_PAYMENT`를
"failed"로 착각했던 예전 테스트가 그 버그를 고정시켰던 자리이므로, 여기서는
"이미 성공했다"는 벤더 코드가 실제로 재조회를 거쳐 성공으로 확정되는지를
직접 검증한다.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import Mock, patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from payments.adapters import PGAdapter, PGError, PGTimeoutError
from payments.adapters_toss import TossPGAdapter


def _adapter() -> TossPGAdapter:
    with override_settings(TOSS_API_SECRET_KEY="test_sk_dummy", TOSS_API_VERSION="2022-11-16"):
        return TossPGAdapter()


def _response(status_code: int, json_body: dict | None = None, text: str = "") -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text if json_body is None else json.dumps(json_body)
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


# --- 생성 · 계약 ------------------------------------------------------------


def test_adapter_requires_secret_key():
    with override_settings(TOSS_API_SECRET_KEY=""):
        with pytest.raises(ImproperlyConfigured):
            TossPGAdapter()


def test_adapter_satisfies_pgadapter_protocol():
    assert isinstance(_adapter(), PGAdapter)


def test_request_payment_does_not_call_vendor():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post, patch(
        "payments.adapters_toss.requests.get"
    ) as mock_get:
        result = adapter.request_payment(order_id="order-1", amount=10_000)

    mock_post.assert_not_called()
    mock_get.assert_not_called()
    assert result.order_id == "order-1"
    assert result.checkout_url


# --- confirm -----------------------------------------------------------------


def test_confirm_success_sends_basic_auth_and_returns_paid():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"status": "DONE"})
        result = adapter.confirm(
            order_id="order-1", payment_key="pk-1", amount=10_000
        )

    assert result == "paid"
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"paymentKey": "pk-1", "orderId": "order-1", "amount": 10_000}
    auth_header = kwargs["headers"]["Authorization"]
    assert auth_header.startswith("Basic ")
    decoded = base64.b64decode(auth_header.removeprefix("Basic ")).decode()
    assert decoded == "test_sk_dummy:"
    assert kwargs["headers"]["TossPayments-api-version"] == "2022-11-16"


def test_confirm_requires_payment_key():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        with pytest.raises(PGError):
            adapter.confirm(order_id="order-1", payment_key=None, amount=10_000)
    mock_post.assert_not_called()


def test_confirm_requires_amount():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        with pytest.raises(PGError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=None)
    mock_post.assert_not_called()


def test_confirm_vendor_decline_returns_failed_not_raise():
    """카드 거절처럼 벤더가 정상적으로 거절한 결과는 예외가 아니라 "failed"다 —
    PGError를 던지면 Payment가 REQUESTED에 갇혀 재시도해도 502만 반복된다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        mock_post.return_value = _response(
            400, {"code": "REJECT_CARD_COMPANY", "message": "카드사에서 거절했습니다."}
        )
        result = adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)

    assert result == "failed"


def test_confirm_already_processed_resolves_via_query_and_returns_paid():
    """타임아웃 뒤 재시도가 받는 ALREADY_PROCESSED_PAYMENT는 승인이 실제로는
    성공했다는 뜻이다(#87 코드리뷰 지적 1) — "failed"로 뭉개면 카드는 긁혔는데
    Payment는 실패로 종결되고 원장에 예치 분개도 남지 않는다. 실제 상태를
    조회해 "paid"로 확정해야 한다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post, patch(
        "payments.adapters_toss.requests.get"
    ) as mock_get:
        mock_post.return_value = _response(
            400, {"code": "ALREADY_PROCESSED_PAYMENT", "message": "이미 처리된 결제입니다."}
        )
        mock_get.return_value = _response(200, {"status": "DONE"})

        result = adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)

    assert result == "paid"
    mock_get.assert_called_once()


def test_confirm_already_processed_still_pending_raises_pgtimeout():
    """재조회로도 아직 확정되지 않았다면(벤더 쪽 반영 지연) confirm()은
    "failed"로 확정지을 수 없다 — protocol이 "paid"/"failed"만 허용하므로
    PGTimeoutError를 던져 호출자의 기존 재확인 경로를 타게 한다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post, patch(
        "payments.adapters_toss.requests.get"
    ) as mock_get:
        mock_post.return_value = _response(400, {"code": "ALREADY_PROCESSED_PAYMENT"})
        mock_get.return_value = _response(200, {"status": "IN_PROGRESS"})

        with pytest.raises(PGTimeoutError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)


def test_confirm_our_credentials_rejected_raises_pgerror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        mock_post.return_value = _response(
            401, {"code": "UNAUTHORIZED_KEY", "message": "인증되지 않은 시크릿 키입니다."}
        )
        with pytest.raises(PGError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)


def test_confirm_timeout_raises_pgtimeouterror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post", side_effect=requests.Timeout("boom")):
        with pytest.raises(PGTimeoutError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)


def test_confirm_network_error_raises_pgtimeouterror():
    """타임아웃이 아닌 일반 네트워크 예외(커넥션 리셋 등)도 PGTimeoutError다
    (#87 코드리뷰 지적 5) — 요청이 벤더에 도달했는지 알 수 없다는 점에서
    타임아웃과 같다."""

    adapter = _adapter()
    with patch(
        "payments.adapters_toss.requests.post",
        side_effect=requests.ConnectionError("connection reset"),
    ):
        with pytest.raises(PGTimeoutError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)


def test_confirm_vendor_server_error_raises_pgtimeouterror():
    """5xx는 성공했는지 알 수 없다는 점에서 타임아웃과 같다 — query_status로
    확정해야 한다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        mock_post.return_value = _response(500, text="internal error")
        with pytest.raises(PGTimeoutError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)


def test_confirm_unknown_status_raises_and_logs(caplog):
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"status": "SOMETHING_NEW"})
        with caplog.at_level("ERROR"):
            with pytest.raises(PGError):
                adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)

    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_confirm_non_json_success_response_raises_pgerror():
    """2xx인데 본문이 JSON이 아니면 response.json()의 ValueError가 계약 밖으로
    새 500이 된다(#87 코드리뷰 지적 9) — PGError로 잡아야 한다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.post") as mock_post:
        mock_post.return_value = _response(200, json_body=None, text="<html>not json</html>")
        with pytest.raises(PGError):
            adapter.confirm(order_id="order-1", payment_key="pk-1", amount=10_000)


# --- query_status --------------------------------------------------------------


@pytest.mark.parametrize(
    "vendor_status,expected",
    [
        ("DONE", "paid"),
        ("CANCELED", "failed"),
        ("PARTIAL_CANCELED", "failed"),
        ("ABORTED", "failed"),
        ("EXPIRED", "failed"),
        ("READY", "pending"),
        ("IN_PROGRESS", "pending"),
        ("WAITING_FOR_DEPOSIT", "pending"),
    ],
)
def test_query_status_maps_known_vendor_statuses(vendor_status, expected):
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, {"status": vendor_status})
        assert adapter.query_status(order_id="order-1") == expected


def test_query_status_unknown_order_returns_pending_not_raise():
    """confirm이 벤더에 아직 도달하지 못했을 수도 있다 — 존재하지 않는
    order_id는 예외가 아니라 정해진 값(pending)으로 돌아온다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(404, {"code": "NOT_FOUND_PAYMENT"})
        assert adapter.query_status(order_id="order-does-not-exist") == "pending"


def test_query_status_unknown_vendor_status_raises_and_logs(caplog):
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, {"status": "MYSTERY"})
        with caplog.at_level("ERROR"):
            with pytest.raises(PGError):
                adapter.query_status(order_id="order-1")
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_query_status_vendor_error_raises_pgerror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(403, {"code": "FORBIDDEN"})
        with pytest.raises(PGError):
            adapter.query_status(order_id="order-1")


def test_query_status_timeout_raises_pgtimeouterror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get", side_effect=requests.Timeout("boom")):
        with pytest.raises(PGTimeoutError):
            adapter.query_status(order_id="order-1")


def test_query_status_network_error_raises_pgtimeouterror():
    adapter = _adapter()
    with patch(
        "payments.adapters_toss.requests.get",
        side_effect=requests.ConnectionError("connection reset"),
    ):
        with pytest.raises(PGTimeoutError):
            adapter.query_status(order_id="order-1")


def test_query_status_non_json_response_raises_pgerror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, json_body=None, text="not json")
        with pytest.raises(PGError):
            adapter.query_status(order_id="order-1")


# --- refund ---------------------------------------------------------------------


def test_refund_success_looks_up_payment_key_then_cancels():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post"
    ) as mock_post:
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        mock_post.return_value = _response(200, {"status": "CANCELED"})

        result = adapter.refund(order_id="order-1", amount=10_000)

    assert result == "refunded"
    get_url = mock_get.call_args[0][0]
    assert "order-1" in get_url
    post_url = mock_post.call_args[0][0]
    assert post_url.endswith("/v1/payments/pk-1/cancel")
    assert mock_post.call_args.kwargs["json"]["cancelAmount"] == 10_000


def test_refund_partial_cancel_raises_pgerror():
    """이 시스템은 전액 환불만 지원한다(ADR-0004) — 벤더가 PARTIAL_CANCELED로
    답하면 요청한 전액이 취소되지 않았다는 뜻이다(#87 코드리뷰 지적 7).
    "refunded"로 뭉개 원장에 전액 반대분개를 남기면 안 된다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post"
    ) as mock_post:
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        mock_post.return_value = _response(200, {"status": "PARTIAL_CANCELED"})

        with pytest.raises(PGError):
            adapter.refund(order_id="order-1", amount=5_000)


def test_refund_order_not_found_raises_pgtimeout_not_pgerror():
    """refund()는 이미 PAID였던 주문에만 호출된다 — 그런데도 404라면 "환불이
    실패했다"고 확정할 근거가 없다(#87 코드리뷰 지적 8, query_status의 404
    판정과 같은 원칙). PGError로 던지면 환불 스캔이 이를 "PG가 명시적으로
    거부했다"로 읽어 REFUND_FAILED로 영구 종결시킨다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(404, {"code": "NOT_FOUND_PAYMENT"})
        with pytest.raises(PGTimeoutError):
            adapter.refund(order_id="order-missing", amount=10_000)


def test_refund_order_lookup_network_error_raises_pgtimeout_not_pgerror():
    """#87 코드리뷰 지적 5의 정확한 재현이다 — 환불 전 주문 조회가 커넥션
    리셋으로 실패하면 "PG가 거부했다"가 아니라 "모른다"여야 한다. 예전
    코드는 이 경로에서 PGError를 던져 환불 스캔이 REFUND_FAILED로 영구
    종결시켰다."""

    adapter = _adapter()
    with patch(
        "payments.adapters_toss.requests.get",
        side_effect=requests.ConnectionError("connection reset"),
    ):
        with pytest.raises(PGTimeoutError):
            adapter.refund(order_id="order-1", amount=10_000)


def test_refund_vendor_decline_returns_failed():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post"
    ) as mock_post:
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        mock_post.return_value = _response(
            400, {"code": "NOT_CANCELABLE_AMOUNT", "message": "취소할 수 없는 금액입니다."}
        )

        assert adapter.refund(order_id="order-1", amount=10_000) == "failed"


def test_refund_already_canceled_resolves_via_query_and_returns_refunded():
    """같은 버킷이 ALREADY_CANCELED_PAYMENT(이미 환불됨)를 받으면 종결 상태
    REFUND_FAILED로 잘못 확정시켰던 문제다(#87 코드리뷰 지적 2) — 실제
    상태를 조회해 "refunded"로 확정해야 한다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post"
    ) as mock_post:
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        mock_post.return_value = _response(
            400, {"code": "ALREADY_CANCELED_PAYMENT", "message": "이미 취소된 결제입니다."}
        )

        # refund()가 "이미 취소됨"을 확인하러 다시 주문을 조회할 때는 CANCELED로
        # 답한다 — 취소 전 조회(paymentKey 확보용)와 이후 재확인 조회를 둘 다
        # 같은 mock_get이 순서대로 받는다.
        mock_get.side_effect = [
            _response(200, {"status": "DONE", "paymentKey": "pk-1"}),
            _response(200, {"status": "CANCELED"}),
        ]

        result = adapter.refund(order_id="order-1", amount=10_000)

    assert result == "refunded"
    assert mock_get.call_count == 2


def test_refund_already_canceled_still_pending_raises_pgtimeout():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post"
    ) as mock_post:
        mock_post.return_value = _response(400, {"code": "ALREADY_CANCELED_PAYMENT"})
        mock_get.side_effect = [
            _response(200, {"status": "DONE", "paymentKey": "pk-1"}),
            _response(200, {"status": "DONE"}),
        ]

        with pytest.raises(PGTimeoutError):
            adapter.refund(order_id="order-1", amount=10_000)


def test_refund_timeout_raises_pgtimeouterror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post", side_effect=requests.Timeout("boom")
    ):
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        with pytest.raises(PGTimeoutError):
            adapter.refund(order_id="order-1", amount=10_000)


def test_refund_cancel_network_error_raises_pgtimeouterror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post",
        side_effect=requests.ConnectionError("connection reset"),
    ):
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        with pytest.raises(PGTimeoutError):
            adapter.refund(order_id="order-1", amount=10_000)


def test_refund_non_json_success_response_raises_pgerror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get, patch(
        "payments.adapters_toss.requests.post"
    ) as mock_post:
        mock_get.return_value = _response(200, {"status": "DONE", "paymentKey": "pk-1"})
        mock_post.return_value = _response(200, json_body=None, text="not json")
        with pytest.raises(PGError):
            adapter.refund(order_id="order-1", amount=10_000)


# --- query_refund_status ----------------------------------------------------------


@pytest.mark.parametrize(
    "vendor_status,expected",
    [
        ("CANCELED", "refunded"),
        ("DONE", "pending"),
        ("IN_PROGRESS", "pending"),
    ],
)
def test_query_refund_status_maps_known_vendor_statuses(vendor_status, expected):
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, {"status": vendor_status})
        assert adapter.query_refund_status(order_id="order-1") == expected


def test_query_refund_status_partial_cancel_raises_pgerror():
    """refund()와 같은 판단이다(#87 코드리뷰 지적 7) — 부분 취소는 "refunded"가
    아니다."""

    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, {"status": "PARTIAL_CANCELED"})
        with pytest.raises(PGError):
            adapter.query_refund_status(order_id="order-1")


def test_query_refund_status_unknown_order_returns_pending():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(404, {"code": "NOT_FOUND_PAYMENT"})
        assert adapter.query_refund_status(order_id="order-missing") == "pending"


def test_query_refund_status_unknown_vendor_status_raises_and_logs(caplog):
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, {"status": "MYSTERY"})
        with caplog.at_level("ERROR"):
            with pytest.raises(PGError):
                adapter.query_refund_status(order_id="order-1")
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_query_refund_status_non_json_response_raises_pgerror():
    adapter = _adapter()
    with patch("payments.adapters_toss.requests.get") as mock_get:
        mock_get.return_value = _response(200, json_body=None, text="not json")
        with pytest.raises(PGError):
            adapter.query_refund_status(order_id="order-1")

