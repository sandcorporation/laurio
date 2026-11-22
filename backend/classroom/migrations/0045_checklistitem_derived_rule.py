"""체크리스트 항목에 도출 규칙 칸을 더한다(#1293) — 칸 더하기만(null·빈 문자열 기본값)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0044_class_escalation_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="checklistitem",
            name="derived_rule",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="checklistitem",
            name="derived_kind",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="checklistitem",
            name="derived_text_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="checklistitem",
            name="derived_model",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
