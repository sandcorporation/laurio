"""JudgingExtensionPayment에 연장 일수 스냅샷을 추가하고 backfill한다 (#78 코드리뷰 지적 2).

initiate 시점에는 결제 금액(amount)만 스냅샷되고 연장 일수는 confirm
(`contests.services.mark_extension_paid`) 시점에 PlatformPolicy에서 다시
읽혔다. #78이 이 값을 런타임에 바꿀 수 있는 DB 행으로 옮기면서, initiate와
confirm 사이에 운영자가 `judging_extension_days`를 바꾸면 amount는 옛
금액 그대로 청구되는데 심사기간은 새 값만큼만 늘어나는 불일치 창이 실제로
열렸다 — 값이 상수였을 때는 없던 문제다.

이 마이그레이션 이전에 이미 존재하는 모든 JudgingExtensionPayment 행은
옛 JUDGING_EXTENSION_DAYS 환경변수 기본값(7, 어떤 배포 환경도 오버라이드한
적이 없었다 — #73 조사, `payouts/migrations/0004_payout_rate_snapshot.py`와
같은 근거)으로 계산되었다. `default=7`/`preserve_default=False`로 AddField
자체가 기존 행을 이 값으로 채운다 — 이후 신규 행은 initiate 엔드포인트가
그 시점의 정책값을 명시적으로 채워야 한다(모델 필드 자체에는 기본값이
남지 않는다).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contests", "0009_contest_contest_status_deadline_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="judgingextensionpayment",
            name="extension_days",
            field=models.PositiveIntegerField(default=7),
            preserve_default=False,
        ),
    ]
