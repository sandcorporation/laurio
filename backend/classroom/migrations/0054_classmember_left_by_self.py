"""참여자 행이 닫힌 까닭이 스스로 나간 것인가(#1492-5).

칸만 더한다 — NULL 을 허용하고 기본값이 없다(ADD COLUMN 메타데이터만). 값은 셋이다: 참(나감)·거짓(내보냄)은
새 코드가 닫을 때 적은 확정 사유, NULL 은 사유 불명이다. 이 칸을 모르고 닫힌 행 — 칸이 생기기 전의 행과, 이행
뒤 겹쳐 배포 중인 옛 서버·코드만 되돌린 서버가 닫은 행 — 은 칸을 건드리지 않으므로 NULL 로 남는다. 기본값이
거짓이면 그런 행이 새 코드의 「내보냄」과 섞인다(#1509 ①). 일회성 행 채우기는 이행 뒤의 쓰기를 놓치므로(#1503 ②)
불명인 행만 읽을 때 남은 흔적(탈퇴)으로 판정한다 — `classroom.departures.left_member_ids`."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0053_class_signal_rev"),
    ]

    operations = [
        migrations.AddField(
            model_name="classmember",
            name="left_by_self",
            field=models.BooleanField(null=True),
        ),
    ]
