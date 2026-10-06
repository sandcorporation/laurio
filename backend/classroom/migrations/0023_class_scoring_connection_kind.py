# ROLLING-DEPLOY-SAFE: db_default 가 있는 칸을 더하기만 한다 — 옛 코드는 이 칸을 모른 채 그대로 읽고 쓰고, 기존 클래스는 전부 「OpenAI 키」다.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0022_scoring_quota_exhausted'),
    ]

    operations = [
        migrations.AddField(
            model_name='class',
            name='scoring_connection_kind',
            field=models.CharField(
                choices=[('openai_key', 'OpenAI 키')],
                db_default='openai_key',
                default='openai_key',
                max_length=20,
            ),
        ),
    ]
