"""0053 이 더한 `classroom_class.signal_rev` 는 DB 기본값 0 을 가진다(#1496 ①).

겹쳐 배포하는 동안·코드만 되돌린 뒤 옛 서버의 클래스 만들기·복사·템플릿 가져오기 INSERT 는 이 칸을 모른다.
ORM 의 `default=0` 만 있으면 Django 가 이행 뒤 DB 기본값을 지워 그 INSERT 가 NOT NULL 로 떨어진다."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tests.classroom_scenarios import create_class, login

_ADD = ("classroom", "0053_class_signal_rev")
_BEFORE = ("classroom", "0052_link_legacy_transfer_request_notifications")


def _run_add_migration(*, backwards: bool) -> None:
    """0053 하나만 되돌리거나 다시 적용한다 — 실행 기록은 건드리지 않는다
    (`tests/test_classroom_token_budget_columns_dropped.py` 와 같은 까닭)."""

    loader = MigrationExecutor(connection).loader
    migration = loader.graph.nodes[_ADD]
    before = loader.project_state(_BEFORE, at_end=True)
    with connection.schema_editor(atomic=migration.atomic) as editor:
        if backwards:
            migration.unapply(before, editor)
        else:
            migration.apply(before, editor)


def _old_code_insert_copy_of(class_id: int) -> int:
    """`signal_rev` 를 모르는 옛 코드 꼴의 원시 INSERT — 있는 행을 베끼되 그 칸과 id·참가 코드만 뺀다."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'classroom_class' AND column_name NOT IN ('id', 'join_code', 'signal_rev')"
            " ORDER BY ordinal_position"
        )
        columns = ", ".join(f'"{row[0]}"' for row in cursor.fetchall())
        cursor.execute(
            f"INSERT INTO classroom_class ({columns}, join_code)"
            f" SELECT {columns}, 'OLDCODE1496' FROM classroom_class WHERE id = %s RETURNING id, signal_rev",
            [class_id],
        )
        new_id, signal_rev = cursor.fetchone()
    assert signal_rev == 0
    return new_id


@pytest.mark.django_db(transaction=True)
def test_an_insert_that_does_not_know_signal_rev_still_succeeds_after_0053(client):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], name="옛 코드 꼴")

    _run_add_migration(backwards=True)
    _run_add_migration(backwards=False)

    _old_code_insert_copy_of(class_id)
