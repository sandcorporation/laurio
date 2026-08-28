"""결제 admin — 조회 전용.

`Payment`/`WebhookDelivery`는 결제 API·웹훅이 관리하는 시스템 레코드다. admin에서
직접 추가하면(다른 필드는 전부 readonly라도) `has_add_permission`을 막지 않는 한
"모든 필드가 readonly인 추가 폼"이 그대로 남아 NOT NULL 제약 위반으로 500이
난다(ledger.admin의 `ReadOnlyAppendOnlyAdmin`과 같은 이유로 이 프로젝트 관례를
따른다) — 추가·수정·삭제를 전부 막고 감사를 위한 열람만 허용한다.
"""

from django.contrib import admin

from .models import Payment, WebhookDelivery


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
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


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(ReadOnlyAdmin):
    list_display = ("webhook_id", "order_id", "event_status", "received_at", "payment")
    search_fields = ("webhook_id", "order_id")
    readonly_fields = [f.name for f in WebhookDelivery._meta.fields]
