from django.contrib import admin

from .models import Payout, PayoutWebhookDelivery, TaxIdentity


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    """지급 대사용 — 운영자가 확정·실패·신원 대기 상태를 한눈에 확인한다."""

    list_display = (
        "id",
        "handover",
        "idempotency_key",
        "status",
        "prize_amount",
        "platform_fee_amount",
        "withholding_tax_amount",
        "net_amount",
        "journal_entry_id",
    )
    list_filter = ("status",)
    readonly_fields = ("idempotency_key", "created_at", "updated_at")


@admin.register(PayoutWebhookDelivery)
class PayoutWebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("id", "payout", "webhook_id", "idempotency_key", "event_status", "received_at")
    readonly_fields = ("received_at",)


class ReadOnlyAdmin(admin.ModelAdmin):
    """주민등록번호는 암호화되어 있어도 admin에서 수정·삭제할 이유가 없다
    (contests.admin.ReadOnlyAdmin과 같은 이유 — 빈 필수 FK로 INSERT가 나가는
    사고까지 막는다)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TaxIdentity)
class TaxIdentityAdmin(ReadOnlyAdmin):
    """암호문 필드만 노출한다 — admin 화면에서도 평문 주민등록번호를 복호화해
    보여주지 않는다."""

    list_display = ("id", "payout", "created_at")
    readonly_fields = ("payout", "resident_registration_number_encrypted", "created_at")
