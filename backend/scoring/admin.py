"""Score admin — 조회 전용 (ADR-0006).

Score는 불변 스냅샷이다. admin에서 추가·수정·삭제를 허용하면 애플리케이션 레벨의
append-only 규율(scoring.models.Score, ledger.models.AppendOnlyModel 재사용)을
우회해 마감 직후 고정된 판정이 뒤바뀔 수 있으므로, 여기서는 감사를 위한 열람만
허용한다(ledger.admin.ReadOnlyAppendOnlyAdmin과 같은 원칙).
"""

from django.contrib import admin

from .models import Score, ScoringAttempt


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Score)
class ScoreAdmin(ReadOnlyAdmin):
    list_display = ("submission", "percentage", "model_version", "created_at")
    search_fields = ("=submission__id",)


@admin.register(ScoringAttempt)
class ScoringAttemptAdmin(admin.ModelAdmin):
    """실패 이력은 운영 로그다 — Score와 달리 열람만으로 제한하지 않는다."""

    list_display = ("submission", "attempted_at", "error")
    search_fields = ("=submission__id",)
