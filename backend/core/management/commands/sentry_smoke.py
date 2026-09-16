"""오류 수집이 실제로 GlitchTip 에 닿는지 한 번 확인한다(2026-09-16).

설정이 틀려도 조용히 아무 일도 안 일어나는 것이 오류 수집의 기본 실패 모양이라
(그러면 진짜 사고가 날 때까지 모른다), 배포 뒤 이 명령을 한 번 쏘고 GlitchTip
프로젝트에 들어왔는지 눈으로 본다.

```
ssh sub 'docker exec codemit-staging-backend-1 python manage.py sentry_smoke'
```

일부러 예외를 만들어 보낸다 — 로그 한 줄이 아니라 예외여야 실제 경로(스택 추적·
release·environment 태그)가 전부 지나간다.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class SentrySmokeError(RuntimeError):
    """이 명령만 내는 예외 — GlitchTip 에서 이 이름으로 찾으면 된다."""


class Command(BaseCommand):
    help = "오류 수집기(GlitchTip)로 시험용 예외를 한 번 보낸다."

    def handle(self, *args, **options):
        if not getattr(settings, "SENTRY_ENABLED", False):
            raise CommandError(
                "SENTRY_DSN 이 없어 오류 수집기가 꺼져 있다 — 보낼 곳이 없다. "
                "배포 환경의 .env 에 DSN 을 넣었는지 확인한다."
            )

        import sentry_sdk

        try:
            raise SentrySmokeError("오류 수집 확인용 예외다 — 사고가 아니다.")
        except SentrySmokeError as exc:
            event_id = sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=10)

        self.stdout.write(
            self.style.SUCCESS(
                f"보냈다: event_id={event_id} environment={settings.CODEMIT_DEPLOYMENT_TARGET}"
            )
        )
