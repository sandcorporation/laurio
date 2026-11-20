from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
    verbose_name = "결제 · Escrow 예치"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_payment_adapter_mode, BOOT_CHECK_TAG)

        # 참여자 0명 전액 환불 스캔 둘(#17, #140) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .services import REFUND_SCANS

        for spec in REFUND_SCANS:
            register_scan(spec)

        # 공모전 API 가 묻는 결제 질의 둘(#1086) — `contests.ports`
        from contests.ports import HAS_REFUNDED_PAYMENT, SYNC_REQUESTED_PAYMENT_PRIZE

        from .services import has_refunded_payment, sync_requested_payment_prize

        HAS_REFUNDED_PAYMENT.register(has_refunded_payment)
        SYNC_REQUESTED_PAYMENT_PRIZE.register(sync_requested_payment_prize)
