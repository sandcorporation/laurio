"""Assignment(ADR-0028, #207) 전용 Category 기준데이터를 심는다.

`contests.assignment_category.get_assignment_category`가 이 행을 이름으로 읽는다 —
`is_active=False`로 둬 공개 목록·공모전 개최 화면에 새지 않게 한다
(`contests.assignment_category` 모듈 docstring 참고).
"""

from django.db import migrations
from django.db.utils import IntegrityError

ASSIGNMENT_CATEGORY_NAME = "과제"


def create_assignment_category(apps, schema_editor):
    Category = apps.get_model("contests", "Category")

    existing = Category.objects.filter(name=ASSIGNMENT_CATEGORY_NAME).first()
    if existing is not None:
        # 이미 있는 행을 무조건 재사용하지 않는다 — `get_or_create`는 이름이
        # 우연히 같은(실제 산업·장르로 쓰이는) Category를 조용히 Assignment
        # 전용 행으로 접수해버릴 수 있다. `is_active=False`는 이 마이그레이션
        # 자신만 남기는 지문이다: 그 값이면 이전 실행(또는 롤백 후 재실행)이
        # 남긴 우리 행으로 보고 그대로 둔다. `is_active=True`면 다른 목적으로
        # 이미 쓰이는 행이라는 뜻이므로 여기서 멈춘다 — 운영자가 실제로 그런
        # Category를 만든 적이 있다면 이름을 바꾸거나 이 행을 수동으로
        # 정리해야 한다.
        if existing.is_active:
            raise IntegrityError(
                f"Category({ASSIGNMENT_CATEGORY_NAME!r})가 이미 활성 상태로 존재한다 — "
                "Assignment 전용 기준데이터로 재사용하지 않는다. 이름이 겹치는 기존 "
                "Category를 확인해 달라(0013_assignment_category)."
            )
        return

    Category.objects.create(name=ASSIGNMENT_CATEGORY_NAME, is_active=False)


def remove_assignment_category(apps, schema_editor):
    Category = apps.get_model("contests", "Category")
    Category.objects.filter(name=ASSIGNMENT_CATEGORY_NAME, contests__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contests", "0012_alter_contest_status_invitecode"),
    ]

    operations = [
        migrations.RunPython(create_assignment_category, remove_assignment_category),
    ]
