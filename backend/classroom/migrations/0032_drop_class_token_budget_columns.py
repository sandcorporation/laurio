# ROLLING-DEPLOY-SAFE: 옛 코드(0029 이후)는 이 칸을 읽지도 쓰지도 않는다 — 0029 가 먼저 배포된 환경에서만 돈다(PR 은 prod 가 0029 를 받을 때까지 hold)

from django.db import migrations

TABLE = "classroom_class"


class Migration(migrations.Migration):
    """채점 상한 칸 셋을 DB 에서 지운다(#665, ADR-0060) — expand → contract 의 두 번째 배포.

    Django 상태에서는 0029 가 이미 지웠다. 여기서는 DB 칸만 걷으므로 상태 연산이 없다.
    되돌리면 0030 직후의 모양(정수 null 허용 + 음수 막는 CHECK, 경고 임계는 DB 기본값
    80 — 기존 행도 80 으로 채운다)으로 칸 셋을 다시 더한다."""

    dependencies = [
        ("classroom", "0031_class_scoring_connection_verified_at"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS token_budget",
                f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS token_budget_warning_threshold_percent",
                f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS token_budget_warning_sent_at",
            ],
            reverse_sql=[
                f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS token_budget integer NULL"
                " CHECK (token_budget >= 0)",
                f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS token_budget_warning_threshold_percent"
                " integer NULL DEFAULT 80 CHECK (token_budget_warning_threshold_percent >= 0)",
                f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS token_budget_warning_sent_at"
                " timestamp with time zone NULL",
            ],
        ),
    ]
