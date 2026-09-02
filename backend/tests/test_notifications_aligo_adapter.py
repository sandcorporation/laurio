"""알리고(Aligo) SMS/LMS/알림톡 실물 어댑터 단위 테스트 (#51, ADR-0007, ADR-0009).

`notifications.adapters_aligo`는 벤더 경계 코드다 — `payments.adapters_toss`를
`unittest.mock.patch`로 검증하는 것과 같은 층위다(CLAUDE.md의 HTTP 시임 규율은
서비스·엔드포인트에 적용된다). 네트워크는 항상 mock으로 대체한다 — 기본
스위트는 결정적이고 오프라인이어야 한다(AC).

실제 벤더를 치는 것은 `test_live_adapters.py`의 몫이다(옵인, `@live_vendor`,
잔액 0인 계정이라 발송 성공은 검증하지 않는다).
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import requests
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from accounts.models import PhoneContact
from notifications.adapters import ChannelSendResult, NotificationChannelAdapter
from notifications.adapters_aligo import (
    AligoAlimtalkAdapter,
    AligoLmsAdapter,
    AligoSmsAdapter,
    _byte_length,
    _select_msg_type,
)
from notifications.models import Notification, NotificationType

_ALIGO_SETTINGS = dict(
    ALIGO_API_KEY="test-api-key",
    ALIGO_USER_ID="test-user-id",
    ALIGO_SENDER_PHONE_NUMBER="01000000000",
)


def _response(status_code: int, json_body: dict | None = None, text: str = "") -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text if json_body is None else json.dumps(json_body)
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


@pytest.fixture
def recipient(db):
    return get_user_model().objects.create_user(username="dev-aligo", password="pw-12345678")


def _notification(recipient, *, notification_type=NotificationType.SCORING_COMPLETE, context=None):
    return Notification(
        recipient=recipient,
        notification_type=notification_type,
        is_transactional=True,
        is_promotional=False,
        context=context or {"contest_title": "테스트 대회"},
    )


# --- 생성 · 계약 --------------------------------------------------------------


def test_sms_adapter_requires_credentials():
    with override_settings(ALIGO_API_KEY="", ALIGO_USER_ID="", ALIGO_SENDER_PHONE_NUMBER=""):
        with pytest.raises(ImproperlyConfigured):
            AligoSmsAdapter()


def test_lms_adapter_requires_credentials():
    with override_settings(ALIGO_API_KEY="", ALIGO_USER_ID="", ALIGO_SENDER_PHONE_NUMBER=""):
        with pytest.raises(ImproperlyConfigured):
            AligoLmsAdapter()


def test_alimtalk_adapter_requires_credentials():
    with override_settings(ALIGO_API_KEY="", ALIGO_USER_ID="", ALIGO_SENDER_PHONE_NUMBER=""):
        with pytest.raises(ImproperlyConfigured):
            AligoAlimtalkAdapter()


@override_settings(**_ALIGO_SETTINGS)
def test_adapters_satisfy_notification_channel_protocol():
    assert isinstance(AligoSmsAdapter(), NotificationChannelAdapter)
    assert isinstance(AligoLmsAdapter(), NotificationChannelAdapter)
    assert isinstance(AligoAlimtalkAdapter(), NotificationChannelAdapter)


# --- 길이 판정 -----------------------------------------------------------------


def test_select_msg_type_short_message_is_sms():
    assert _select_msg_type("짧은 메시지") == "SMS"


def test_select_msg_type_long_message_is_lms():
    long_message = "긴 메시지 내용 " * 30
    assert _byte_length(long_message) > 90
    assert _select_msg_type(long_message) == "LMS"


# --- 알림톡: 승인 전에는 항상 실패, 벤더를 호출하지 않는다 ---------------------


@override_settings(**_ALIGO_SETTINGS)
def test_alimtalk_adapter_always_fails_without_calling_vendor(recipient):
    adapter = AligoAlimtalkAdapter()
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    mock_post.assert_not_called()
    assert result.success is False
    assert result.failure_reason


# --- SMS: 전화번호 없음 -------------------------------------------------------


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_fails_without_calling_vendor_when_no_phone_on_file(recipient):
    adapter = AligoSmsAdapter()
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    mock_post.assert_not_called()
    assert result.success is False
    assert "전화번호" in result.failure_reason


# --- SMS: 짧은 메시지는 SMS로, 긴 메시지는 자르지 않고 LMS로 ------------------


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_sends_short_message_as_sms(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "message": "success"})
        result = adapter.send(
            recipient=recipient,
            notification=_notification(recipient, notification_type=NotificationType.APPEAL_RULED),
        )

    assert result == ChannelSendResult(success=True)
    kwargs = mock_post.call_args.kwargs
    assert kwargs["data"]["msg_type"] == "SMS"
    assert kwargs["data"]["receiver"] == "01011112222"
    assert kwargs["data"]["sender"] == "01000000000"


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_routes_a_long_message_to_lms_without_truncating(recipient):
    """돈 정보를 담은 문장(Distribution 최종 경고)이 길어도 잘리면 안 된다 —
    SMS 어댑터가 자체적으로 LMS 타입으로 전환해 전체 문구를 그대로 보낸다."""

    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    long_context = {
        "contest_title": "아주 긴 이름을 가진 해커톤 대회",
        "amount": 1_000_000,
        "distribution_due_at": "2026-09-30T08:00:00+09:00",
    }
    notification = _notification(
        recipient,
        notification_type=NotificationType.DISTRIBUTION_FINAL_WARNING,
        context=long_context,
    )

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "message": "success"})
        result = adapter.send(recipient=recipient, notification=notification)

    assert result == ChannelSendResult(success=True)
    kwargs = mock_post.call_args.kwargs
    assert kwargs["data"]["msg_type"] == "LMS"
    assert "title" in kwargs["data"]
    # 잘리지 않았다 — 렌더링된 전체 문구가 그대로 msg에 담긴다.
    from notifications.rendering import render_message

    assert kwargs["data"]["msg"] == render_message(notification)


# --- 벤더 실패 · 네트워크 오류는 예외가 아니라 실패 결과다 ---------------------


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_vendor_rejection_returns_failure_not_raise(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        # 잔액 0(실제 이 프로젝트 계정의 현재 상태)일 때 알리고가 돌려주는 모양 —
        # result_code가 1이 아니다.
        mock_post.return_value = _response(
            200, {"result_code": "-101", "message": "잔여 건수가 부족합니다."}
        )
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert "잔여 건수" in result.failure_reason


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_timeout_returns_failure_not_raise(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch(
        "notifications.adapters_aligo.requests.post", side_effect=requests.Timeout("boom")
    ):
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert result.failure_reason


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_network_error_returns_failure_not_raise(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch(
        "notifications.adapters_aligo.requests.post",
        side_effect=requests.ConnectionError("connection reset"),
    ):
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert result.failure_reason


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_non_json_response_returns_failure_not_raise(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, json_body=None, text="<html>error</html>")
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert result.failure_reason


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_http_error_status_returns_failure_not_raise(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(500, text="internal error")
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert result.failure_reason


# --- LMS 어댑터: 항상 LMS로 강제한다 ------------------------------------------


@override_settings(**_ALIGO_SETTINGS)
def test_lms_adapter_always_sends_as_lms_even_for_a_short_message(recipient):
    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoLmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "message": "success"})
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result == ChannelSendResult(success=True)
    assert mock_post.call_args.kwargs["data"]["msg_type"] == "LMS"


@override_settings(**_ALIGO_SETTINGS)
def test_lms_adapter_fails_without_calling_vendor_when_no_phone_on_file(recipient):
    adapter = AligoLmsAdapter()
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    mock_post.assert_not_called()
    assert result.success is False
