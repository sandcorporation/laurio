# 문제마다 권장 기한·마감 (#769, ADR-0063). 둘 다 null 기본이라 먼저 돌아도 옛 코드가
# 견딘다(ADR-0053) — 옛 INSERT 는 이 칸을 빼먹고, DB 가 NULL 을 넣는다.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0032_drop_class_token_budget_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="recommended_due_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="problem",
            name="due_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
