"""운영 필수 설정이 이 컨테이너에서 비었는지 본다(#1124) — 배포 뒤 확인이 서비스마다 부른다.

```
python manage.py check_required_settings --service celery-worker   # 0 통과 · 1 빈 키가 있다
python manage.py check_required_settings --services                # 확인할 서비스 이름만
```

표는 `ops_metrics/required_settings.py`. 키 이름과 「비어 있음」만 낸다 — 값·길이·해시는 내지 않는다.
"""

from __future__ import annotations

import argparse

from django.core.management.base import BaseCommand, CommandError

from ops_metrics import required_settings


class Command(BaseCommand):
    help = "운영 필수 설정 가운데 이 서비스에서 비어 있는 키 이름을 낸다."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--service", help="compose 서비스 이름(backend·celery-worker …)")
        group.add_argument("--services", action="store_true", help="표에 나오는 서비스 이름만 낸다")

    def handle(self, *args: object, **options: object) -> None:
        if options["services"]:
            self.stdout.write(" ".join(required_settings.services()))
            return
        service = str(options["service"])
        if service not in required_settings.services():
            raise CommandError(f"필수 설정 표에 없는 서비스다: {service}")
        empty = required_settings.missing(service)
        for name in empty:
            self.stdout.write(f"{service} {name}: 비어 있음")
        if empty:
            raise CommandError(f"{service}: 필수 설정 {len(empty)}개가 비어 있다", returncode=1)
        self.stdout.write(f"{service}: 필수 설정 통과")
