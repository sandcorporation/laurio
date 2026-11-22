# 「한 번 호출로 못 담는 제출물」 칸 둘과 점수의 못 본 파일 수(#1311). 기존 클래스는 db_default 로 모두 「반려」다(ADR-0053).
# #1310(0047)이 상태에서만 지운 `escalation_model` 열을 DB 에서도 지운다(docs/ops/migrations.md 「칸 지우기」의 둘째 단계).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0047_remove_class_escalation_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="class",
            name="oversize_policy",
            field=models.CharField(
                choices=[("reject", "반려"), ("agent", "에이전트로 채점"), ("partial", "들어가는 파일만으로 채점")],
                db_default="reject",
                default="reject",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="class",
            name="oversize_agent_model",
            field=models.CharField(blank=True, db_default="", default="", max_length=200),
        ),
        migrations.AddField(
            model_name="classroomscore",
            name="unseen_files",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
        migrations.RunSQL(
            "ALTER TABLE classroom_class DROP COLUMN IF EXISTS escalation_model",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
