"""#1354 2단계 — 0010 이 상태에서만 지운 `sub_model`·`model_usage` 를 DB 에서 지운다.

0010 이 배포된 뒤라 직전 판 코드는 이 두 칸을 읽고 쓰지 않는다(docs/ops/migrations.md 「두 단계」).
상태 연산은 없다.
"""

from django.db import migrations

TABLE = "core_agentruntoken"


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_agent_run_token_drop_sub_model_state'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS sub_model",
                f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS model_usage",
            ],
            reverse_sql=[
                f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS sub_model varchar(100) NOT NULL DEFAULT ''",
                f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS model_usage jsonb NULL",
            ],
        ),
    ]
