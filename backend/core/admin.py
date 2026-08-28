from django.contrib import admin

from .models import ClockOverride, ScheduledStateDemo

admin.site.register(ClockOverride)
admin.site.register(ScheduledStateDemo)
