"""나머지 요금·기간·리드타임·지급대행 주간 한도를 PlatformPolicy로 옮긴다 (#78, ADR-0023).

#75가 옮긴 요율 둘(platform_fee_bps·withholding_tax_bps)에 이어, settings.py의
환경변수 열 개(개최비·연장비·심사기간·심사기간 연장 단위·인도 승인 기간·배분
대기·알림 리드타임 3종·지급대행 주간 한도)를 이 행으로 옮긴다.

기본값은 전부 옛 환경변수의 기본값과 같다 — 이 마이그레이션의 유일한 안전망은
기존 테스트 스위트이고(CLAUDE.md), 그 스위트는 기간을 짧게 잡지 않고 시계를
옮긴다(ADR-0003) — 값의 출처만 바뀌고 값 자체는 그대로여야 결과가 같다.

기간 계열 네 필드(judging_period_days·judging_extension_days·
handover_acceptance_period_days·distribution_wait_days)에는 0일 방지
CheckConstraint를 단다 — "0일 기간"은 정책이 아니라 정책의 부재다(#73 스펙이
명시한 거부 대상). 나머지(요금·리드타임·지급대행 주간 한도)는 0을 거부할
이유가 없다 — 리드타임 0시간은 "마감 순간에 알린다"는 유효한 정책이다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0002_bounds_and_exempt_threshold_inputs'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformpolicy',
            name='contest_listing_fee',
            field=models.PositiveIntegerField(default=50000),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='deadline_reminder_lead_hours',
            field=models.PositiveIntegerField(default=24),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='distribution_final_warning_lead_days',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='distribution_wait_days',
            field=models.PositiveIntegerField(default=14),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='handover_acceptance_period_days',
            field=models.PositiveIntegerField(default=14),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='judging_end_reminder_lead_hours',
            field=models.PositiveIntegerField(default=24),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='judging_extension_days',
            field=models.PositiveIntegerField(default=7),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='judging_extension_fee',
            field=models.PositiveIntegerField(default=30000),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='judging_period_days',
            field=models.PositiveIntegerField(default=7),
        ),
        migrations.AddField(
            model_name='platformpolicy',
            name='seller_weekly_limit_amount',
            field=models.PositiveIntegerField(default=10000000),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('judging_period_days__gte', 1)), name='judging_period_days_at_least_one_day'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('judging_extension_days__gte', 1)), name='judging_extension_days_at_least_one_day'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('handover_acceptance_period_days__gte', 1)), name='handover_acceptance_period_days_at_least_one_day'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('distribution_wait_days__gte', 1)), name='distribution_wait_days_at_least_one_day'),
        ),
    ]
