"""토스 지급대행 실물 어댑터(Seller 등록 + 실이체) 단위 테스트 (#57, ADR-0007/0008/0020).

`payments.adapters_toss`(#87)와 같은 층위 — 마운트된 API가 아니라 "벤더가
무엇을 답하든 우리가 계약대로 해석하는가"를 검증한다(CLAUDE.md HTTP 시임
규율은 서비스·엔드포인트에 적용된다). 네트워크는 항상 `unittest.mock.patch`로
대체한다.

실제 벤더를 치는 것은 `test_live_adapters.py`의 몫이다(옵인, `@live_vendor`).
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django.contrib.auth import get_user_model

from accounts.models import DeveloperProfile
from payouts.adapters import PayoutAdapter, PayoutError, PayoutTimeoutError, SellerAdapter, SellerError
from payouts.models import Seller
from payouts.adapters_toss import (
    TossPayoutAdapter,
    TossSellerAdapter,
    jwe_decrypt,
    jwe_encrypt,
    verify_toss_webhook_signature,
)
from verification.models import Verification

_SECURE_KEY_HEX = "a" * 64  # 32바이트(A256GCM) — 값 자체는 테스트 전용 더미다.


def _settings(**overrides):
    defaults = dict(
        TOSS_API_SECRET_KEY="test_sk_dummy",
        TOSS_API_SECURE_KEY=_SECURE_KEY_HEX,
        TOSS_API_VERSION="2022-11-16",
    )
    defaults.update(overrides)
    return override_settings(**defaults)


def _response(status_code: int, json_body: dict | None = None, text: str = "") -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text if json_body is None else json.dumps(json_body)
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


def _encrypted_response(status_code: int, body: dict) -> Mock:
    token = jwe_encrypt(body, secure_key_hex=_SECURE_KEY_HEX)
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = token
    response.json.side_effect = ValueError("jwe body, not plain json")
    return response


@pytest.fixture
def developer(db):
    User = get_user_model()
    user = User.objects.create_user(username="toss-seller-dev", email="dev@example.com")
    return DeveloperProfile.objects.create(user=user)


def _verify(developer, *, real_name="홍길동"):
    from datetime import date

    Verification.objects.create(
        user_id=developer.user_id,
        status=Verification.Status.VERIFIED,
        real_name=real_name,
        birth_date=date(1995, 1, 1),
    )


def _give_phone(developer, phone="01012345678"):
    seller, _ = Seller.objects.get_or_create(developer=developer)
    seller.phone_number = phone
    seller.save(update_fields=["phone_number_encrypted"])


# --- JWE round trip -----------------------------------------------------------------


def test_jwe_encrypt_decrypt_round_trip_preserves_payload():
    payload = {"businessType": "INDIVIDUAL", "individual": {"name": "홍길동"}}
    token = jwe_encrypt(payload, secure_key_hex=_SECURE_KEY_HEX)

    assert token.count(".") == 4
    assert jwe_decrypt(token, secure_key_hex=_SECURE_KEY_HEX) == payload


def test_jwe_decrypt_rejects_tampered_ciphertext():
    token = jwe_encrypt({"a": 1}, secure_key_hex=_SECURE_KEY_HEX)
    header, ekey, iv, ciphertext, tag = token.split(".")
    tampered = ".".join([header, ekey, iv, ciphertext[:-2] + ("AA" if ciphertext[-2:] != "AA" else "BB"), tag])

    with pytest.raises(SellerError):
        jwe_decrypt(tampered, secure_key_hex=_SECURE_KEY_HEX)


def test_jwe_encrypt_header_uses_dir_alg_and_a256gcm():
    token = jwe_encrypt({"x": 1}, secure_key_hex=_SECURE_KEY_HEX)
    header_b64 = token.split(".")[0]
    import base64

    padding = "=" * (-len(header_b64) % 4)
    header = json.loads(base64.urlsafe_b64decode(header_b64 + padding))
    assert header["alg"] == "dir"
    assert header["enc"] == "A256GCM"
    assert "iat" in header and "nonce" in header


# --- 웹훅 서명 검증 -------------------------------------------------------------------


def test_webhook_signature_accepts_matching_v1_entry():
    """secure_key는 hex 디코드한 32바이트를 HMAC 키로 쓴다(코드리뷰 지적 11) —
    JWE 암호화와 정확히 같은 해석. 여기서 계산하는 기대값도 같은 방식으로
    hex-decode해야 실제 구현과 맞아떨어진다."""

    import base64
    import hashlib
    import hmac

    payload = b'{"eventType":"payout.changed"}'
    transmission_time = "2024-01-01T00:00:00+09:00"
    secure_key = _SECURE_KEY_HEX
    expected = hmac.new(
        bytes.fromhex(secure_key),
        f"{payload.decode()}:{transmission_time}".encode(),
        hashlib.sha256,
    ).digest()
    header = f"v1:{base64.b64encode(expected).decode()},v1:{base64.b64encode(b'stale-key-sig').decode()}"

    assert verify_toss_webhook_signature(
        payload=payload, transmission_time=transmission_time, signature_header=header, secure_key=secure_key
    )


def test_webhook_signature_rejects_utf8_encoded_key_not_hex_decoded():
    """secure_key를 hex 디코드하지 않고 UTF-8 문자열 그대로 HMAC 키로 쓰면
    (코드리뷰 지적 11이 지적한 잘못된 해석) 서명이 달라져야 한다 — 두 해석이
    실제로 다른 결과를 낸다는 것 자체를 회귀 테스트로 고정해 둔다."""

    import base64
    import hashlib
    import hmac

    payload = b'{"eventType":"payout.changed"}'
    transmission_time = "2024-01-01T00:00:00+09:00"
    wrong_expected = hmac.new(
        _SECURE_KEY_HEX.encode("utf-8"),
        f"{payload.decode()}:{transmission_time}".encode(),
        hashlib.sha256,
    ).digest()
    header = f"v1:{base64.b64encode(wrong_expected).decode()}"

    assert not verify_toss_webhook_signature(
        payload=payload,
        transmission_time=transmission_time,
        signature_header=header,
        secure_key=_SECURE_KEY_HEX,
    )


def test_webhook_signature_rejects_wrong_signature():
    assert not verify_toss_webhook_signature(
        payload=b"{}", transmission_time="t", signature_header="v1:d3Jvbmc=", secure_key="secret"
    )


def test_webhook_signature_rejects_missing_header_or_key():
    assert not verify_toss_webhook_signature(
        payload=b"{}", transmission_time="t", signature_header=None, secure_key="secret"
    )
    assert not verify_toss_webhook_signature(
        payload=b"{}", transmission_time="t", signature_header="v1:AA==", secure_key=""
    )


# --- 생성 · 계약 ---------------------------------------------------------------------


def test_seller_adapter_requires_secret_key():
    with override_settings(TOSS_API_SECRET_KEY="", TOSS_API_SECURE_KEY=_SECURE_KEY_HEX):
        with pytest.raises(ImproperlyConfigured):
            TossSellerAdapter()


def test_seller_adapter_requires_secure_key():
    with override_settings(TOSS_API_SECRET_KEY="sk", TOSS_API_SECURE_KEY=""):
        with pytest.raises(ImproperlyConfigured):
            TossSellerAdapter()


def test_seller_adapter_satisfies_protocol():
    with _settings():
        assert isinstance(TossSellerAdapter(), SellerAdapter)


def test_payout_adapter_satisfies_protocol():
    with _settings():
        assert isinstance(TossPayoutAdapter(), PayoutAdapter)


# --- TossSellerAdapter.register — 신원 정보 누락 ---------------------------------------


@pytest.mark.django_db
def test_register_without_phone_does_not_call_vendor_and_returns_pending(developer):
    _verify(developer)
    # 전화번호를 아직 제출하지 않았다.

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            result = adapter.register(developer_id=developer.id)

    mock_post.assert_not_called()
    assert result.status == "pending"
    assert result.seller_id == ""


@pytest.mark.django_db
def test_register_without_verification_does_not_call_vendor_and_returns_pending(developer):
    _give_phone(developer)
    # 본인확인이 안 되어 있어 실명이 없다.

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            result = adapter.register(developer_id=developer.id)

    mock_post.assert_not_called()
    assert result.status == "pending"


# --- TossSellerAdapter.register — 정상 경로 --------------------------------------------


@pytest.mark.django_db
def test_register_sends_jwe_encrypted_body_with_individual_fields(developer):
    _verify(developer, real_name="홍길동")
    _give_phone(developer, phone="01099998888")

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(
                200,
                {
                    "refSellerId": f"laurio-developer-{developer.id}",
                    "sellerId": "seller-abc",
                    "status": "APPROVAL_REQUIRED",
                },
            )
            result = adapter.register(developer_id=developer.id)

    assert result.status == "approval_required"
    assert result.seller_id == "seller-abc"
    assert result.weekly_limit_amount is None

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["TossPayments-api-security-mode"] == "ENCRYPTION"
    sent_body = jwe_decrypt(kwargs["data"], secure_key_hex=_SECURE_KEY_HEX)
    assert sent_body["businessType"] == "INDIVIDUAL"
    assert sent_body["individual"] == {
        "name": "홍길동",
        "email": "dev@example.com",
        "phone": "01099998888",
    }


@pytest.mark.django_db
def test_register_maps_partially_approved_and_weekly_limit(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(
                200,
                {
                    "sellerId": "seller-xyz",
                    "status": "PARTIALLY_APPROVED",
                    "weeklyLimit": {"amount": 10_000_000},
                },
            )
            result = adapter.register(developer_id=developer.id)

    assert result.status == "partially_approved"
    assert result.weekly_limit_amount == 10_000_000


@pytest.mark.django_db
def test_register_maps_kyc_required_to_under_review(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(
                200, {"sellerId": "seller-x", "status": "KYC_REQUIRED"}
            )
            result = adapter.register(developer_id=developer.id)

    assert result.status == "under_review"


@pytest.mark.django_db
def test_register_maps_approved_with_no_weekly_limit(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(
                200, {"sellerId": "seller-x", "status": "APPROVED"}
            )
            result = adapter.register(developer_id=developer.id)

    assert result.status == "approved"
    assert result.weekly_limit_amount is None


@pytest.mark.django_db
def test_register_vendor_rejection_returns_rejected_not_raise(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(
                400, {"code": "INVALID_REQUEST", "message": "심사 기준 미달"}
            )
            result = adapter.register(developer_id=developer.id)

    assert result.status == "rejected"


@pytest.mark.django_db
def test_register_our_credentials_rejected_raises_sellererror(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(401, {"code": "UNAUTHORIZED_KEY"})
            with pytest.raises(SellerError):
                adapter.register(developer_id=developer.id)


@pytest.mark.django_db
def test_register_timeout_raises_sellererror(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post", side_effect=requests.Timeout("boom")):
            with pytest.raises(SellerError):
                adapter.register(developer_id=developer.id)


@pytest.mark.django_db
def test_register_unknown_status_raises_and_logs(developer, caplog):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(200, {"status": "SOMETHING_NEW"})
            with caplog.at_level("ERROR"):
                with pytest.raises(SellerError):
                    adapter.register(developer_id=developer.id)

    assert any(record.levelname == "ERROR" for record in caplog.records)


# --- TossPayoutAdapter — 순수 요청/응답 (#134/#135) ---------------------------------------
#
# adapter 는 Payout·Seller 를 읽지도 쓰지도 않는다. caller 가 TransferRequest 에 수취인·금액·
# vendor_ref 를 실어 보내고 VendorResult 를 받는다 — 여기 테스트에는 DB 픽스처가 없다.

from payouts.adapters import TransferRequest


def _req(**overrides):
    base = dict(
        idempotency_key="22222222-2222-2222-2222-222222222222",
        amount=900_000,
        seller_id="seller-1",
        vendor_ref="22222222-2222-2222-2222-222222222222-1",
        vendor_payout_id="",
    )
    base.update(overrides)
    return TransferRequest(**base)


def test_confirm_without_seller_id_is_internal_acceptance_without_network_call():
    """수취인이 아직 없는 요청 — 벤더 규약상 이체 API 가 없으므로 HTTP 없이 "paid"(내부 확정)."""
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            result = adapter.confirm(_req(seller_id=""))
    assert result.status == "paid"
    assert result.vendor_payout_id == ""
    mock_post.assert_not_called()


def test_confirm_posts_the_request_as_given_and_maps_completed_to_paid():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(200, {"id": "toss-payout-id-123", "status": "COMPLETED"})
            result = adapter.confirm(_req())
    assert result.status == "paid"
    assert result.vendor_payout_id == "toss-payout-id-123"  # caller 가 저장한다 — adapter 는 DB 를 쓰지 않는다
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Idempotency-Key"] == "22222222-2222-2222-2222-222222222222-1"
    sent_body = jwe_decrypt(kwargs["data"], secure_key_hex=_SECURE_KEY_HEX)
    assert sent_body["sellerId"] == "seller-1"
    assert sent_body["refPayoutId"] == "22222222-2222-2222-2222-222222222222-1"
    assert sent_body["amount"] == 900_000


def test_confirm_maps_failed_status_to_failed():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(200, {"status": "FAILED"})
            result = adapter.confirm(_req())
    assert result.status == "failed"


def test_confirm_in_progress_is_pending_with_the_vendor_id_kept():
    """아직 진행 중이면 예외가 아니라 pending 이다 — 벤더가 준 id 를 같이 돌려줘야 caller 가 그것으로
    조회를 이어간다(코드리뷰 지적 8)."""
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _encrypted_response(200, {"id": "toss-in-progress", "status": "IN_PROGRESS"})
            result = adapter.confirm(_req())
    assert result.status == "pending"
    assert result.vendor_payout_id == "toss-in-progress"


def test_confirm_network_error_raises_payout_timeout_error():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post", side_effect=requests.ConnectionError("connection reset")):
            with pytest.raises(PayoutTimeoutError):
                adapter.confirm(_req())


def test_query_status_without_seller_id_is_pending_without_network_call():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.get") as mock_get:
            result = adapter.query_status(_req(seller_id=""))
    assert result.status == "pending"
    mock_get.assert_not_called()


def test_query_status_uses_vendor_payout_id_when_present():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.get") as mock_get:
            mock_get.return_value = _encrypted_response(200, {"status": "COMPLETED"})
            result = adapter.query_status(_req(vendor_payout_id="toss-payout-id-999"))
    assert result.status == "paid"
    assert result.vendor_payout_id == "toss-payout-id-999"
    assert mock_get.call_args[0][0].endswith("/v2/payouts/toss-payout-id-999")


def test_query_status_without_vendor_payout_id_falls_back_to_ref_query():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.get") as mock_get:
            mock_get.return_value = _encrypted_response(200, {"id": "found-by-ref", "status": "IN_PROGRESS"})
            result = adapter.query_status(_req(vendor_ref="cccccccc-cccc-cccc-cccc-cccccccccccc-3"))
    assert result.status == "pending"
    assert result.vendor_payout_id == "found-by-ref"
    assert mock_get.call_args[0][0].endswith("/v2/payouts")
    assert mock_get.call_args.kwargs["params"] == {"refPayoutId": "cccccccc-cccc-cccc-cccc-cccccccccccc-3"}


def test_query_status_by_ref_returns_pending_on_404():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.get") as mock_get:
            mock_get.return_value = _response(404, {"code": "NOT_FOUND"})
            result = adapter.query_status(_req())
    assert result.status == "pending"


# --- 코드리뷰 후속(#57 2차): 12 -- SECURE_KEY 형식 검증 -----------------------------


def test_seller_adapter_rejects_secure_key_with_wrong_length():
    with override_settings(TOSS_API_SECRET_KEY="sk", TOSS_API_SECURE_KEY="ab" * 10):
        with pytest.raises(ImproperlyConfigured):
            TossSellerAdapter()


def test_seller_adapter_rejects_non_hex_secure_key():
    with override_settings(TOSS_API_SECRET_KEY="sk", TOSS_API_SECURE_KEY="z" * 64):
        with pytest.raises(ImproperlyConfigured):
            TossSellerAdapter()


def test_payout_adapter_rejects_secure_key_with_wrong_length():
    with override_settings(TOSS_API_SECRET_KEY="sk", TOSS_API_SECURE_KEY="ab" * 10):
        with pytest.raises(ImproperlyConfigured):
            TossPayoutAdapter()


def test_payout_adapter_rejects_non_hex_secure_key():
    with override_settings(TOSS_API_SECRET_KEY="sk", TOSS_API_SECURE_KEY="z" * 64):
        with pytest.raises(ImproperlyConfigured):
            TossPayoutAdapter()


# --- 코드리뷰 후속(#57 2차): 3 -- Seller 등록 5xx/429 ------------------------------


@pytest.mark.django_db
def test_register_vendor_server_error_raises_sellererror_not_rejected(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(500, text="internal error")
            with pytest.raises(SellerError):
                adapter.register(developer_id=developer.id)


@pytest.mark.django_db
def test_register_rate_limited_raises_sellererror_not_rejected(developer):
    _verify(developer)
    _give_phone(developer)

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(429, {"code": "TOO_MANY_REQUESTS"})
            with pytest.raises(SellerError):
                adapter.register(developer_id=developer.id)


# --- 코드리뷰 후속(#57 2차): 7 -- 재등록 대신 조회 ---------------------------------


@pytest.mark.django_db
def test_register_with_existing_seller_id_queries_instead_of_posting(developer):
    """이미 seller_id를 받은 상태라면 register()를 다시 불러도 POST가 아니라
    GET으로 현재 상태만 재확인한다(코드리뷰 지적 7) -- 고정된 refSellerId로
    또 POST하면 벤더의 "이미 등록됨" 4xx가 REJECTED로 잘못 매핑된다."""

    from payouts.models import Seller as SellerModel

    _verify(developer)
    _give_phone(developer)
    SellerModel.objects.filter(developer=developer).update(
        seller_id="already-registered-seller-id",
        status=SellerModel.Status.APPROVAL_REQUIRED,
    )

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post, patch(
            "payouts.adapters_toss.requests.get"
        ) as mock_get:
            mock_get.return_value = _encrypted_response(
                200, {"sellerId": "already-registered-seller-id", "status": "PARTIALLY_APPROVED"}
            )
            result = adapter.register(developer_id=developer.id)

    mock_post.assert_not_called()
    mock_get.assert_called_once()
    get_url = mock_get.call_args[0][0]
    assert "already-registered-seller-id" in get_url
    assert result.status == "partially_approved"


@pytest.mark.django_db
def test_register_with_rejected_existing_seller_posts_again(developer):
    """거절된 등록은 재시도(새 POST)를 허용한다 -- seller_id가 있어도 상태가
    REJECTED면 재등록 경로를 막지 않는다."""

    from payouts.models import Seller as SellerModel

    _verify(developer)
    _give_phone(developer)
    SellerModel.objects.filter(developer=developer).update(
        seller_id="old-seller-id", status=SellerModel.Status.REJECTED
    )

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post, patch(
            "payouts.adapters_toss.requests.get"
        ) as mock_get:
            mock_post.return_value = _encrypted_response(
                200, {"sellerId": "new-seller-id", "status": "APPROVAL_REQUIRED"}
            )
            result = adapter.register(developer_id=developer.id)

    mock_post.assert_called_once()
    mock_get.assert_not_called()
    assert result.seller_id == "new-seller-id"


@pytest.mark.django_db
def test_query_seller_status_unknown_id_returns_pending(developer):
    from payouts.models import Seller as SellerModel

    _verify(developer)
    _give_phone(developer)
    SellerModel.objects.filter(developer=developer).update(
        seller_id="missing-on-vendor", status=SellerModel.Status.APPROVAL_REQUIRED
    )

    with _settings():
        adapter = TossSellerAdapter()
        with patch("payouts.adapters_toss.requests.get") as mock_get:
            mock_get.return_value = _response(404, {"code": "NOT_FOUND_SELLER"})
            result = adapter.register(developer_id=developer.id)

    assert result.status == "pending"


# --- 코드리뷰 후속(#57 2차): 2 -- 실이체 한도/rate limit는 종결 실패가 아니다 ---------


def test_confirm_limit_exceeded_code_raises_timeout_not_failed():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(400, {"code": "EXCEED_WEEKLY_PAYOUT_LIMIT", "message": "주간 한도 초과"})
            with pytest.raises(PayoutTimeoutError):
                adapter.confirm(_req())


def test_confirm_rate_limited_429_raises_timeout_not_failed():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(429, {"code": "TOO_MANY_REQUESTS"})
            with pytest.raises(PayoutTimeoutError):
                adapter.confirm(_req())


def test_confirm_genuine_decline_still_returns_failed():
    """한도/rate-limit 키워드가 없는 진짜 거절은 여전히 "failed"다 -- 모든 4xx를 일시 오류로
    뭉개면 안 된다."""
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            mock_post.return_value = _response(400, {"code": "INVALID_ACCOUNT", "message": "invalid account"})
            result = adapter.confirm(_req())
    assert result.status == "failed"
