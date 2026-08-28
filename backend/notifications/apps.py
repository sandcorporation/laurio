from django.apps import AppConfig
from django.core.checks import Error, register


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        register(check_notification_type_flags_cover_all_types)


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
