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


_REQUIRED_FLAG_KEYS = ("is_transactional", "is_promotional", "is_quiet_hours_exempt")


def check_notification_type_flags_cover_all_types(app_configs, **kwargs):
    """NotificationType 에 값을 추가하고 NOTIFICATION_TYPE_FLAGS 를 깜빡하면 부팅을 막는다.

    짝이 안 맞으면 GET /api/internal/notifications/types/ 와 알림 생성이 둘 다
    KeyError -> 500 이 난다(#18 리뷰 지적). `manage.py check` 는 CI가 이미
    `--fail-level WARNING` 으로 돌리고 있어, 이 체크가 하나라도 걸리면 배포 전에
    잡힌다.

    **세 플래그 모두를 검사한다**(#169) — `is_quiet_hours_exempt` 가 야간 유예의
    예외를 여는 유일한 자리이므로, 새 유형이 이 키 없이 등록되면(그래서 조용히
    "예외 아님"으로 새지 않고) 부팅 시점에 드러나야 한다.
    """

    from .models import NOTIFICATION_TYPE_FLAGS, NotificationType

    missing_types = [
        value for value in NotificationType.values if value not in NOTIFICATION_TYPE_FLAGS
    ]
    incomplete = [
        value
        for value in NotificationType.values
        if value in NOTIFICATION_TYPE_FLAGS
        and any(key not in NOTIFICATION_TYPE_FLAGS[value] for key in _REQUIRED_FLAG_KEYS)
    ]
    if not missing_types and not incomplete:
        return []

    errors = []
    if missing_types:
        errors.append(
            Error(
                f"NOTIFICATION_TYPE_FLAGS 에 다음 NotificationType 의 플래그가 아예 없다: "
                f"{missing_types}",
                hint=(
                    "notifications/models.py 의 NOTIFICATION_TYPE_FLAGS 에 "
                    "{'is_transactional': ..., 'is_promotional': ..., "
                    "'is_quiet_hours_exempt': ...} 항목을 추가하라."
                ),
                id="notifications.E001",
            )
        )
    if incomplete:
        errors.append(
            Error(
                f"NOTIFICATION_TYPE_FLAGS 에 다음 NotificationType 의 플래그 셋이 "
                f"{_REQUIRED_FLAG_KEYS} 를 전부 갖지 않는다: {incomplete}",
                hint="세 키를 모두 채워라 — 특히 is_quiet_hours_exempt(#169).",
                id="notifications.E002",
            )
        )
    return errors
