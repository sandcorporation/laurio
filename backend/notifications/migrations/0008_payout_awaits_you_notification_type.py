"""`NotificationType.PAYOUT_AWAITS_YOU`(#169)를 마이그레이션 상태에 반영한다.

**DB 는 한 바이트도 바뀌지 않는다** — `sqlmigrate` 가 `(no-op)` 을 낸다. Django 의
`choices` 는 Postgres 제약을 만들지 않으므로 이 `AlterField` 는 순수하게 마이그레이션
상태와 모델을 다시 맞추는 일이다.

그래도 필요하다: 이게 없으면 `makemigrations --check` 가 계속 실패하고, 다음 사람이
자기 변경으로 `makemigrations` 를 돌릴 때 **남의 변경이 자기 마이그레이션에 섞여
들어온다**. 실제로 #190 작업 중 그 드리프트를 만나 「내 변경인가」를 한 번 확인해야 했다.

#169 가 유형을 더하면서 마이그레이션을 빠뜨린 것이고, 그 뒤 여러 티켓이 이 드리프트를
그대로 안고 지나갔다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0007_alter_notificationdispatch_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(choices=[('deadline_reminder', '마감 임박 알림'), ('judging_period_ending_reminder', '심사기간 종료 임박 알림'), ('distribution_final_warning', 'Distribution 최종 경고'), ('result_notice', '결과 알림'), ('scoring_complete', '채점 완료'), ('appeal_ruled', '이의 심판 완료'), ('new_contest_in_category', '관심 Category 신규 Contest'), ('payout_awaits_you', '지급이 당신을 기다린다')], max_length=40),
        ),
        migrations.AlterField(
            model_name='notificationoptin',
            name='notification_type',
            field=models.CharField(choices=[('deadline_reminder', '마감 임박 알림'), ('judging_period_ending_reminder', '심사기간 종료 임박 알림'), ('distribution_final_warning', 'Distribution 최종 경고'), ('result_notice', '결과 알림'), ('scoring_complete', '채점 완료'), ('appeal_ruled', '이의 심판 완료'), ('new_contest_in_category', '관심 Category 신규 Contest'), ('payout_awaits_you', '지급이 당신을 기다린다')], max_length=40),
        ),
    ]
