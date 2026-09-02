"""부팅 시점 어댑터 검증 (#89, ADR-0007).

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
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .adapters import NotificationChannelAdapter


def check_notification_alimtalk_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="NOTIFICATION_ALIMTALK_ADAPTER", protocol=NotificationChannelAdapter
    )


def check_notification_sms_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="NOTIFICATION_SMS_ADAPTER", protocol=NotificationChannelAdapter
    )


def check_notification_lms_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(
        setting_name="NOTIFICATION_LMS_ADAPTER", protocol=NotificationChannelAdapter
    )
