# 이 기능이 배포되기 전에 이미 Award돼 있던 Contest에 Handover를 채운다.
#
# Handover는 지금까지 awards.api.award_submission이 Award 생성과 같은 트랜잭션
# 에서만 만들었다(#14) — 그래서 이 마이그레이션이 적용되기 전에 이미 Award된
# Contest(다른 체인의 테스트 데이터가 아니라, 이 기능이 배포된 뒤 실제 운영
# DB에 이미 존재할 수 있는 행)는 Handover가 아예 없는 채로 남는다. 그 Award는
# 모든 Handover 엔드포인트에서 404이고, release-due 스캔은 애초에 Handover
# 테이블만 스캔하므로 이 행을 볼 방법이 없으며, Payout 요청도 Handover가 없어
# 404다 — Escrow 해제도 지급도 영구히 막힌다(운영자가 손쓸 방법이 없는 상태로
# 갇힌다는 점에서 contests/migrations/0005_backfill_judging_ends_at.py와 정확히
# 같은 모양의 사고다).
#
# contests/migrations/0002_contest_ledger_id.py·0005_backfill_judging_ends_at.py
# 가 쓴 것과 같은 패턴을 따른다: 스키마는 이미 있으므로(0001) RunPython 백필만
# 추가한다. 새로 만드는 Handover는 이미 Award된 시점부터 인수 대기 상태로
# 시작해야 정상 흐름(수동 인수 확인 또는 타임아웃 스캔)에 그대로 올라탄다.
from datetime import timedelta

from django.db import migrations

# 이 마이그레이션이 작성된 시점의 인수 대기 기간을 그대로 굳힌다 — 나중에
# settings.HANDOVER_ACCEPTANCE_PERIOD_DAYS를 바꿔도 이 백필의 의미(당시의 14일
# 규칙을 소급 적용)는 흔들리면 안 된다(contests/migrations/
# 0005_backfill_judging_ends_at.py의 _JUDGING_PERIOD_DAYS_AT_MIGRATION_TIME과
# 같은 이유). handovers.api의 런타임 인수 확인·release-due 스캔은 계속 settings
# 값을 따른다 — 이 상수는 배포 시점 이전에 이미 확정됐던 Award들에만 쓰인다.
_HANDOVER_ACCEPTANCE_PERIOD_DAYS_AT_MIGRATION_TIME = 14


def backfill_missing_handovers(apps, schema_editor):
    Award = apps.get_model("awards", "Award")
    Handover = apps.get_model("handovers", "Handover")

    stranded = Award.objects.filter(handover__isnull=True)
    for award in stranded.iterator():
        Handover.objects.create(
            award_id=award.id,
            status="pending_acceptance",
            release_deadline_at=award.awarded_at
            + timedelta(days=_HANDOVER_ACCEPTANCE_PERIOD_DAYS_AT_MIGRATION_TIME),
        )


def noop_reverse(apps, schema_editor):
    # Handover 행 자체를 지우는 건 이 마이그레이션의 책임이 아니다(0001의
    # 역방향 CreateModel이 테이블째 지운다) — 그래도 reverse가 정의돼 있어야
    # `migrate handovers 0001`이 여기서 막히지 않는다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("handovers", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_missing_handovers, noop_reverse),
    ]
