"""알리고(Aligo) SMS/LMS 실물 어댑터 + 알림톡 자리 (#51, ADR-0007, ADR-0009).

`notifications.adapters.NotificationChannelAdapter` 계약만 만족시킨다 — Fake
어댑터와 나란히 놓고 봐야 이해되는 코드다.

- **알림톡(`AligoAlimtalkAdapter`)은 벤더를 전혀 호출하지 않는다.** 사업자등록·
  카카오 채널 개설·템플릿 사전심사가 끝나기 전까지는 항상 실패를 돌려줘
  `CHANNEL_FALLBACK_CHAIN`(alimtalk → sms → lms)이 SMS로 대체발송하게 한다
  (ADR-0009 "실패 시 SMS/LMS로 대체발송"). 자리를 비워두지 않는 이유는
  `NOTIFICATION_ALIMTALK_ADAPTER`가 배포 가드(ADR-0007, #89)의 대상이라 dotted
  path가 반드시 실제로 존재해야 하기 때문이다.
- **SMS는 길다고 자르지 않는다.** `AligoSmsAdapter.send`는 렌더링된 문구의
  바이트 길이가 SMS 한도(대략 90바이트, EUC-KR 계열 기준)를 넘으면 스스로
  LMS 타입으로 벤더에 요청한다 — 돈 정보를 담은 문장이 중간에서 끊기면 안
  된다는 AC를 어댑터 층에서 지킨다.
- **수신자에게 등록된 전화번호가 없으면 벤더를 호출하지 않고 즉시 실패를
  돌려준다.** ADR-0009가 말하는 "연락처를 방치"한 경우의 가장 흔한 모양이다 —
  이것도 `NotificationDispatch`에 실패 사유로 남는다.
- **벤더가 오류를 반환하거나 응답하지 않아도 예외를 던지지 않는다.** 항상
  `ChannelSendResult(success=False, ...)`로 돌려준다 — `_attempt_dispatch`가
  예외도 잡긴 하지만, 여기서 명시적으로 처리하면 실패 사유가 훨씬 구체적으로
  남는다(ADR-0009: 채널별 실패 사유 보존).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .adapters import ChannelSendResult
from .rendering import render_message

logger = logging.getLogger(__name__)

_SEND_URL = "https://apis.aligo.in/send/"
_REMAIN_URL = "https://apis.aligo.in/remain/"
_TIMEOUT_SECONDS = 10

# 대략적인 EUC-KR(CP949) 계열 SMS 바이트 한도 — 이 값을 넘으면 벤더가 SMS로는
# 아예 접수하지 않거나(우리가 원치 않는 잘림) 임의로 잘라 보낼 수 있다. 그래서
# 이 한도를 넘는 순간 처음부터 LMS로 보낸다.
_SMS_BYTE_LIMIT = 90

# LMS/MMS는 벤더가 제목을 요구한다(본문과 별개 필드) — 45바이트 이내의 고정
# 문구를 쓴다. 실제 내용은 title이 아니라 msg에 전부 담기므로 이 값이 잘려도
# 정보 손실이 없다.
_DEFAULT_TITLE = "Laurio 알림"


class AligoCredentialsError(ImproperlyConfigured):
    """Aligo 자격증명이 비어 있을 때."""


@dataclass(frozen=True)
class _AligoCredentials:
    api_key: str
    user_id: str
    sender: str


def _read_credentials() -> _AligoCredentials:
    api_key = settings.ALIGO_API_KEY
    user_id = settings.ALIGO_USER_ID
    sender = settings.ALIGO_SENDER_PHONE_NUMBER

    missing = [
        name
        for name, value in (
            ("ALIGO_API_KEY", api_key),
            ("ALIGO_USER_ID", user_id),
            ("ALIGO_SENDER_PHONE_NUMBER", sender),
        )
        if not value
    ]
    if missing:
        raise AligoCredentialsError(
            f"{', '.join(missing)} 가 비어 있다 — NOTIFICATION_SMS_ADAPTER/"
            "NOTIFICATION_LMS_ADAPTER를 알리고 실물 어댑터로 켜려면 환경에 세 값을 "
            "반드시 주입해야 한다(#51)."
        )
    return _AligoCredentials(api_key=api_key, user_id=user_id, sender=sender)


def _byte_length(text: str) -> int:
    """Aligo SMS/LMS 판정 기준(EUC-KR 계열 바이트 수)을 근사한다.

    UTF-8로 세면 한글 한 글자가 3바이트라 실제 벤더 판정보다 훨씬 빨리 한도를
    넘긴 것으로 오판한다. CP949는 EUC-KR의 상위 호환이라 현대 한글 음절을 전부
    2바이트로 인코딩한다. CP949로 표현할 수 없는 문자(이모지 등)는 "?"로
    치환한다 — 길이 판정이 예외로 죽으면 안 된다.
    """

    return len(text.encode("cp949", errors="replace"))


def _select_msg_type(message: str) -> str:
    return "SMS" if _byte_length(message) <= _SMS_BYTE_LIMIT else "LMS"


def _recipient_phone_number(recipient) -> str | None:
    """`accounts.models.PhoneContact`에 등록된 번호를 찾는다(#51).

    없으면 None — Django의 역방향 OneToOne 접근자는 행이 없을 때
    `RelatedObjectDoesNotExist`(AttributeError의 하위 타입)를 던지므로
    `getattr(..., default)`가 그대로 동작한다.
    """

    contact = getattr(recipient, "phone_contact", None)
    if contact is None:
        return None
    return contact.phone_number or None


def _post_to_aligo(
    credentials: _AligoCredentials,
    *,
    receiver: str,
    msg: str,
    msg_type: str,
    title: str | None = None,
) -> ChannelSendResult:
    payload = {
        "key": credentials.api_key,
        "user_id": credentials.user_id,
        "sender": credentials.sender,
        "receiver": receiver,
        "msg": msg,
        "msg_type": msg_type,
    }
    if title:
        payload["title"] = title

    try:
        response = requests.post(_SEND_URL, data=payload, timeout=_TIMEOUT_SECONDS)
    except requests.Timeout as exc:
        logger.warning("Aligo 발송 요청이 타임아웃됐다: %r", exc)
        return ChannelSendResult(success=False, failure_reason=f"aligo-timeout: {exc}"[:255])
    except requests.RequestException as exc:
        logger.warning("Aligo 발송 요청이 네트워크 오류로 실패했다: %r", exc)
        return ChannelSendResult(success=False, failure_reason=f"aligo-network-error: {exc}"[:255])

    if response.status_code >= 400:
        logger.warning(
            "Aligo가 HTTP %s를 응답했다: %s", response.status_code, response.text
        )
        return ChannelSendResult(
            success=False,
            failure_reason=f"aligo-http-{response.status_code}: {response.text}"[:255],
        )

    try:
        body = response.json()
    except ValueError:
        return ChannelSendResult(
            success=False, failure_reason=f"aligo-non-json-response: {response.text}"[:255]
        )

    result_code = body.get("result_code")
    if str(result_code) == "1":
        return ChannelSendResult(success=True)

    message = body.get("message") or "알 수 없는 오류"
    logger.info("Aligo가 발송을 거절했다(result_code=%s): %s", result_code, message)
    return ChannelSendResult(
        success=False, failure_reason=f"aligo-rejected(code={result_code}): {message}"[:255]
    )


class AligoSmsAdapter:
    """`NOTIFICATION_SMS_ADAPTER=notifications.adapters_aligo.AligoSmsAdapter`로 켠다."""

    channel = "sms"

    def __init__(self) -> None:
        self._credentials = _read_credentials()

    def send(self, *, recipient, notification) -> ChannelSendResult:
        phone = _recipient_phone_number(recipient)
        if not phone:
            return ChannelSendResult(
                success=False, failure_reason="수신자에게 등록된 전화번호가 없다"
            )

        message = render_message(notification)
        msg_type = _select_msg_type(message)
        title = _DEFAULT_TITLE if msg_type == "LMS" else None
        return _post_to_aligo(
            self._credentials, receiver=phone, msg=message, msg_type=msg_type, title=title
        )


class AligoLmsAdapter:
    """`NOTIFICATION_LMS_ADAPTER=notifications.adapters_aligo.AligoLmsAdapter`로 켠다.

    항상 LMS로 보낸다 — `CHANNEL_FALLBACK_CHAIN`에서 SMS 다음 순서로만 쓰이는
    최종 대체발송 채널이다.
    """

    channel = "lms"

    def __init__(self) -> None:
        self._credentials = _read_credentials()

    def send(self, *, recipient, notification) -> ChannelSendResult:
        phone = _recipient_phone_number(recipient)
        if not phone:
            return ChannelSendResult(
                success=False, failure_reason="수신자에게 등록된 전화번호가 없다"
            )

        message = render_message(notification)
        return _post_to_aligo(
            self._credentials,
            receiver=phone,
            msg=message,
            msg_type="LMS",
            title=_DEFAULT_TITLE,
        )


class AligoAlimtalkAdapter:
    """`NOTIFICATION_ALIMTALK_ADAPTER=notifications.adapters_aligo.AligoAlimtalkAdapter`로 켠다.

    사업자등록·카카오 채널 개설·템플릿 사전심사가 끝나기 전까지는 벤더를
    전혀 호출하지 않고 항상 실패를 돌려준다 — `CHANNEL_FALLBACK_CHAIN`이
    SMS/LMS로 대체발송하게 하는 것이 ADR-0009가 설계한 폴백 그대로다. 승인이
    난 뒤에는 이 클래스의 `send`만 실제 카카오 알림톡 API 호출로 바꾸면 되고,
    호출부(`notifications.services`)는 전혀 바뀌지 않는다.
    """

    channel = "alimtalk"

    def __init__(self) -> None:
        # 아직 벤더를 호출하지 않지만, 자격증명 자체는 미리 검증해 둔다 —
        # 승인이 나서 실제 발송으로 바뀌는 시점에 자격증명 문제까지 새로
        # 드러나지 않게 하기 위해서다. 배포 가드(core.adapters.check_adapter_mode,
        # #89)가 이 생성 실패를 core.E002로 잡는다.
        _read_credentials()

    def send(self, *, recipient, notification) -> ChannelSendResult:
        del recipient, notification
        return ChannelSendResult(
            success=False,
            failure_reason="알림톡 템플릿 사전심사 대기 중 — SMS/LMS로 대체발송한다(ADR-0009)",
        )


def query_remaining_balance(credentials: _AligoCredentials | None = None) -> dict:
    """잔여 발송 건수를 조회한다 — 실제 발송 없이 자격증명이 유효한지 확인하는
    용도(#51 live 테스트). 잔액이 0이어도(계정 잔액 0인 것이 이 프로젝트의 현재
    상태다) 이 호출 자체는 성공한다 — 조회는 과금되지 않는다.
    """

    credentials = credentials or _read_credentials()
    response = requests.get(
        _REMAIN_URL,
        params={"key": credentials.api_key, "user_id": credentials.user_id},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
