"""`contest`·`developer` 물리 컬럼을 지운다 — `contests/0018`이 자식 테이블로
옮긴 뒤다 (#270, ADR-0039, `submissions/migrations/0004`와 같은 규율).

Django 상태는 이미 `0013`에서 이 두 필드를 지웠으므로, 여기는 순수 DB 연산이다
(`SeparateDatabaseAndState`로 상태 변화 없음을 명시한다) — raw SQL을 쓰는
이유는 Django ORM이 이미 이 컬럼들을 모르기 때문이다(`RemoveField`를 다시
쓰면 "모르는 필드를 지우라"는 상태 불일치가 난다).

**되돌리기가 값을 복구한다.** `0013`(상태만 지웠고, 제약은 이미 물리적으로도
지웠다)과 달리 이번에는 컬럼 자체가 사라지므로, 되돌릴 때는 컬럼을 다시 만든
뒤 `contests.ContestSubmission`(이 마이그레이션이 되돌려지는 시점에는 아직
존재한다 — `contests/0018`은 이 마이그레이션보다 나중에 되돌려진다)에서 값을
그대로 베껴 채우고, 그 다음에야 not null로 잠근다. 유니크 제약은 여기서
되살리지 않는다 — 그것은 `0013`의 되돌리기가 한다(이 마이그레이션이 `0013`에
의존하므로, 되돌릴 때는 이 마이그레이션이 먼저 되돌려지고 `0013`이 그 다음이다
— 그래서 `0013`의 되돌리기 시점에는 이미 컬럼과 값이 준비돼 있다).
"""

from __future__ import annotations

from django.db import migrations


def _forward_sql(cursor) -> None:
    cursor.execute(
        "ALTER TABLE submissions_submission "
        "DROP COLUMN contest_id, "
        "DROP COLUMN developer_id"
    )


def _reverse_sql(cursor) -> None:
    cursor.execute(
        "ALTER TABLE submissions_submission "
        "ADD COLUMN contest_id bigint, "
        "ADD COLUMN developer_id bigint"
    )
    cursor.execute(
        "UPDATE submissions_submission AS s "
        "SET contest_id = cs.contest_id, developer_id = cs.developer_id "
        "FROM contests_contestsubmission AS cs "
        "WHERE cs.submission_ptr_id = s.id"
    )
    cursor.execute(
        "ALTER TABLE submissions_submission "
        "ALTER COLUMN contest_id SET NOT NULL, "
        "ALTER COLUMN developer_id SET NOT NULL, "
        "ADD CONSTRAINT submissions_submission_contest_id_fk "
        "FOREIGN KEY (contest_id) REFERENCES contests_contest(id) DEFERRABLE INITIALLY DEFERRED, "
        "ADD CONSTRAINT submissions_submission_developer_id_fk "
        "FOREIGN KEY (developer_id) REFERENCES accounts_developerprofile(id) "
        "DEFERRABLE INITIALLY DEFERRED"
    )
    cursor.execute(
        "CREATE INDEX submissions_submission_contest_id_idx "
        "ON submissions_submission (contest_id)"
    )
    cursor.execute(
        "CREATE INDEX submissions_submission_developer_id_idx "
        "ON submissions_submission (developer_id)"
    )


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _forward_sql(cursor)


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _reverse_sql(cursor)


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0013_forget_contest_and_developer"),
        ("contests", "0018_contestsubmission"),
    ]

    operations = [
        # `RunPython`은 기본적으로 상태를 건드리지 않는다 — 상태는 이미 `0013`이
        # 지웠으므로 여기서 더 지울 상태가 없다.
        migrations.RunPython(forward, reverse),
    ]
