"""Submission 부모에 제출자(`user`)와 제품 식별 컬럼(`product`)을 더한다
(#270, ADR-0039).

`0013`(contests)이 자식 `ContestSubmission`을 만들고 이 시점의 `contest`·
`developer` 컬럼에서 자료를 복제한다 — 그 뒤 `0014`(submissions)가 그 두
컬럼을 지운다. 이 마이그레이션은 그 사이에서 `user`·`product`만 채운다.

`user`는 `contest_ledger_id`(contests/migrations/0002)와 같은 3단계다 — null
허용으로 추가 → RunPython으로 `developer.user_id`를 그대로 옮겨 백필 → not
null로 잠근다. `product`는 지금 존재하는 행이 전부 공모전 제출이므로
`default="contest"` 하나로 끝난다.
"""

from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_user(apps, schema_editor):
    Submission = apps.get_model("submissions", "Submission")
    for submission in Submission.objects.all().iterator():
        Submission.objects.filter(pk=submission.pk).update(
            user_id=submission.developer.user_id
        )


def noop_reverse(apps, schema_editor):
    # 되돌리는 쪽은 `0014`의 되돌리기가 이미 `user`를 참조하지 않는 상태로
    # 되돌려 놓으므로, 여기서는 값을 되살릴 필요가 없다 — `RunPython`에는
    # 그래도 reverse가 정의돼 있어야 이 마이그레이션 한 칸만 되돌릴 수 있다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0011_merge_screenshot_kind_and_destroyed_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="submissions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="product",
            field=models.CharField(
                choices=[("contest", "공모전"), ("classroom", "강의실")],
                default="contest",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_user, noop_reverse),
        migrations.AlterField(
            model_name="submission",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="submissions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
