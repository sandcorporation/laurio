# 의심 재판정 모델 칸을 지운다(#1310, 대표 결정) — 첫 단계라 상태에서만 지운다(docs/ops/migrations.md 「칸 지우기」).
# 칸은 `db_default=""` 라 새 코드의 INSERT 가 빼먹어도 된다. DB 에서 지우는 것은 다음 PR 의
# `RunSQL("ALTER TABLE classroom_class DROP COLUMN IF EXISTS escalation_model")` 몫이다.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0046_template_machine_rule_and_score_fingerprint"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="class", name="escalation_model")],
        ),
    ]
