# 실행 토큰의 키 출처(#1036) — 칸 추가뿐(NULL 허용, 기존 행은 플랫폼 키).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_agent_run_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentruntoken',
            name='key_class_id',
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
