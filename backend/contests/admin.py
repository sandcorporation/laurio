from django.contrib import admin

from .models import Category, Contest, DeliverableType, Requirement, RequirementChatMessage


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_editable = ("is_active",)


@admin.register(DeliverableType)
class DeliverableTypeAdmin(admin.ModelAdmin):
    """운영자가 배포 없이 최소 제안 상금을 조정하는 화면(ADR-0001)."""

    list_display = ("name", "minimum_prize", "is_active")
    list_editable = ("minimum_prize", "is_active")


class RequirementInline(admin.TabularInline):
    model = Requirement
    extra = 0


@admin.register(Contest)
class ContestAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "sponsor",
        "category",
        "status",
        "prize",
        "required_minimum_prize",
        "is_underfunded",
        "deadline_at",
    )
    list_filter = ("status", "category", "is_underfunded")
    inlines = [RequirementInline]


@admin.register(RequirementChatMessage)
class RequirementChatMessageAdmin(admin.ModelAdmin):
    """AI grill 대화 이력을 운영자가 감사할 수 있는 화면(#20)."""

    list_display = ("contest", "role", "created_at")
    list_filter = ("role",)
    readonly_fields = ("contest", "role", "content", "prompt", "created_at")
