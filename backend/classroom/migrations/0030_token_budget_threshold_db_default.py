# ROLLING-DEPLOY-SAFE: DB 기본값만 더한다 — 옛 코드는 값을 넣고 새 코드는 칸을 모르니 기본값이 채운다

from django.db import migrations


class Migration(migrations.Migration):
    """경고 임계 칸에 DB 기본값 80 을 건다(#665) — 0029 의 겹침 구멍을 막는다.

    0029 가 이 칸을 null 허용으로 바꿨지만 `default=80` 은 파이썬 쪽 기본값이라 DB 에는
    없다. 칸을 모르는 새 코드가 INSERT 한 클래스는 NULL 이 되고, 옛 코드의 `ClassOut`
    (`int`)가 겹치는 몇 초 동안(또는 되돌리기 때) 그 행을 읽다 500 을 낸다. DB 기본값이
    80 을 채워 옛 코드가 늘 정수를 읽게 한다. 칸 자체는 다음 마이그레이션(0031)이 지운다."""

    dependencies = [
        ("classroom", "0029_remove_class_token_budget"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE classroom_class ALTER COLUMN token_budget_warning_threshold_percent SET DEFAULT 80",
            reverse_sql="ALTER TABLE classroom_class ALTER COLUMN token_budget_warning_threshold_percent DROP DEFAULT",
        ),
    ]
