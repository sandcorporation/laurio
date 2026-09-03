from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
    verbose_name = "결제 · Escrow 예치"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_payment_adapter_mode)

        # 참여자 0명 전액 환불 스캔 둘(#17, #140) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .services import REFUND_SCANS

        for spec in REFUND_SCANS:
            register_scan(spec)
