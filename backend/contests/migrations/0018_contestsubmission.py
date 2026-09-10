"""공모전 자식 `ContestSubmission`을 만들고 기존 행을 옮긴다 (#270, ADR-0039).

**테이블을 옮기지 않는다 — 컬럼 둘만 옮긴다.** `submissions.Submission`(부모)은
테이블·pk 그대로 남는다. `submissions/0013`이 Django의 상태에서만
`contest`·`developer`를 지워 뒀으므로(그래야 이 마이그레이션이 같은 이름의
필드를 자식에 선언할 수 있다), 그 두 컬럼은 `submissions_submission` 테이블에
**물리적으로는 아직 남아 있다**. 이 마이그레이션은 그 물리 컬럼을 원본으로
새 자식 테이블을 채운다 — raw SQL을 쓰는 이유는 Django의 상태(ORM 모델)가
이미 그 컬럼을 모르기 때문이다.

`submissions/0014`가 그 뒤에 원본 컬럼을 물리적으로 지운다. **순서가 규율이다**
(`submissions/migrations/0004`와 같다) — 이 마이그레이션과 `0014` 사이에
호출부가 전부 `ContestSubmission`을 통해 `contest`·`developer`를 읽도록
바뀌어 있어야 한다.

되돌리기는 이 마이그레이션 하나만으로는 데이터를 잃지 않는다 — 원본 컬럼이
아직 물리적으로 그대로이므로 자식 테이블만 지우면 된다(`CreateModel`의 자동
되돌리기). 전체를 되돌릴 때 실제로 값을 옮겨 담는 쪽은 `0014`의 되돌리기다
— 그쪽이 원본 컬럼을 되살리는 시점에 이 자식 테이블이 아직 존재한다.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def copy_to_child(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO contests_contestsubmission "
            "(submission_ptr_id, contest_id, developer_id) "
            "SELECT id, contest_id, developer_id FROM submissions_submission"
        )


def noop_reverse(apps, schema_editor):
    # 원본 컬럼은 아직 물리적으로 그대로다(`0013`은 상태만 지웠다) — 자식
    # 테이블이 지워질 뿐(`CreateModel`의 자동 되돌리기) 값은 잃지 않는다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contests", "0017_contestimage_detail_key_and_more"),
        ("submissions", "0013_forget_contest_and_developer"),
        ("accounts", "0004_sponsorprofile_can_open_assignments_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContestSubmission",
            fields=[
                (
                    "submission_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="submissions.submission",
                    ),
                ),
                (
                    "contest",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="submissions",
                        to="contests.contest",
                    ),
                ),
                (
                    "developer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="submissions",
                        to="accounts.developerprofile",
                    ),
                ),
            ],
            bases=("submissions.submission",),
        ),
        migrations.RunPython(copy_to_child, noop_reverse),
        migrations.AddConstraint(
            model_name="contestsubmission",
            constraint=models.UniqueConstraint(
                fields=("contest", "developer"), name="unique_submission_per_contest_developer"
            ),
        ),
    ]
