"""참여자 행이 닫힌 까닭이 스스로 나간 것인가(#1492-5).

칸만 더한다. 이 칸을 모르고 닫힌 행 — 칸이 생기기 전의 행과, 이행 뒤 겹쳐 배포 중인 옛 서버·코드만 되돌린
서버가 닫은 행 — 은 일회성 행 채우기로는 다 잡히지 않는다(이행 뒤의 쓰기를 놓친다, #1503 ②). 그래서 행을
채우지 않고 읽을 때 남은 흔적(탈퇴)으로 판정한다 — `classroom.departures.left_member_ids`."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0053_class_signal_rev"),
    ]

    operations = [
        migrations.AddField(
            model_name="classmember",
            name="left_by_self",
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
