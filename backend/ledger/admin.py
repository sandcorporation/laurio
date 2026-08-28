"""원장 admin — 조회 전용.

원장은 append-only다(ADR-0004). admin에서 추가·수정·삭제를 허용하면 `/api/ledger/entries`가
강제하는 차변==대변 검증을 우회해 균형이 깨진 분개가 들어올 수 있으므로, 여기서는 감사를
위한 열람만 허용한다.
"""

from django.contrib import admin

from ledger.models import JournalEntry, LedgerLine


class LedgerLineInline(admin.TabularInline):
    model = LedgerLine
    extra = 0
    fields = ("account", "side", "amount")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ReadOnlyAppendOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JournalEntry)
class JournalEntryAdmin(ReadOnlyAppendOnlyAdmin):
    list_display = ("id", "contest_id", "memo", "reverses", "created_at")
    list_filter = ("contest_id",)
    inlines = [LedgerLineInline]


@admin.register(LedgerLine)
class LedgerLineAdmin(ReadOnlyAppendOnlyAdmin):
    list_display = ("id", "entry", "account", "side", "amount")
    list_filter = ("account", "side")
