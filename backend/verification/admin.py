from django.contrib import admin

from .models import Verification


@admin.register(Verification)
class VerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "verified_at", "created_at")
    list_filter = ("status",)
    readonly_fields = (
        "real_name_encrypted",
        "birth_date_encrypted",
        "ci_encrypted",
        "ci_hash",
        "di_encrypted",
    )
