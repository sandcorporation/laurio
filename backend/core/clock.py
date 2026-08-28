"""주입 가능한 시각 제공자 (ADR-0003).

앱 코드는 `datetime.now()` / `datetime.utcnow()` / `django.utils.timezone.now()` 를
직접 부르지 않고, "현재 시각이 필요하다"는 모든 지점에서 이 모듈의 `Clock.now()` 를
거친다. 프로덕션에서는 실제 시각과 동일하게 동작하고, 테스트는 `ClockOverride` 행을
채워 시각을 고정하거나 임의로 전진시킬 수 있다.

테스트에서의 사용 예:

    from core.models import ClockOverride

    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": frozen_time})
    # ... Clock.now() 를 쓰는 코드는 이제 frozen_time 을 "지금"으로 본다 ...
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": frozen_time + delta})
    # ... 시각을 임의로 전진시켰다 ...
"""

from django.utils import timezone

from .models import ClockOverride


class Clock:
    @staticmethod
    def now():
        overridden_at = (
            ClockOverride.objects.filter(pk=1).values_list("overridden_at", flat=True).first()
        )
        return overridden_at or timezone.now()
