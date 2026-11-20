from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Authentication · 계정"

    # 신원 파기 스캔 둘(#102, #138)은 #1086 에서 `verification.apps` 로 옮겼다 — 공유층이 본인확인 기록을 읽지 않는다.

    def ready(self) -> None:
        # 탈퇴·휴면이면 연결된 앱 허락을 그 자리에서 끊는다(ADR-0052, #870). 끊는 일은 `core` 가, 시그널은 이 앱이
        # 가진다 — 연결을 여기서 해야 `core` 가 `accounts` 를 import 하지 않는다(#1086). dispatch_uid 는 처음 그대로다.
        from core.connected_app_signals import revoke_on_dormancy, revoke_on_withdrawal

        from .signals import user_became_dormant, user_withdrawn

        user_withdrawn.connect(revoke_on_withdrawal, dispatch_uid="classroom-connected-app-withdrawal")
        user_became_dormant.connect(revoke_on_dormancy, dispatch_uid="classroom-connected-app-dormancy")
