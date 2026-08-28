from django.contrib import admin

from .models import Award


@admin.register(Award)
class AwardAdmin(admin.ModelAdmin):
    list_display = ("id", "contest", "submission", "awarded_at", "created_at")
    readonly_fields = ("created_at",)
