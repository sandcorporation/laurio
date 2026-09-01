"""코드리뷰 지적 반영 (#75 후속).

1. 요율에 상한이 없어 오입력이 저장되면 지급 요청이 500으로 죽고 원인이
   덮인다 — 네 CheckConstraint로 "말이 안 되는 값은 애초에 저장되지 않는다"를
   강제한다.
2. 원천징수 면제 임계값(지급액 250,000원)이 withholding_tax_bps에서 유도되어,
   그 요율만 바꿔도 임계값이 조용히 틀려질 수 있었다.
   withholding_necessary_expense_bps·withholding_minor_income_exempt_won 두
   필드를 추가해 임계값이 이 둘에서만(요율과 독립적으로) 유도되게 한다
   (`payouts.services._withholding_exempt_threshold`).

기존 행(있다면 pk=1 하나뿐)은 새 필드의 기본값(8000, 50000)을 그대로 받는다 —
이 값들은 지금까지 코드에 있던 상수(필요경비 80%, 과세최저한 5만원)와 같아서
기존 계산 결과(임계값 250,000원)를 그대로 재현한다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("policies", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformpolicy",
            name="withholding_necessary_expense_bps",
            field=models.PositiveIntegerField(default=8000),
        ),
        migrations.AddField(
            model_name="platformpolicy",
            name="withholding_minor_income_exempt_won",
            field=models.PositiveIntegerField(default=50_000),
        ),
        migrations.AddConstraint(
            model_name="platformpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(platform_fee_bps__lte=9000),
                name="platform_fee_bps_sane_upper_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(withholding_tax_bps__lte=9000),
                name="withholding_tax_bps_sane_upper_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(withholding_necessary_expense_bps__lte=9999),
                name="withholding_necessary_expense_bps_below_100_percent",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    platform_fee_bps__lte=10_000 - models.F("withholding_tax_bps")
                ),
                name="platform_fee_and_withholding_bps_leave_nonnegative_net",
            ),
        ),
    ]
