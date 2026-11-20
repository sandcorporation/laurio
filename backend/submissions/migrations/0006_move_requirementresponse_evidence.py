"""자가 응답·근거의 옛 상태를 지운다 — 짝인 `contests/0015` 가 같은 표를 contests 소속으로 세웠다(#1086).

**상태만 지운다.** 표는 그대로 contests 의 모델이 쓴다 — `sqlmigrate` 가 SQL 0줄이다.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0005_submissionasset_video_link_kind"),
        ("contests", "0015_move_requirementresponse_evidence"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="Evidence"),
                migrations.DeleteModel(name="RequirementResponse"),
            ],
        ),
    ]
