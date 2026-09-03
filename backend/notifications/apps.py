from django.apps import AppConfig
from django.core.checks import Error, register


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        register(check_notification_type_flags_cover_all_types)

        # #89: 알림 채널 셋(알림톡/SMS/LMS)도 나머지 여섯 어댑터와 같은 부팅
        # 가드를 받는다 — import·인스턴스화·계약 충족을 실제로 검증한다.
        from . import checks

        register(checks.check_notification_alimtalk_adapter_mode)
        register(checks.check_notification_sms_adapter_mode)
        register(checks.check_notification_lms_adapter_mode)

        # Contest 라이프사이클 통지 스캔 다섯(#19, #138) — 등록부에 올라 각자 자기 예산으로 돈다.
        from core.scans import register_scan

        from .lifecycle import LIFECYCLE_SCANS
        from .services import NOTIFICATION_SCANS

        # 야간 큐 발송·stuck-QUEUED 재선점(#10, #139)도 등록부 항목이다.
        for spec in (*NOTIFICATION_SCANS, *LIFECYCLE_SCANS):
            register_scan(spec)


def check_notification_type_flags_cover_all_types(app_configs, **kwargs):
    """NotificationType 에 값을 추가하고 NOTIFICATION_TYPE_FLAGS 를 깜빡하면 부팅을 막는다.

    짝이 안 맞으면 GET /api/internal/notifications/types/ 와 알림 생성이 둘 다
    KeyError -> 500 이 난다(#18 리뷰 지적). `manage.py check` 는 CI가 이미
    `--fail-level WARNING` 으로 돌리고 있어, 이 체크가 하나라도 걸리면 배포 전에
    잡힌다.
    """

    from .models import NOTIFICATION_TYPE_FLAGS, NotificationType

    missing = [value for value in NotificationType.values if value not in NOTIFICATION_TYPE_FLAGS]
    if not missing:
        return []

    return [
        Error(
            f"NOTIFICATION_TYPE_FLAGS 에 다음 NotificationType 의 거래성/광고성 플래그가 "
            f"없다: {missing}",
            hint=(
                "notifications/models.py 의 NOTIFICATION_TYPE_FLAGS 에 "
                "{'is_transactional': ..., 'is_promotional': ...} 항목을 추가하라."
            ),
            id="notifications.E001",
        )
    ]
