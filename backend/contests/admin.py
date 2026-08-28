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


class ReadOnlyAdmin(admin.ModelAdmin):
    """`payments.admin.ReadOnlyAdmin`과 같은 이유로 추가·수정·삭제를 전부 막는다.

    필드를 전부 readonly로만 둬도 `has_add_permission`을 막지 않으면 "모든 필드가
    readonly인 추가 폼"이 그대로 남는다 — 거기서 저장을 누르면 필수 FK
    (`contest`)가 비어 있는 채로 INSERT가 나가 NOT NULL 제약 위반으로 500이 난다.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RequirementChatMessage)
class RequirementChatMessageAdmin(ReadOnlyAdmin):
    """AI grill 대화 이력을 운영자가 감사할 수 있는 화면(#20). 조회 전용이다."""

    list_display = ("contest", "role", "created_at")
    list_filter = ("role",)
    readonly_fields = ("contest", "role", "content", "prompt", "created_at")
