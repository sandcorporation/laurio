from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
    verbose_name = "결제 · Escrow 예치"

    def ready(self) -> None:
        from django.core.checks import register

        from . import checks

        register(checks.check_payment_adapter_mode)
