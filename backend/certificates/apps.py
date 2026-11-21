from __future__ import annotations

from django.apps import AppConfig


class CertificatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "certificates"
    verbose_name = "Certificate · 상장"

    def ready(self) -> None:
        # 받는 사람이 탈퇴하면 확인 페이지를 닫고 이름을 지운다(#1130, 스펙 #1071 G6).
        from accounts.signals import user_withdrawn

        from .withdrawal import hide_on_withdrawal

        user_withdrawn.connect(hide_on_withdrawal, dispatch_uid="certificates-recipient-withdrawal")
