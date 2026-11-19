# 느린 경로 경고(#971) — 경로마다 한 행이라 규칙 이름이 길어지고, 해소까지 센 검사 수를 든다.
# 둘 다 운영에서 즉시 끝난다: varchar 길이 늘리기는 표를 다시 쓰지 않고(행도 여섯), 상수 기본값 열 더하기는
# PostgreSQL 11+ 에서 카탈로그만 고친다.
# ROLLING-DEPLOY-SAFE: rule 은 varchar 길이만 늘린다(64 → 255, null 그대로) — 옛 코드는 64자 안의 값만 쓰므로 그대로 읽고 쓴다. clear_streak 는 db_default 0 이라 옛 코드의 INSERT 가 그 열을 빼도 된다.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ops_metrics", "0003_alert_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="alertstate",
            name="rule",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.AddField(
            model_name="alertstate",
            name="clear_streak",
            field=models.PositiveIntegerField(default=0, db_default=0),
        ),
    ]
