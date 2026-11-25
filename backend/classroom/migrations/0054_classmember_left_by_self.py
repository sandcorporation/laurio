"""참여자 행이 닫힌 까닭이 스스로 나간 것인가(#1492-5).

기존 행 채우기: 공동 강사의 떠나기·내보내기는 흔적이 남지 않는다(공동 강사 줄이 지워지고 알림도
없다) — 둘을 가를 근거가 없어 지금처럼 「내보냄」으로 둔다. 탈퇴만은 `accounts.Withdrawal` 이
남는다: 그 사람이 이 클래스의 공동 강사 초대를 수락한 적이 있고, 참여자 행이 탈퇴한 그 순간에
닫혔다면 탈퇴가 닫은 것이다(`co_instructors.leave_all_on_withdrawal` 이 탈퇴 트랜잭션 안에서 닫는다
— 탈퇴 시각 `withdrawn_at` 은 그보다 먼저 잡힌다)."""

from datetime import timedelta

from django.db import migrations, models

#: 탈퇴 시각과 참여자 행이 닫힌 시각 사이 — 한 트랜잭션 안이라 넉넉히 잡아도 다른 길과 겹치지 않는다.
_SAME_TRANSACTION = timedelta(minutes=1)


def mark_withdrawn_co_instructors_as_left(apps, schema_editor):
    ClassMember = apps.get_model("classroom", "ClassMember")
    CoInstructorInvite = apps.get_model("classroom", "CoInstructorInvite")
    Withdrawal = apps.get_model("accounts", "Withdrawal")

    withdrawn_at = dict(Withdrawal.objects.values_list("user_id", "withdrawn_at"))
    if not withdrawn_at:
        return
    co_taught = set(
        CoInstructorInvite.objects.filter(accepted_by_id__in=withdrawn_at, accepted_at__isnull=False).values_list(
            "classroom_id", "accepted_by_id"
        )
    )
    ids = [
        member_id
        for member_id, classroom_id, user_id, expelled_at in ClassMember.objects.filter(
            user_id__in=withdrawn_at, expelled_at__isnull=False
        ).values_list("id", "classroom_id", "user_id", "expelled_at")
        if (classroom_id, user_id) in co_taught
        and withdrawn_at[user_id] <= expelled_at <= withdrawn_at[user_id] + _SAME_TRANSACTION
    ]
    ClassMember.objects.filter(id__in=ids).update(left_by_self=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_unique_non_empty_user_email"),
        ("classroom", "0053_class_signal_rev"),
    ]

    operations = [
        migrations.AddField(
            model_name="classmember",
            name="left_by_self",
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.RunPython(mark_withdrawn_co_instructors_as_left, migrations.RunPython.noop),
    ]
