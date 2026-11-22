"""체크리스트 항목에 기계 확인 규칙 칸을 더한다(#1283) — 칸 더하기만(null 허용, 기본값 없음)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0042_class_anthropic_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="checklistitem",
            name="machine_rule",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
