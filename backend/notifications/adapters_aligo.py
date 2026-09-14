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
# 야간 드레인 스캔(notifications.services 의 notification-dispatch-deferred 스캔, #51
# 코드리뷰 지적 6)이 한 요청 안에서 여러 건을 순차 처리한다 — 채널 하나가
# 오래 물고 늘어지면 그 시간이 통째로 스캔 예산을 잡아먹는다.
#
# 스칼라 값 하나(예: 5)를 주면 requests가 그 값을 connect와 read 각각에
# 독립적으로 적용한다 — 연결은 되는데 응답만 느린(slow-drip) 벤더를 만나면
# 실제 최대 대기 시간은 5초가 아니라 최대 10초가 된다(#51 2차 코드리뷰
# 지적 3). "채널 하나 최대 5초 × 3채널 = 15초, 스캔 예산 12초 + 15초 =
# 27초 < gunicorn/Celery 30초" 라는 계산은 채널 하나의 총 대기 시간이
# 5초라는 전제 위에 있었는데, 스칼라 timeout으로는 그 전제가 성립하지
# 않았다. `(connect, read)` 튜플로 각 단계를 명시적으로 나눠, 합쳐서 정확히
# 5초를 넘지 않게 한다 — 연결 자체가 막힌 경우(2초)와 연결은 됐지만 응답이
# 느린 경우(3초)를 구분해서 잡는다.
_CONNECT_TIMEOUT_SECONDS = 2
_READ_TIMEOUT_SECONDS = 3
_TIMEOUT_SECONDS = (_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS)

# 대략적인 EUC-KR(CP949) 계열 SMS 바이트 한도 — 이 값을 넘으면 벤더가 SMS로는
# 아예 접수하지 않거나(우리가 원치 않는 잘림) 임의로 잘라 보낼 수 있다. 그래서
# 이 한도를 넘는 순간 처음부터 LMS로 보낸다.
_SMS_BYTE_LIMIT = 90

# LMS/MMS는 벤더가 제목을 요구한다(본문과 별개 필드) — 45바이트 이내의 고정
# 문구를 쓴다. 실제 내용은 title이 아니라 msg에 전부 담기므로 이 값이 잘려도
# 정보 손실이 없다.
_DEFAULT_TITLE = "Codemit 알림"


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

    UTF-8로 통째로 세면 한글 한 글자가 3바이트라 실제 벤더 판정보다 훨씬 빨리
    한도를 넘긴 것으로 오판한다 — 그래서 CP949(EUC-KR의 상위 호환, 현대 한글
    음절을 전부 2바이트로 인코딩한다)를 기준으로 삼는다.

    다만 문자 전체를 한 번에 ``text.encode("cp949", errors="replace")``로
    인코딩하면, CP949로 표현할 수 없는 문자(이모지, KS X 1001 밖 한자, 그리고
    이 저장소가 실제 문구에 쓰는 em dash "—")가 전부 "?" 1바이트로 치환돼
    실제보다 훨씬 짧게 계산된다(#51 코드리뷰 지적 2 — 이모지 15개짜리 제목이
    추정 65바이트로 나왔지만 실제 페이로드는 123바이트였다). 그 결과 SMS
    한도를 실제로는 넘는 메시지가 SMS로 잘못 분류돼 벤더가 잘라 보내거나
    접수를 거절할 수 있다 — "돈 정보를 담은 문장이 중간에서 끊기면 안 된다"는
    AC(#51)가 그대로 깨진다.

    그래서 문자 하나하나를 시도한다 — CP949로 인코딩되면 그 결과(1~2바이트)를,
    안 되면 실제로 전송될 때 쓰이는 UTF-8 인코딩 기준 바이트 수(그 문자의
    진짜 크기)를 더한다. 순수 한글·영문 문구는 기존과 똑같이 정확하고, 특수
    문자가 섞여도 더는 과소평가하지 않는다.
    """

    total = 0
    for char in text:
        try:
            total += len(char.encode("cp949"))
        except UnicodeEncodeError:
            total += len(char.encode("utf-8"))
    return total


def _select_msg_type(message: str) -> str:
    return "SMS" if _byte_length(message) <= _SMS_BYTE_LIMIT else "LMS"


def _recipient_phone_number(recipient) -> str | None:
    """`accounts.models.PhoneContact`에 등록된 번호를 찾는다(#51).

    없으면 None — Django의 역방향 OneToOne 접근자는 행이 없을 때
    `RelatedObjectDoesNotExist`(AttributeError의 하위 타입)를 던지므로
    `getattr(..., default)`가 그대로 동작한다.

    `PhoneContact.phone_number` setter(accounts.models)가 저장 시점에 이미
    `accounts.phone.normalize_phone_number`로 정규화·검증하므로 여기서 다시
    걸릴 값은 정상적으로는 없다. 그래도 알리고의 `receiver` 파라미터가
    콤마로 여러 수신자를 지정하는 필드라는 사실 자체가 위험하므로(#51
    코드리뷰 지적 4), 벤더를 호출하는 마지막 지점에서 한 번 더 방어한다 —
    저장 시점 검증을 우회하는 어떤 경로(레거시 데이터, 직접 DB 조작 등)가
    생겨도 콤마가 섞인 값이 그대로 벤더에 나가는 일은 없다.
    """

    contact = getattr(recipient, "phone_contact", None)
    if contact is None:
        return None
    phone = contact.phone_number
    if not phone:
        return None
    if "," in phone:
        logger.error(
            "PhoneContact(user_id=%s)의 번호에 콤마가 포함돼 있다 — 알리고 "
            "receiver 파라미터는 콤마를 다중 수신자 구분자로 해석하므로 "
            "발송하지 않는다.",
            getattr(recipient, "id", None),
        )
        return None
    return phone


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


# SMS 슬롯이 실제로는 LMS로 승격돼 나갔을 때 이력에 남기는 문구(#51 3차
# 코드리뷰 지적 6). notifications.checks의 notifications.E002(#89/#51)는
# "이 슬롯에 바인딩된 어댑터의 channel 속성이 슬롯과 같은가"만 부팅 시점에
# 확인한다 — AligoSmsAdapter는 channel="sms"이므로 그 검사를 정상적으로
# 통과하지만, 메시지 길이에 따라 매 발송마다 벤더에는 SMS로도 LMS로도 나갈
# 수 있다는 사실은 바인딩 시점 검사로는 볼 수 없다. 그래서 발송 시점에
# 이력으로 남긴다.
_LMS_PROMOTION_NOTE = "메시지가 SMS 한도를 넘어 LMS로 승격되어 발송됨(과금은 LMS 기준)"


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
        result = _post_to_aligo(
            self._credentials, receiver=phone, msg=message, msg_type=msg_type, title=title
        )

        if msg_type != "LMS":
            return result

        # 승격이 실제로 일어났다 — NotificationDispatch.channel은 그대로
        # "sms"로 남긴다(재시도 판단에 쓰이는 슬롯 식별자이기 때문이다,
        # notifications.services._attempt_dispatch 참고). 대신 이 사실을
        # failure_reason에 남긴다(성공이어도) — ChannelSendResult 독스트링
        # 참고.
        if result.success:
            return ChannelSendResult(success=True, failure_reason=_LMS_PROMOTION_NOTE)
        return ChannelSendResult(
            success=False,
            failure_reason=f"{_LMS_PROMOTION_NOTE} — {result.failure_reason}"[:255],
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


class AligoQueryError(Exception):
    """잔액 조회가 실패했을 때(#51 코드리뷰 지적 5)."""


def query_remaining_balance(credentials: _AligoCredentials | None = None) -> dict:
    """잔여 발송 건수를 조회한다 — 실제 발송 없이 자격증명이 유효한지 확인하는
    용도(#51 live 테스트). 잔액이 0이어도(계정 잔액 0인 것이 이 프로젝트의 현재
    상태다) 이 호출 자체는 성공한다 — 조회는 과금되지 않는다.

    GET이 아니라 POST(form body)로 보낸다(#51 코드리뷰 지적 5) — GET은 `key`가
    쿼리스트링에 그대로 실려, `response.raise_for_status()`가 던지는
    `requests.HTTPError`의 메시지에 `response.url` 전체(쿼리스트링 포함)가
    담겨 그대로 로그로 새 나갈 수 있었다. 알리고 `/remain/`은 POST form도
    받는 엔드포인트라 body로 옮기는 것만으로 이 경로 자체가 없어진다. 그래도
    `raise_for_status()`를 쓰지 않고 직접 예외를 만든다 — 그 메서드가 항상
    `response.url`을 메시지에 포함시키는 구현이라, 다른 경로로 URL에 자격증명이
    실리는 변경이 나중에 들어와도 이 함수만은 자격증명을 예외 메시지에 담지
    않는다는 것을 구조적으로 보장한다.
    """

    credentials = credentials or _read_credentials()
    response = requests.post(
        _REMAIN_URL,
        data={"key": credentials.api_key, "user_id": credentials.user_id},
        timeout=_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        logger.warning("Aligo 잔액 조회가 HTTP %s를 응답했다: %s", response.status_code, response.text)
        raise AligoQueryError(f"Aligo 잔액 조회가 HTTP {response.status_code}를 응답했다.")
    return response.json()
