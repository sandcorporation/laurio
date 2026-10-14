# ROLLING-DEPLOY-SAFE: RemoveField 는 상태(state)에서만 지운다 — DB 칸 셋은 그대로 두고, NOT NULL 이던 경고 임계 칸만 null 을 허용해 새 코드의 INSERT 가 그 칸을 빼먹어도 되게 한다. 옛 코드는 칸이 남아 있어 그대로 읽고 쓴다. 실제 DROP 은 다음 배포의 contract 마이그레이션 0032(ADR-0053, #665).

from django.db import migrations, models


class Migration(migrations.Migration):
    """채점 상한을 걷는다(#629, ADR-0060) — expand → contract 의 첫 배포.

    새 코드는 `token_budget`·`token_budget_warning_threshold_percent`·`token_budget_warning_sent_at`
    을 읽지도 쓰지도 않는다. 겹쳐 바꾸는 몇 초 동안 옛 코드가 이 칸들을 SELECT·UPDATE 하므로
    DB 에서는 지우지 않는다. 칸 셋은 `0032_drop_class_token_budget_columns` 가 `RunSQL` 로
    지운다(#665 — 0029 가 배포된 뒤라 그때 옛 코드는 이미 이 칸을 모른다)."""

    dependencies = [
        ("classroom", "0028_classroom_submission_scoring_lease"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name="class",
                    name="token_budget_warning_threshold_percent",
                    field=models.PositiveIntegerField(default=80, null=True),
                ),
            ],
            state_operations=[
                migrations.RemoveField(model_name="class", name="token_budget"),
                migrations.RemoveField(model_name="class", name="token_budget_warning_threshold_percent"),
                migrations.RemoveField(model_name="class", name="token_budget_warning_sent_at"),
            ],
        ),
    ]
