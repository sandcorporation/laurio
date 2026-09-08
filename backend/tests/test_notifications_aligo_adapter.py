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
    AligoQueryError,
    AligoSmsAdapter,
    _byte_length,
    _select_msg_type,
    query_remaining_balance,
)
from notifications.models import Notification, NotificationType
from notifications.rendering import render_message

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


def test_byte_length_does_not_undercount_characters_cp949_cannot_encode():
    """#51 코드리뷰 지적 2: cp949로 인코딩 안 되는 문자(이모지, em dash 등)를
    1바이트로 뭉개면 실제로는 SMS 한도를 넘는 메시지가 SMS로 분류된다. 이
    저장소가 실제 문구에 쓰는 em dash "—" 하나로도 재현된다."""

    plain = "짧은 문구"
    with_em_dash = plain + " — 안내"

    # em dash는 cp949로 인코딩할 수 없다 — UTF-8 기준 실제 바이트 수(3바이트)로
    # 잡혀야 한다. 예전 코드(errors="replace")는 이를 "?" 1바이트로 셌다.
    assert _byte_length(with_em_dash) - _byte_length(plain) >= _byte_length(" 안내") + 3


def test_byte_length_matches_the_reported_emoji_title_regression():
    """리뷰가 직접 측정한 사례를 그대로 고정한다: 이모지 15개가 섞인 문구는
    실제 페이로드(UTF-8 기준)에 가까운 크기로 계산돼야 하고, 예전처럼 SMS
    한도 아래로 과소평가되면 안 된다."""

    emoji_heavy = "🎉" * 25 + " 마감 임박!"
    # UTF-8에서 이모지 하나는 4바이트다 — 25개만으로 100바이트라, 나머지
    # 문구를 더하지 않아도 이미 SMS 한도(90바이트)를 넘는다. 예전 코드
    # (errors="replace")는 이모지 하나를 "?" 1바이트로 셌으므로 25개 전체가
    # 25바이트로 계산돼 SMS로 잘못 분류됐다.
    assert _byte_length(emoji_heavy) >= 100
    assert _select_msg_type(emoji_heavy) == "LMS"


# --- 알림톡: 승인 전에는 항상 실패, 벤더를 호출하지 않는다 ---------------------


@override_settings(**_ALIGO_SETTINGS)
def test_alimtalk_adapter_always_fails_without_calling_vendor(recipient):
    adapter = AligoAlimtalkAdapter()
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    mock_post.assert_not_called()
    assert result.success is False
    assert result.failure_reason


# --- SMS: 콤마가 섞인 값은 다중 수신자로 해석되지 않게 방어한다(#51 코드리뷰 지적 4) ---


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_refuses_to_call_vendor_when_stored_number_contains_a_comma(recipient):
    """PhoneContact.phone_number setter가 정규화로 이미 막지만, 레거시 데이터나
    직접 DB 조작으로 콤마가 섞인 값이 들어와도 벤더 호출 직전에 한 번 더
    막는다 — 알리고의 receiver는 콤마를 다중 수신자 구분자로 해석해 최대
    1000명까지 팬아웃될 수 있다."""

    from verification.crypto import encrypt

    contact = PhoneContact(user=recipient)
    contact.phone_number_encrypted = encrypt("01011112222,01099998888")
    contact.save()

    adapter = AligoSmsAdapter()
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    mock_post.assert_not_called()
    assert result.success is False


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
    # (connect, read) 튜플이어야 한다(#51 2차 코드리뷰 지적 3) — 스칼라
    # 하나를 쓰면 requests가 그 값을 connect·read 각각에 적용해 실제 최대
    # 대기 시간이 두 배가 된다.
    assert isinstance(kwargs["timeout"], tuple)
    assert sum(kwargs["timeout"]) <= 5


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

    assert result.success is True
    # #51 3차 코드리뷰 지적 6: NotificationDispatch.channel은 재시도 판단에
    # 쓰이는 슬롯 식별자라 "sms"로 그대로 남지만(notifications.services.
    # _attempt_dispatch), 실제로는 LMS로 승격돼 나갔다는 사실이 새 구멍이 될
    # 수 있다(notifications.E002는 바인딩 시점만 본다) — 그래서 발송 시점의
    # 이 사실이 failure_reason에 정직하게 남아야 한다.
    assert "LMS" in result.failure_reason
    assert "승격" in result.failure_reason
    kwargs = mock_post.call_args.kwargs
    assert kwargs["data"]["msg_type"] == "LMS"
    assert "title" in kwargs["data"]
    # 잘리지 않았다 — 렌더링된 전체 문구가 그대로 msg에 담긴다.
    from notifications.rendering import render_message

    assert kwargs["data"]["msg"] == render_message(notification)


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_promotion_note_survives_a_vendor_rejection_too(recipient):
    """#51 3차 코드리뷰 지적 6: 승격된 메시지가 벤더에게 거절당해도(성공이
    아니어도) "SMS 슬롯인데 실제로는 LMS로 보내려 했다"는 사실은 이력에
    남아야 한다 — 실패 사유만 보고서는 애초에 어떤 종류로 시도됐는지 알 수
    없어진다."""

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
        mock_post.return_value = _response(
            200, {"result_code": "-999", "message": "요청을 처리할 수 없습니다."}
        )
        result = adapter.send(recipient=recipient, notification=notification)

    assert result.success is False
    assert "LMS" in result.failure_reason
    assert "승격" in result.failure_reason
    assert "요청을 처리할 수 없습니다" in result.failure_reason


# --- 벤더 실패 · 네트워크 오류는 예외가 아니라 실패 결과다 ---------------------


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_vendor_rejection_returns_failure_not_raise(recipient):
    """벤더가 result_code로 명시적 거절을 답하는 일반적인 경우 — 성공(1)이
    아닌 어떤 코드든 실패로 다뤄야 한다(구체적인 코드의 의미는 여기서
    주장하지 않는다 — 그 의미는 live 테스트가 실제로 확인한 -101 케이스를
    바로 아래 별도 테스트가 고정한다)."""

    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(
            200, {"result_code": "-999", "message": "요청을 처리할 수 없습니다."}
        )
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert "요청을 처리할 수 없습니다" in result.failure_reason


@override_settings(**_ALIGO_SETTINGS)
def test_sms_adapter_ip_restriction_rejection_returns_failure_not_raise(recipient):
    """이 계정으로 live 테스트(tests/test_live_adapters.py)를 실제로 돌려서
    확인한 실제 벤더 응답을 그대로 고정한다 — 알리고에서 result_code=-101은
    "잔액 부족"이 아니라 "발신 IP가 콘솔에 등록돼 있지 않다"는 뜻이었다
    (#51 코드리뷰 지적 "참고" — 이전 버전은 이 코드를 잔액 부족으로
    잘못 라벨링했다)."""

    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(
            200, {"result_code": "-101", "message": "인증오류입니다.-IP"}
        )
        result = adapter.send(recipient=recipient, notification=_notification(recipient))

    assert result.success is False
    assert "IP" in result.failure_reason


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


# --- 잔액 조회: POST를 쓰고, 자격증명이 예외 메시지에 새지 않는다(#51 코드리뷰 지적 5) ---


@override_settings(**_ALIGO_SETTINGS)
def test_query_remaining_balance_uses_post_not_query_string():
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "SMS_CNT": 0, "LMS_CNT": 0})
        body = query_remaining_balance()

    assert body["result_code"] == "1"
    kwargs = mock_post.call_args.kwargs
    # GET params가 아니라 POST data로 실린다 — URL 쿼리스트링에 API 키가 없다.
    assert "params" not in kwargs
    assert kwargs["data"]["key"] == "test-api-key"


@override_settings(**_ALIGO_SETTINGS)
def test_query_remaining_balance_error_does_not_leak_credentials_in_the_exception():
    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(403, text="forbidden")
        with pytest.raises(AligoQueryError) as exc_info:
            query_remaining_balance()

    # 자격증명(API 키)이 예외 메시지 어디에도 없다 — raise_for_status()가
    # 쓰던 response.url에는 쿼리스트링으로 실린 키가 그대로 담겼었다.
    assert "test-api-key" not in str(exc_info.value)


# --- PAYOUT_AWAITS_YOU: 지급 대기 알림의 문자 본문 (#229) -------------------
#
# `payouts.notifications._notify_if_developer_turn`가 이미 context에
# `message`(payouts.progress.next_action_message의 결과)를 실어 보낸다 — 렌더러가
# 없어서 그 값이 벤더에 닿지 못하고 폴백("새 알림이 있습니다...")으로 나가던
# 것이 갭이다. 이 절은 렌더러가 그 값을 실제로 쓰는지만 본다 — Hold별 문구
# 자체(HoldKind → 문장 번역표)의 정확성은 `payouts.progress`가 이미 검증한다
# (`assert_covers_all_kinds`, 모듈 로드 시점 검사).


def _payout_awaits_you_notification(recipient, *, message: str | None, contest_title: str = "테스트 대회"):
    context: dict = {"contest_id": 1, "contest_title": contest_title}
    if message is not None:
        context["message"] = message
    return _notification(
        recipient, notification_type=NotificationType.PAYOUT_AWAITS_YOU, context=context
    )


@override_settings(**_ALIGO_SETTINGS)
def test_payout_awaits_you_sms_body_carries_the_hold_message(recipient):
    """AC: 지금 무엇이 막고 있고 무엇을 하면 되는지가 문자 본문에 실린다."""

    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()
    message = "세무 신고를 위해 주민등록번호를 제출해주세요."
    notification = _payout_awaits_you_notification(recipient, message=message)

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "message": "success"})
        result = adapter.send(recipient=recipient, notification=notification)

    assert result.success is True
    sent_body = mock_post.call_args.kwargs["data"]["msg"]
    assert message in sent_body
    # 폴백 문구로 새지 않았다.
    assert "새 알림이 있습니다" not in sent_body


@override_settings(**_ALIGO_SETTINGS)
def test_payout_awaits_you_different_hold_kinds_produce_different_sms_bodies(recipient):
    """AC: 막는 사유 네 가지가 각각 다른 문장으로 나간다."""

    identity_message = "세무 신고를 위해 주민등록번호를 제출해주세요."
    seller_auth_message = (
        "지급대행사(토스페이먼츠)가 보낸 본인인증 문자로 인증을 완료해주세요 — "
        "이미 본인확인을 하셨더라도 지급대행사 자체 의무라 다시 인증이 "
        "필요합니다. 인증이 끝나면 자동으로 다음 단계로 넘어갑니다."
    )

    identity_body = render_message(_payout_awaits_you_notification(recipient, message=identity_message))
    seller_auth_body = render_message(
        _payout_awaits_you_notification(recipient, message=seller_auth_message)
    )

    assert identity_message in identity_body
    assert seller_auth_message in seller_auth_body
    assert identity_body != seller_auth_body


@override_settings(**_ALIGO_SETTINGS)
def test_payout_awaits_you_long_hold_message_is_promoted_to_lms_without_truncating(recipient):
    """AC: 문구가 길어져 문자 한 통을 넘기면 기존 승격 규칙이 그대로 처리한다 —
    발송이 실패하지 않는다. `SELLER_AUTH`의 문구(#57, `payouts.progress`)가 실제로
    SMS 한도를 넘는다."""

    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()
    seller_auth_message = (
        "지급대행사(토스페이먼츠)가 보낸 본인인증 문자로 인증을 완료해주세요 — "
        "이미 본인확인을 하셨더라도 지급대행사 자체 의무라 다시 인증이 "
        "필요합니다. 인증이 끝나면 자동으로 다음 단계로 넘어갑니다."
    )
    notification = _payout_awaits_you_notification(recipient, message=seller_auth_message)
    assert _byte_length(render_message(notification)) > 90  # 전제 확인 — 실제로 SMS 한도를 넘는다.

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "message": "success"})
        result = adapter.send(recipient=recipient, notification=notification)

    assert result.success is True
    assert "LMS" in result.failure_reason and "승격" in result.failure_reason
    kwargs = mock_post.call_args.kwargs
    assert kwargs["data"]["msg_type"] == "LMS"
    assert seller_auth_message in kwargs["data"]["msg"]  # 잘리지 않았다.


@override_settings(**_ALIGO_SETTINGS)
def test_payout_awaits_you_falls_back_to_generic_message_when_context_has_no_message(recipient):
    """AC: 알 수 없는 사유가 오면(여기서는 context에 message가 아예 없는 경우로
    흉내낸다) 기존 폴백 문구로 나가고 발송 자체는 성공한다."""

    PhoneContact.objects.create(user=recipient, phone_number="01011112222")
    adapter = AligoSmsAdapter()
    notification = _payout_awaits_you_notification(recipient, message=None)

    with patch("notifications.adapters_aligo.requests.post") as mock_post:
        mock_post.return_value = _response(200, {"result_code": "1", "message": "success"})
        result = adapter.send(recipient=recipient, notification=notification)

    assert result.success is True
    sent_body = mock_post.call_args.kwargs["data"]["msg"]
    assert "새 알림이 있습니다" in sent_body


def test_payout_awaits_you_body_contains_no_personal_information(recipient):
    """AC: 본문에 이름·연락처·계좌 같은 개인정보가 들어가지 않는다.

    context 자체가 그런 값을 담지 않는다(`payouts.notifications._notify_if_developer_turn`
    — contest_id·message뿐) — 렌더러가 새로 담지 않는지만 확인한다."""

    message = "세무 신고를 위해 주민등록번호를 제출해주세요."
    body = render_message(_payout_awaits_you_notification(recipient, message=message))

    assert recipient.username not in body
    assert recipient.email not in body or recipient.email == ""


def test_other_notification_type_bodies_are_unaffected_by_the_new_branch():
    """AC: 다른 알림 종류의 본문은 바뀌지 않는다 — 회귀 고정."""

    notification = Notification(
        recipient_id=1,
        notification_type=NotificationType.APPEAL_RULED,
        is_transactional=True,
        is_promotional=False,
        context={"contest_title": "테스트 대회"},
    )
    assert render_message(notification) == "[Laurio] 제기하신 이의 심판이 완료됐습니다. laurio에서 결과를 확인하세요."
