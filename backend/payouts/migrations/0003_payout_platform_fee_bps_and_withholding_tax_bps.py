"""기존 Payout 행에 당시 요율을 backfill한다 (#75, ADR-0023).

이 마이그레이션 이전에는 요율이 settings.py의 환경변수(PAYOUT_PLATFORM_FEE_BPS
기본값 1000, PAYOUT_WITHHOLDING_TAX_BPS 기본값 330)였다 — 둘 다 어떤 배포
환경에서도 오버라이드된 적이 없었으므로(#73 조사), 이 저장소에 이미 존재하는
모든 Payout 행은 실제로 이 두 기본값으로 계산되었다. `default=`/
`preserve_default=False`로 AddField 자체가 기존 행을 이 값으로 채운다 — 마이그레이션이
값을 채우지 않아 옛 지급이 "요율 없음"으로 남는 사고를 만들지 않는다.

withholding_tax_bps의 backfill 값(330)은 새 기본값(440, PlatformPolicy 참고)과
다르다 — 의도적이다. 이 필드는 스냅샷이므로 옛 행은 그때 실제로 적용된(틀렸던)
세율을 그대로 기억해야 한다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payouts", "0002_payout_distribution_share_alter_payout_handover_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="payout",
            name="platform_fee_bps",
            field=models.PositiveIntegerField(default=1000),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="payout",
            name="withholding_tax_bps",
            field=models.PositiveIntegerField(default=330),
            preserve_default=False,
        ),
    ]
