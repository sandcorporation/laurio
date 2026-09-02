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
from payouts.adapters_toss import (
    TossPayoutAdapter,
    TossSellerAdapter,
    jwe_decrypt,
    jwe_encrypt,
    verify_toss_webhook_signature,
)
from payouts.models import Seller
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
    import base64
    import hashlib
    import hmac

    payload = b'{"eventType":"payout.changed"}'
    transmission_time = "2024-01-01T00:00:00+09:00"
    secure_key = "toss-secure-key"
    expected = hmac.new(
        secure_key.encode(), f"{payload.decode()}:{transmission_time}".encode(), hashlib.sha256
    ).digest()
    header = f"v1:{base64.b64encode(expected).decode()},v1:{base64.b64encode(b'stale-key-sig').decode()}"

    assert verify_toss_webhook_signature(
        payload=payload, transmission_time=transmission_time, signature_header=header, secure_key=secure_key
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


# --- TossPayoutAdapter — 두 갈래 confirm ------------------------------------------------


def test_confirm_none_seller_short_circuits_without_network_call():
    """`_resolve_seller`가 던지는 예외/경로가 아니라 "Seller가 준비 안 됐다"
    분기 자체는 순수하게 unit 레벨에서도 검증할 수 있다 — `_request_real_payout`
    이 아예 호출되지 않는지를 patch로 확인한다."""

    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(Mock(), None)):
            with patch("payouts.adapters_toss.requests.post") as mock_post:
                result = adapter.confirm(idempotency_key="11111111-1111-1111-1111-111111111111")

    assert result == "paid"
    mock_post.assert_not_called()


def test_confirm_with_ready_seller_calls_vendor_and_maps_completed_to_paid():
    payout = Mock(idempotency_key="22222222-2222-2222-2222-222222222222", net_amount=900_000)
    seller = Mock(status=Seller.Status.PARTIALLY_APPROVED, seller_id="seller-1")

    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(payout, seller)):
            with patch("payouts.adapters_toss.requests.post") as mock_post:
                mock_post.return_value = _encrypted_response(200, {"status": "COMPLETED"})
                result = adapter.confirm(idempotency_key=str(payout.idempotency_key))

    assert result == "paid"
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Idempotency-Key"] == str(payout.idempotency_key)
    sent_body = jwe_decrypt(kwargs["data"], secure_key_hex=_SECURE_KEY_HEX)
    assert sent_body["sellerId"] == "seller-1"
    assert sent_body["refPayoutId"] == str(payout.idempotency_key)


def test_confirm_with_ready_seller_maps_failed_status_to_failed():
    payout = Mock(idempotency_key="33333333-3333-3333-3333-333333333333", net_amount=1_000)
    seller = Mock(status=Seller.Status.APPROVED, seller_id="seller-2")

    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(payout, seller)):
            with patch("payouts.adapters_toss.requests.post") as mock_post:
                mock_post.return_value = _encrypted_response(200, {"status": "FAILED"})
                result = adapter.confirm(idempotency_key=str(payout.idempotency_key))

    assert result == "failed"


def test_confirm_with_ready_seller_in_progress_raises_timeout():
    payout = Mock(idempotency_key="44444444-4444-4444-4444-444444444444", net_amount=1_000)
    seller = Mock(status=Seller.Status.APPROVED, seller_id="seller-3")

    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(payout, seller)):
            with patch("payouts.adapters_toss.requests.post") as mock_post:
                mock_post.return_value = _encrypted_response(200, {"status": "IN_PROGRESS"})
                with pytest.raises(PayoutTimeoutError):
                    adapter.confirm(idempotency_key=str(payout.idempotency_key))


def test_confirm_network_error_raises_payout_timeout_error():
    payout = Mock(idempotency_key="55555555-5555-5555-5555-555555555555", net_amount=1_000)
    seller = Mock(status=Seller.Status.APPROVED, seller_id="seller-4")

    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(payout, seller)):
            with patch(
                "payouts.adapters_toss.requests.post",
                side_effect=requests.ConnectionError("connection reset"),
            ):
                with pytest.raises(PayoutTimeoutError):
                    adapter.confirm(idempotency_key=str(payout.idempotency_key))


def test_query_status_without_ready_seller_returns_pending_without_network_call():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(Mock(), None)):
            with patch("payouts.adapters_toss.requests.get") as mock_get:
                assert adapter.query_status(idempotency_key="unknown") == "pending"

    mock_get.assert_not_called()


def test_query_status_with_ready_seller_maps_vendor_statuses():
    payout = Mock(idempotency_key="66666666-6666-6666-6666-666666666666")
    seller = Mock(status=Seller.Status.APPROVED, seller_id="seller-5")

    with _settings():
        adapter = TossPayoutAdapter()
        with patch.object(adapter, "_resolve_seller", return_value=(payout, seller)):
            with patch("payouts.adapters_toss.requests.get") as mock_get:
                mock_get.return_value = _encrypted_response(200, {"status": "COMPLETED"})
                assert adapter.query_status(idempotency_key=str(payout.idempotency_key)) == "paid"


def test_request_payout_never_calls_vendor():
    with _settings():
        adapter = TossPayoutAdapter()
        with patch("payouts.adapters_toss.requests.post") as mock_post:
            result = adapter.request_payout(idempotency_key="k", amount=1000)

    mock_post.assert_not_called()
    assert result.accepted is True
