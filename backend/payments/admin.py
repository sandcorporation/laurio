from django.contrib import admin

from .models import Payment, WebhookDelivery


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "order_id",
        "contest",
        "status",
        "prize_amount",
        "listing_fee_amount",
        "journal_entry_id",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("order_id", "contest__title")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("webhook_id", "order_id", "event_status", "received_at", "payment")
    search_fields = ("webhook_id", "order_id")
    readonly_fields = [f.name for f in WebhookDelivery._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
