# ledger_id를 세 단계로 나눠 추가한다.
#
# AddField(default=uuid.uuid4, unique=True) 하나로 처리하면 Django가
# effective_default()를 딱 한 번만 평가해서 그 값을 이미 있는 모든 행에 그대로
# 써버린다 — 기존 Contest가 하나라도 있는 DB(#8이 이미 돌아간 dev·staging)에서는
# unique 인덱스 생성이 곧바로 중복 키 위반으로 실패한다. 그래서
# 1) null 허용으로 컬럼만 추가 → 2) RunPython으로 행마다 서로 다른 UUID를 배정 →
# 3) unique·not null로 잠그는 순서로 나눈다.
import uuid

from django.db import migrations, models


def backfill_ledger_id(apps, schema_editor):
    Contest = apps.get_model("contests", "Contest")
    for contest in Contest.objects.all().iterator():
        Contest.objects.filter(pk=contest.pk).update(ledger_id=uuid.uuid4())


def noop_reverse(apps, schema_editor):
    # ledger_id를 다시 지우는 건 AlterField/RemoveField가 이미 하므로, 역방향
    # RunPython은 아무 것도 할 필요가 없다 — 그래도 reverse가 정의돼 있어야
    # `migrate contests 0001`이 이 마이그레이션에서 막히지 않는다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contests', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='ledger_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(backfill_ledger_id, noop_reverse),
        migrations.AlterField(
            model_name='contest',
            name='ledger_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
