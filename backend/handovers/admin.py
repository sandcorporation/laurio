from django.contrib import admin

from .models import BuildAsset, Handover


@admin.register(Handover)
class HandoverAdmin(admin.ModelAdmin):
    """Escrow 해제 대사용 — 운영자가 Award부터 해제까지의 흐름을 확인한다."""

    list_display = (
        "id",
        "award",
        "status",
        "release_deadline_at",
        "released_via",
        "released_at",
        "escrow_release_journal_entry_id",
    )
    list_filter = ("status", "released_via")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BuildAsset)
class BuildAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "submission", "kind", "label", "created_at")
    list_filter = ("kind",)
    readonly_fields = ("created_at",)
