"""클래스에 의심 재판정 모델 칸을 더한다(#1291) — 칸 더하기만(빈 값 = 끔)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0043_checklistitem_machine_rule"),
    ]

    operations = [
        migrations.AddField(
            model_name="class",
            name="escalation_model",
            field=models.CharField(blank=True, db_default="", default="", max_length=200),
        ),
    ]
