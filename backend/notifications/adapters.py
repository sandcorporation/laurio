"""알림 채널 어댑터 (ADR-0007).

PG·LLM 과 같은 이유로 알림 채널도 인터페이스 뒤에 둔다. dev/test 는 전부 Fake 구현체에
바인딩되고(settings.NOTIFICATION_*_ADAPTER), 실제 카카오 알림톡·SMS/LMS 벤더 연동은
이 티켓 범위 밖이다.

Fake 구현체는 `settings.NOTIFICATION_FAKE_FAILING_CHANNELS` 에 자기 채널명이 있으면
"정상적으로 실패 응답을 돌려준다"를 흉내내고, `settings.NOTIFICATION_FAKE_RAISING_CHANNELS`
에 있으면 예외를 던져 "벤더 HTTP 클라이언트가 타임아웃/5xx로 뻗는다"는, 실제 장애에서
훨씬 흔한 경우를 흉내낸다. 후자는 notifications.services._attempt_dispatch 가 반드시
잡아서 다음 채널로 넘어가야 하는 경로를 테스트로 증명하는 데 쓴다. 둘 다
`override_settings` 로 순수 설정만으로 재현할 수 있다.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class ChannelSendResult:
    success: bool
    failure_reason: str = ""


@runtime_checkable
class NotificationChannelAdapter(Protocol):
    channel: str

    def send(self, *, recipient, notification) -> ChannelSendResult: ...


class FakeAdapterCrashed(Exception):
    """실제 벤더 클라이언트의 타임아웃/5xx 를 흉내내는, 성공/실패 응답조차 못 받는 상황."""


class _FakeAdapterBase:
    channel: str

    def send(self, *, recipient, notification) -> ChannelSendResult:
        if self.channel in settings.NOTIFICATION_FAKE_RAISING_CHANNELS:
            raise FakeAdapterCrashed(f"fake-{self.channel}-adapter-crashed")
        if self.channel in settings.NOTIFICATION_FAKE_FAILING_CHANNELS:
            return ChannelSendResult(
                success=False, failure_reason=f"fake-{self.channel}-forced-failure"
            )
        return ChannelSendResult(success=True)


class FakeAlimtalkAdapter(_FakeAdapterBase):
    channel = "alimtalk"


class FakeSmsAdapter(_FakeAdapterBase):
    channel = "sms"


class FakeLmsAdapter(_FakeAdapterBase):
    channel = "lms"


def get_alimtalk_adapter() -> NotificationChannelAdapter:
    return import_string(settings.NOTIFICATION_ALIMTALK_ADAPTER)()


def get_sms_adapter() -> NotificationChannelAdapter:
    return import_string(settings.NOTIFICATION_SMS_ADAPTER)()


def get_lms_adapter() -> NotificationChannelAdapter:
    return import_string(settings.NOTIFICATION_LMS_ADAPTER)()


# 알림톡 우선, 실패 시 SMS, 그마저 실패하면 LMS(ADR-0009 "실패 시 SMS/LMS로 대체발송").
CHANNEL_FALLBACK_CHAIN = [
    ("alimtalk", get_alimtalk_adapter),
    ("sms", get_sms_adapter),
    ("lms", get_lms_adapter),
]
