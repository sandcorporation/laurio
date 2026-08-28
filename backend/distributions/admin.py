from django.contrib import admin

from .models import Distribution, DistributionCutline, DistributionShare


@admin.register(DistributionCutline)
class DistributionCutlineAdmin(admin.ModelAdmin):
    """운영자가 컷라인을 코드 배포 없이 조정하는 유일한 경로(#16 AC)."""

    list_display = ("minimum_percentage", "updated_at")

    def has_add_permission(self, request):
        # 단일 행(pk=1)만 존재해야 한다 — 이미 있으면 추가를 막고 변경만 허용한다.
        return not DistributionCutline.objects.exists()


class DistributionShareInline(admin.TabularInline):
    model = DistributionShare
    extra = 0
    readonly_fields = ("submission", "amount", "created_at")
    can_delete = False


@admin.register(Distribution)
class DistributionAdmin(admin.ModelAdmin):
    list_display = (
        "contest",
        "cutline_percentage",
        "total_prize",
        "qualifying_count",
        "share_amount",
        "remainder_amount",
        "cutline_waived",
        "created_at",
    )
    inlines = [DistributionShareInline]
