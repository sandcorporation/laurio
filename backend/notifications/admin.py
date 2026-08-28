from django.contrib import admin

from .models import Notification, NotificationDispatch, NotificationOptIn


class NotificationDispatchInline(admin.TabularInline):
    model = NotificationDispatch
    extra = 0
    readonly_fields = ["channel", "status", "attempted_at", "failure_reason"]
    can_delete = False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "recipient",
        "notification_type",
        "status",
        "is_transactional",
        "is_promotional",
        "created_at",
    ]
    list_filter = ["notification_type", "status", "is_transactional", "is_promotional"]
    inlines = [NotificationDispatchInline]


@admin.register(NotificationOptIn)
class NotificationOptInAdmin(admin.ModelAdmin):
    list_display = ["user", "notification_type", "opted_in", "created_at"]
    list_filter = ["notification_type", "opted_in"]
