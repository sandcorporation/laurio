"""withholding_exempt를 backfill한다 (#75 코드리뷰 지적 2).

이 필드가 생기기 전의 모든 Payout 행은 과세최저한 면제 로직 자체가 없던
시절(3.3%를 무조건 곱하던 원래 버그, 또는 #75가 고친 뒤라도 이 필드가 생기기
전)에 만들어졌다 — 그 시점에 "면제됐다"는 개념이 코드에 없었으므로 False로
backfill하는 것이 그때 상황을 정확히 반영한다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payouts", "0004_payout_rate_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="payout",
            name="withholding_exempt",
            field=models.BooleanField(default=False),
        ),
    ]
