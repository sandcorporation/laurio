"""`PortOneV2VerificationAdapter` 단위 테스트 (#85, ADR-0007).

`test_core_adapters.py`와 같은 이유로 이 파일은 HTTP를 거치지 않는다 — 이
어댑터는 어느 API에도 매여 있지 않은 순수 인프라 클래스이고(`verification.api`는
`VerificationAdapter` 계약만 알 뿐 구현체를 모른다), 검증 대상은 "포트원이
이런저런 응답을 줬을 때 이 어댑터가 계약대로 옮기는가"라는 이 클래스 자신의
행동이다. `requests.get`을 직접 모킹해 네트워크 없이 결정적으로 돈다.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from verification.adapters import (
    PortOneV2VerificationAdapter,
    VerificationAdapterError,
    VerificationMissingCIError,
)


def _fake_response(*, status_code=200, json_body=None, text="") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text or str(json_body)
    if json_body is None:
        response.json.side_effect = ValueError("no JSON body")
    else:
        response.json.return_value = json_body
    return response


def _verified_body(
    *, name="홍길동", birth_date="1990-01-01", ci="ci-real-1", di="di-real-1", phone_number=None
) -> dict:
    customer = {"name": name, "birthDate": birth_date, "ci": ci, "di": di}
    if phone_number is not None:
        customer["phoneNumber"] = phone_number
    return {"status": "VERIFIED", "verifiedCustomer": customer}


@pytest.fixture(autouse=True)
def _portone_credentials(monkeypatch):
    monkeypatch.setenv("PORT_ONE_V2_STORE_ID", "store-test-1")
    monkeypatch.setenv("PORT_ONE_V2_SECRET_KEY", "secret-test-1")
    yield


def test_adapter_construction_requires_both_credentials(monkeypatch):
    monkeypatch.delenv("PORT_ONE_V2_STORE_ID", raising=False)
    with pytest.raises(VerificationAdapterError):
        PortOneV2VerificationAdapter()


def test_adapter_construction_requires_secret_key(monkeypatch):
    monkeypatch.delenv("PORT_ONE_V2_SECRET_KEY", raising=False)
    with pytest.raises(VerificationAdapterError):
        PortOneV2VerificationAdapter()


def test_resolve_queries_portone_server_to_server_with_the_token_as_identity_verification_id():
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(json_body=_verified_body())
        result = adapter.resolve("iv-abc-123")

    called_url = mock_get.call_args.args[0]
    called_kwargs = mock_get.call_args.kwargs
    assert called_url == "https://api.portone.io/identity-verifications/iv-abc-123"
    assert called_kwargs["params"] == {"storeId": "store-test-1"}
    assert called_kwargs["headers"]["Authorization"] == "PortOne secret-test-1"

    assert result.real_name == "홍길동"
    assert result.ci == "ci-real-1"
    assert result.di == "di-real-1"
    from datetime import date

    assert result.birth_date == date(1990, 1, 1)


def test_resolve_extracts_the_phone_number_for_notification_channels():
    """#51 코드리뷰 지적 1: notifications가 실제로 문자를 보낼 대상 번호를
    포트원 응답의 verifiedCustomer.phoneNumber에서 가져온다."""

    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            json_body=_verified_body(phone_number="01099998888")
        )
        result = adapter.resolve("iv-abc-123")

    assert result.phone_number == "01099998888"


def test_resolve_defaults_phone_number_to_empty_string_when_vendor_omits_it():
    """phoneNumber는 포트원 계약상 필수가 아니다 — 없어도 본인확인 자체는
    성공하고, 빈 문자열로 남는다(verification.api.verify가 이 경우 PhoneContact를
    만들지 않는다)."""

    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(json_body=_verified_body(phone_number=None))
        result = adapter.resolve("iv-abc-123")

    assert result.phone_number == ""


def test_resolve_raises_not_500_when_identity_verification_id_does_not_exist():
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=404, text="not found")
        with pytest.raises(VerificationAdapterError):
            adapter.resolve("does-not-exist")


def test_resolve_raises_when_vendor_returns_a_server_error():
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=502, text="bad gateway")
        with pytest.raises(VerificationAdapterError):
            adapter.resolve("iv-abc-123")


def test_resolve_does_not_leak_the_raw_vendor_response_body_into_the_exception_message(caplog):
    """벤더 원문(response.text)이 예외 메시지에 실리면 verify()가 그걸 422 detail로
    그대로 사용자에게 돌려준다(#85 코드리뷰 지적 6) — 로그에만 남고 예외 메시지는
    일반화돼야 한다."""
    adapter = PortOneV2VerificationAdapter()
    secret_looking_body = "internal-trace-id=abc123 upstream=payment-core-7"

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(status_code=502, text=secret_looking_body)
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationAdapterError) as exc_info:
                adapter.resolve("iv-abc-123")

    assert secret_looking_body not in str(exc_info.value)
    assert any(secret_looking_body in r.getMessage() for r in caplog.records)


def test_resolve_raises_when_status_is_not_verified():
    """인증 실패·만료·아직 진행 중인 상태(FAILED/PENDING 등)는 4xx로 옮겨진다."""
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(json_body={"status": "FAILED"})
        with pytest.raises(VerificationAdapterError):
            adapter.resolve("iv-failed")


def test_resolve_wraps_network_errors():
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("boom")
        with pytest.raises(VerificationAdapterError):
            adapter.resolve("iv-abc-123")


def test_resolve_does_not_leak_the_request_url_when_the_network_call_fails(caplog):
    """`requests.RequestException`의 str()에는 요청 URL 전체(storeId 쿼리
    파라미터 포함)가 그대로 들어간다 — 예외 메시지에 그대로 실으면 verify()가
    422 detail로 사용자에게 돌려준다(#85 코드리뷰 지적 3). 로그에만 남아야
    한다."""
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError(
            "Max retries exceeded with url: /identity-verifications/iv-abc-123"
            "?storeId=store-test-1 (Caused by ...)"
        )
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationAdapterError) as exc_info:
                adapter.resolve("iv-abc-123")

    assert "store-test-1" not in str(exc_info.value)
    assert any("store-test-1" in r.getMessage() for r in caplog.records)


def test_resolve_raises_and_logs_when_response_is_not_json(caplog):
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(json_body=None, text="<html>not json</html>")
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationAdapterError):
                adapter.resolve("iv-abc-123")

    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_resolve_raises_and_logs_when_verified_customer_is_missing(caplog):
    """벤더 응답이 계약이 기대하는 모양이 아니면(필드 누락) 예외가 나고 로그가 남는다 —
    조용히 빈 값으로 채우지 않는다."""
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(json_body={"status": "VERIFIED"})
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationAdapterError):
                adapter.resolve("iv-abc-123")

    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_resolve_raises_and_logs_when_expected_fields_are_missing(caplog):
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            json_body={"status": "VERIFIED", "verifiedCustomer": {"name": "홍길동"}}
        )
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationAdapterError):
                adapter.resolve("iv-abc-123")

    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_resolve_does_not_leak_the_raw_birth_date_when_it_is_malformed(caplog):
    """`date.fromisoformat`이 거부하는 값을 그대로 받으면 그 ValueError의 str()에
    원본 문자열(생년월일, PII)이 그대로 들어간다 — 예외 메시지에 그대로 실으면
    verify()가 422 detail로 사용자에게 돌려준다(#85 코드리뷰 지적 3)."""
    adapter = PortOneV2VerificationAdapter()
    malformed_birth_date = "1990-99-99"

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            json_body={
                "status": "VERIFIED",
                "verifiedCustomer": {
                    "name": "홍길동",
                    "birthDate": malformed_birth_date,
                    "ci": "ci-1",
                    "di": "di-1",
                },
            }
        )
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationAdapterError) as exc_info:
                adapter.resolve("iv-abc-123")

    assert malformed_birth_date not in str(exc_info.value)
    assert any(malformed_birth_date in r.getMessage() for r in caplog.records)


def test_resolve_reuses_the_84_ci_invariant_instead_of_reimplementing_it():
    """CI가 비어 있는 응답은 #84가 세운 `VerificationMissingCIError`로 거절된다 —
    이 어댑터는 그 검사를 자기 안에 다시 두지 않는다(카카오처럼 CI를 안 주는
    인증 수단이 벤더 콘솔에서 실수로 다시 켜진 상황을 재현한다, ADR-0024)."""
    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            json_body={
                "status": "VERIFIED",
                "verifiedCustomer": {"name": "홍길동", "birthDate": "1990-01-01", "ci": "", "di": "di-1"},
            }
        )
        with pytest.raises(VerificationMissingCIError):
            adapter.resolve("iv-no-ci")


def test_resolve_logs_what_the_vendor_actually_returned_when_ci_is_missing(caplog):
    """CI가 없을 때 **벤더가 무엇을 줬는지**를 남긴다.

    이게 없으면 운영자는 "CI가 없다"만 보고 원인을 가릴 수 없다 — 콘솔에서
    CI를 안 주는 인증 수단(카카오, ADR-0024)이 다시 켜진 것인지, 아예 테스트
    채널이라 CI가 안 내려오는 것인지, 벤더가 필드 이름을 바꾼 것인지가 전부
    같은 한 줄로 보인다. staging 에서 실제로 이 상황을 만나 원인을 좁히지
    못했다(#52).

    **값이 아니라 필드 이름과 인증 수단만 남긴다** — verifiedCustomer 는 실명·
    생년월일·전화번호가 든 PII 덩어리라, 이 파일의 다른 테스트들이 이미 원문이
    로그·예외로 새지 않는 것을 고정하고 있다.
    """

    adapter = PortOneV2VerificationAdapter()

    with patch("verification.adapters.requests.get") as mock_get:
        mock_get.return_value = _fake_response(
            json_body={
                "status": "VERIFIED",
                "method": "IDENTITY_VERIFICATION_METHOD_UNIFIED",
                "verifiedCustomer": {
                    "name": "홍길동",
                    "birthDate": "1990-01-01",
                    "phoneNumber": "01012345678",
                    "di": "di-1",
                    "operator": "SHINHAN",
                },
            }
        )
        with caplog.at_level(logging.ERROR, logger="verification.adapters"):
            with pytest.raises(VerificationMissingCIError):
                adapter.resolve("iv-no-ci")

    logged = "\n".join(record.getMessage() for record in caplog.records)

    # 어떤 필드가 왔는지 — ci 가 아예 없었는지 빈 값이었는지가 여기서 갈린다.
    assert "birthDate" in logged
    assert "phoneNumber" in logged
    # 어느 인증 수단이었는지 — 카카오 회귀인지 아닌지를 가르는 값이다.
    assert "SHINHAN" in logged

    # **PII 는 새지 않는다.**
    assert "홍길동" not in logged
    assert "1990-01-01" not in logged
    assert "01012345678" not in logged
