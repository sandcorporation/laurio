"""dev 전용 최소 기준 데이터 시드 (FE-09, #34).

Category·DeliverableType은 REQUEST.md가 명시한 대로 "DB로 관리"하는 운영
파라미터라 마이그레이션에 하드코딩하지 않는다 — 운영자가 admin에서 조정한다.
그런데 프론트엔드가 Contest 개최 폼(FE-04 이후)이나 presigned 업로드 e2e
증명(FE-09)에서 실제로 카테고리·요구형태 하나씩을 골라야 하는데, 빈 DB로
compose를 새로 띄우면 그 목록이 전부 비어 있어 아무것도 진행할 수 없다.

이 커맨드는 멱등하다(get_or_create) — 몇 번을 다시 돌려도 중복이 생기지 않고,
운영자가 admin에서 이미 채워놓은 값이 있어도 건드리지 않는다. dev compose가
매 기동마다 migrate 다음 단계로 이 커맨드를 부른다(docker/compose.dev.yaml).
staging/prod compose는 부르지 않는다 — 실제 카테고리·요구형태 확정은 TBD고
(REQUEST.md), 운영자가 admin에서 직접 채운다.

**원래 `core`에 있었다(#465 전까지).** 심는 것이 Category·DeliverableType
뿐이라 `contests`가 맞는 자리다 — 공유층이 공모전 하나만 아는 코드를 들고 있을
이유가 없었다. 명령 이름은 그대로다(`docker/compose.dev.yaml`이 이름으로 부른다).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from contests.models import Category, DeliverableType

_CATEGORIES = ["엔터테인먼트", "교육", "게임", "라이프스타일"]

# REQUEST.md "요구형태와 최소 제안 상금" 표 그대로.
_DELIVERABLE_TYPES = [
    ("랜딩·원페이지", 200_000),
    ("관리자 페이지", 500_000),
    ("웹 서비스", 1_000_000),
    ("모바일 앱", 1_000_000),
    ("데스크톱 프로그램", 1_000_000),
]


class Command(BaseCommand):
    help = "dev 전용 — Category·DeliverableType 최소 기준 데이터를 멱등하게 채운다."

    def handle(self, *args, **options):
        created_categories = 0
        for name in _CATEGORIES:
            _, created = Category.objects.get_or_create(name=name)
            created_categories += int(created)

        created_types = 0
        for name, minimum_prize in _DELIVERABLE_TYPES:
            _, created = DeliverableType.objects.get_or_create(
                name=name, defaults={"minimum_prize": minimum_prize}
            )
            created_types += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_dev_data: Category +{created_categories}, DeliverableType +{created_types}"
            )
        )
