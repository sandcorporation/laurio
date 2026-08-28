from django.conf import settings
from django.contrib import admin

from .models import ClockOverride, ScheduledStateDemo


@admin.register(ClockOverride)
class ClockOverrideAdmin(admin.ModelAdmin):
    """ClockOverride 는 테스트 전용 스캐폴딩이다.

    이 행이 채워지면 `core.clock.Clock.now()` 가 실제 시각 대신 그 값을 돌려주므로,
    프로덕션에서 이걸 admin으로 채웠다가는 전이 스캔·야간 판단·연기 큐가 전부 그
    순간에 멈춘다. `settings.DEBUG` 를 요청마다 동적으로 확인해 배포 환경에서는 admin
    에 등록만 되어 있을 뿐 어떤 조작도 할 수 없게 막는다(import 시점에 조건부로
    등록하면 override_settings 로 테스트할 수 없어 회귀를 못 잡는다).
    """

    def has_module_permission(self, request):
        return settings.DEBUG and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return settings.DEBUG and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return settings.DEBUG and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return settings.DEBUG and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return settings.DEBUG and super().has_delete_permission(request, obj)


admin.site.register(ScheduledStateDemo)
