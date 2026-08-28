from django.contrib import admin

from .models import Appeal


@admin.register(Appeal)
class AppealAdmin(admin.ModelAdmin):
    list_display = ("submission", "status", "correction_amount", "ruled_at", "created_at")
    list_filter = ("status",)
    readonly_fields = ("submission", "reason", "created_at")
