"""#1354 — 서브에이전트 줄(#1353)을 걷어내며 0009 의 두 칸을 상태에서만 지운다.

DB 칸은 다음 배포(0011)에서 지운다(docs/ops/migrations.md 「두 단계」). 남은 칸은 새 코드의 INSERT 를
깨지 않는다 — `sub_model` 은 DB 기본값 '' 이 있고 `model_usage` 는 null 을 받는다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_agent_run_token_sub_model'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name='agentruntoken', name='model_usage'),
                migrations.RemoveField(model_name='agentruntoken', name='sub_model'),
            ],
        ),
    ]
