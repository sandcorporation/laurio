"""리드타임·요금·기간에 상한 CheckConstraint를 단다 (#78 코드리뷰 지적 1).

#78이 옮긴 열 개 필드 중 요금·기간·리드타임·주간 한도 아홉 개에 하한(기간
1일 이상, #78의 0003)만 있고 상한이 없었다. `deadline_reminder_lead_hours`를
24 대신 2400으로 오타내면 다음 스캔에서 모든 PUBLISHED Contest가 "마감 임박"
알림을 받고, Contest당 한 번뿐인 `deadline_reminder_sent_at` 플래그가
찍힌다 — 값을 되돌려도 그 Contest들의 진짜 마감 알림은 영영 나가지 않는다
(되돌릴 수 없는 손상).

#75가 `platform_fee_bps`·`withholding_tax_bps`에 상한을 건 것과 같은
근거다 — 이 값을 넘는 입력은 오타이지 사업 판단일 수 없고, 운영자 API(#76)
전까지는 이 모델의 CheckConstraint가 유일한 방어선이다. 아래 상한은 전부
기본값 대비 넉넉한 여유(수십 배)를 두면서도 자릿수가 하나 더 붙는 흔한
오타는 막는다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0003_remaining_fees_periods_and_lead_times'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('contest_listing_fee__lte', 10000000)), name='contest_listing_fee_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('judging_extension_fee__lte', 10000000)), name='judging_extension_fee_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('judging_period_days__lte', 180)), name='judging_period_days_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('judging_extension_days__lte', 180)), name='judging_extension_days_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('handover_acceptance_period_days__lte', 180)), name='handover_acceptance_period_days_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('distribution_wait_days__lte', 180)), name='distribution_wait_days_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('deadline_reminder_lead_hours__lte', 720)), name='deadline_reminder_lead_hours_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('judging_end_reminder_lead_hours__lte', 720)), name='judging_end_reminder_lead_hours_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('distribution_final_warning_lead_days__lte', 30)), name='distribution_final_warning_lead_days_sane_upper_bound'),
        ),
        migrations.AddConstraint(
            model_name='platformpolicy',
            constraint=models.CheckConstraint(condition=models.Q(('seller_weekly_limit_amount__lte', 1000000000)), name='seller_weekly_limit_amount_sane_upper_bound'),
        ),
    ]
