"""부팅 시점 어댑터 검증 (#89, #51, ADR-0007).

`NOTIFICATION_ALIMTALK_ADAPTER`/`NOTIFICATION_SMS_ADAPTER`/`NOTIFICATION_LMS_ADAPTER`가
배포 환경에서 "fake"도 아니고 실제로 쓸 수도 없으면(임포트 실패·인스턴스화
실패·`NotificationChannelAdapter` 계약 불충족) 부팅 자체를 거부한다.
`verification.checks.check_verification_adapter_mode`와 같은 원칙이다.

세 값은 처음부터 "fake"라는 별도 별칭이 아니라 dotted path만 쓰고(기본값 자체가
`notifications.adapters.Fake*Adapter`), `config.settings`가 그 dotted path의
클래스명이 `Fake`로 시작하는지로 별도 가드를 이미 두고 있다(#89 이전부터).
그 가드는 여기서 건드리지 않는다 — 이 모듈이 넓히는 것은 "그 값이 실제로
import·인스턴스화되고 계약을 만족하는가"라는, 지금까지 알림 채널만 비어 있던
바로 그 검증이다(#83이 verification/payment/payout/scoring/contests에 이미
적용한 것과 같은 검증을 세 값에 마저 적용한다).

**세 값이 전부 같은 `NotificationChannelAdapter` Protocol을 쓴다는 사실 자체가
새 구멍이다(#51 코드리뷰 지적 8).** `core.adapters.check_adapter_mode`는 구조적
계약(메서드·속성의 존재)만 보므로, `NOTIFICATION_SMS_ADAPTER`가 실수로
`AligoLmsAdapter`(channel="lms")를 가리켜도 깨끗이 통과한다 — SMS 요금으로
전부 LMS를 보내면서 `NotificationDispatch.channel`에는 "sms"로 남는, #89가
막으려던 것과 같은 종류의 "설정이 가리키는 척하지만 실제로는 다른 일을 한다"
사고다. `core/adapters.py`는 이 티켓의 대상이 아니므로(범위를 넓히는
`check_adapter_mode` 자체를 바꾸지 않는다) 이 모듈 안에서 별도로
`instance.channel`이 그 설정이 기대하는 값과 같은지 추가로 확인한다.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error
from django.utils.module_loading import import_string

from core.adapters import check_adapter_mode

from .adapters import NotificationChannelAdapter


def _check_channel_matches_setting(setting_name: str, expected_channel: str) -> list[Error]:
    """`setting_name`이 가리키는 어댑터의 `channel`이 `expected_channel`과 같은지 확인한다.

    import·인스턴스화 실패는 `check_adapter_mode`(core.E001/E002)가 이미
    보고하므로 여기서는 조용히 넘어간다 — 같은 실패를 두 번 보고하지 않는다.
    """

    if not settings.IS_DEPLOYED_ENVIRONMENT:
        return []

    value = getattr(settings, setting_name, "")
    if value == "fake":
        return []

    try:
        instance = import_string(value)()
    except Exception:  # noqa: BLE001 - check_adapter_mode가 이미 이 실패를 보고한다.
        return []

    channel = getattr(instance, "channel", None)
    if channel == expected_channel:
        return []

    return [
        Error(
            f"{setting_name}={value!r} 가 가리키는 어댑터의 channel이 {channel!r}이다 "
            f"— {expected_channel!r}이어야 한다.",
            hint=(
                f"{setting_name}에는 channel == {expected_channel!r}인 "
                "NotificationChannelAdapter만 지정해야 한다. 예: "
                "NOTIFICATION_SMS_ADAPTER에 channel='lms'인 어댑터를 가리키면 "
                "SMS 요금으로 LMS를 보내면서 발송 이력에는 channel='sms'로 "
                "남는 사고가 난다."
            ),
            id="notifications.E002",
        )
    ]


def check_notification_alimtalk_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="NOTIFICATION_ALIMTALK_ADAPTER", protocol=NotificationChannelAdapter
    ) + _check_channel_matches_setting("NOTIFICATION_ALIMTALK_ADAPTER", "alimtalk")


def check_notification_sms_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="NOTIFICATION_SMS_ADAPTER", protocol=NotificationChannelAdapter
    ) + _check_channel_matches_setting("NOTIFICATION_SMS_ADAPTER", "sms")


def check_notification_lms_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="NOTIFICATION_LMS_ADAPTER", protocol=NotificationChannelAdapter
    ) + _check_channel_matches_setting("NOTIFICATION_LMS_ADAPTER", "lms")
