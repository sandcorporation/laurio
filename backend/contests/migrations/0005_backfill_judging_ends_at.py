# 이미 CLOSED 상태로 배포돼 있던 Contest의 judging_ends_at을 채운다.
#
# 0004는 judging_ends_at을 null 허용 컬럼으로만 추가했다 — 그 컬럼을 실제로 채우는
# 조건부 UPDATE는 contests.apps.ContestsConfig.ready()가 등록한
# PUBLISHED -> CLOSED 전이 규칙(core.transitions)뿐이다. 그런데 그 규칙은 "지금부터
# CLOSED로 전이하는" 행에만 적용되고, 이 마이그레이션이 배포되기 전에 이미 CLOSED로
# 넘어가 있던 행(다른 체인의 테스트 데이터가 아니라, 이 기능이 배포된 뒤 실제
# 운영 DB에 이미 존재할 수 있는 행)은 손대지 않는다. 그 행들은 judging_ends_at이
# 영원히 NULL로 남아 Award는 403, 연장은 409, 스케줄러의 `__lte` 비교는 NULL과
# 절대 매치하지 않아 영영 JUDGING_ENDED로도 못 넘어간다 — 운영자가 손쓸 방법이
# 없는 상태로 갇힌다.
#
# contests/migrations/0002_contest_ledger_id.py가 쓴 것과 같은 패턴(스키마 추가 ->
# RunPython 백필 -> 필요하면 잠그는 AlterField)을 따른다. 여기서는 컬럼을 계속
# nullable로 둔다 — CLOSED에 도달하기 전(DRAFT·PUBLISHED)에는 judging_ends_at이
# 여전히 정당하게 null이기 때문이다.
from datetime import timedelta

from django.db import migrations

# 이 마이그레이션이 작성된 시점의 심사기간 길이를 그대로 굳힌다 — 나중에
# settings.JUDGING_PERIOD_DAYS를 바꿔도 이 백필의 의미(당시의 7일 규칙을 소급 적용)는
# 흔들리면 안 된다. contests/apps.py의 런타임 전이 규칙은 계속 settings 값을 따른다.
_JUDGING_PERIOD_DAYS_AT_MIGRATION_TIME = 7


def backfill_judging_ends_at(apps, schema_editor):
    Contest = apps.get_model("contests", "Contest")
    stranded = Contest.objects.filter(status="closed", judging_ends_at__isnull=True)
    for contest in stranded.iterator():
        Contest.objects.filter(pk=contest.pk).update(
            judging_ends_at=contest.deadline_at
            + timedelta(days=_JUDGING_PERIOD_DAYS_AT_MIGRATION_TIME)
        )


def noop_reverse(apps, schema_editor):
    # judging_ends_at 컬럼 자체를 지우는 건 0004의 RemoveField(역방향)가 이미
    # 담당하므로, 역방향 RunPython은 아무 것도 할 필요가 없다 — 그래도 reverse가
    # 정의돼 있어야 `migrate contests 0004`가 여기서 막히지 않는다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contests", "0004_contest_judging_ends_at_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_judging_ends_at, noop_reverse),
    ]
