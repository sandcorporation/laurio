"""`contest`·`developer`를 **상태에서만** 지운다 — 실제 컬럼은 아직 그대로다
(#270, ADR-0039).

**왜 상태와 DB를 갈라놓는가.** `contests.ContestSubmission`(다음 마이그레이션,
`contests/0018`)이 같은 이름의 `contest`·`developer` 필드를 선언하는 순간, 그
시점의 프로젝트 상태에 `submissions.Submission`이 아직 그 두 필드를 갖고 있으면
Django가 "자식 필드가 부모 필드와 겹친다"며 그 자리에서 막는다(다중 테이블
상속은 부모·자식이 같은 필드 이름을 동시에 가질 수 없다) — 그런데 그 자식을
채울 데이터는 아직 이 테이블의 물리 컬럼에만 있다. 그래서 여기서는 **Django의
장부(상태)에서만** 두 필드를 지우고, 실제 컬럼은 남겨 둔다 — `contests/0018`이
그 물리 컬럼을 원본으로 자식 테이블을 채운 뒤, `0014`가 비로소 컬럼을 물리적으로
지운다.

**유니크 제약은 여기서 물리적으로도 지운다.** Postgres에서 제약(을 뒷받침하는
인덱스) 이름은 테이블이 아니라 스키마 전체에서 유일해야 한다 — `contests/0018`이
같은 이름(`unique_submission_per_contest_developer`)으로 자식 테이블에 제약을
새로 걸므로, 그 전에 이 이름을 비워 둬야 한다. 컬럼과 달리 제약은 `0014`까지
남겨 둘 이유가 없다 — 그 이름을 계속 쓰는 쪽은 자식이다.

되돌리기는 제약만 되살린다(컬럼이 이미 있어야 하므로, 컬럼을 되살리는 `0014`의
되돌리기가 먼저 실행된 뒤다 — `0014`가 이 마이그레이션에 의존하므로 되돌릴 때는
`0014`가 먼저 되돌려진다).
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0012_submission_user_and_product"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="submission",
                    name="unique_submission_per_contest_developer",
                ),
                migrations.RemoveField(
                    model_name="submission",
                    name="contest",
                ),
                migrations.RemoveField(
                    model_name="submission",
                    name="developer",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE submissions_submission "
                        "DROP CONSTRAINT unique_submission_per_contest_developer"
                    ),
                    reverse_sql=(
                        "ALTER TABLE submissions_submission "
                        "ADD CONSTRAINT unique_submission_per_contest_developer "
                        "UNIQUE (contest_id, developer_id)"
                    ),
                ),
            ],
        ),
    ]
