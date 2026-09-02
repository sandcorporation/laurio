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


def _verified_body(*, name="홍길동", birth_date="1990-01-01", ci="ci-real-1", di="di-real-1") -> dict:
    return {
        "status": "VERIFIED",
        "verifiedCustomer": {"name": name, "birthDate": birth_date, "ci": ci, "di": di},
    }


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
