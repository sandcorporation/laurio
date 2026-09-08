"""`Contest.kind`를 일급 필드로 더한다 (#213, ADR-0033).

예전에는 "이 Contest가 Assignment인가"를 `category_id`가 예약된 Assignment `Category`
행(`0013_assignment_category`)과 같은지로 판정했다(`Contest.is_assignment`). 이 마이그레이션은
그 판정을 생성 시점에 고정되는 필드로 옮긴다 — 기존 행은 지금 그 판정 방식 그대로
(`category__name="과제"`) 한 번 채우고, 이후로는 API가 생성 시점에 이 필드를 직접 찍는다
(`contests.api.create_contest`·`contests.assignment_api.create_assignment`).

Category 이름으로 비교하는 이유는 이 마이그레이션이 `0013_assignment_category`가 심어 둔
행을 그대로 신뢰하기 때문이다 — `contests.assignment_category.ASSIGNMENT_CATEGORY_NAME`을
문자열로 그대로 쓴다(마이그레이션은 앱 코드를 import하지 않는다, historical model 관용구).
"""

from django.db import migrations, models

ASSIGNMENT_CATEGORY_NAME = "과제"


def backfill_kind(apps, schema_editor):
    Contest = apps.get_model("contests", "Contest")

    Contest.objects.filter(category__name=ASSIGNMENT_CATEGORY_NAME).update(kind="assignment")


def noop_reverse(apps, schema_editor):
    # `kind` 컬럼 자체는 RemoveField가 걷어간다 — 되돌릴 데이터가 없다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contests", "0013_assignment_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="contest",
            name="kind",
            field=models.CharField(
                choices=[("contest", "공모전"), ("assignment", "과제")],
                default="contest",
                editable=False,
                max_length=10,
            ),
        ),
        migrations.RunPython(backfill_kind, noop_reverse),
    ]
