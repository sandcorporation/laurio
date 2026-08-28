from django.contrib import admin

from .models import Evidence, RequirementResponse, Submission


class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 0


class RequirementResponseInline(admin.TabularInline):
    model = RequirementResponse
    extra = 0


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    # 소스는 운영자 화면에서도 object_key만 보인다 — 실제 바이트는 프레젠드
    # 다운로드로만 접근한다(ADR-0005).
    list_display = ("id", "contest", "developer", "created_at", "updated_at")
    list_filter = ("contest",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(RequirementResponse)
class RequirementResponseAdmin(admin.ModelAdmin):
    list_display = ("id", "submission", "requirement", "is_met")
    inlines = [EvidenceInline]
