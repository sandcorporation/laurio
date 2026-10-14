"""채점 상한 칸 셋은 0032 가 DB 에서 지우고, 되돌리면 다시 생긴다(#665, ADR-0053 contract).

0030 상태에서는 경고 임계 칸이 DB 기본값 80 을 가진다 — 칸을 모르는 새 코드의 INSERT 가
NULL 을 남기면 겹치는 동안 옛 코드의 `ClassOut`(int)이 500 을 낸다."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

COLUMNS = {
    "token_budget",
    "token_budget_warning_threshold_percent",
    "token_budget_warning_sent_at",
}


def _budget_columns() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'classroom_class' AND column_name = ANY(%s)",
            [list(COLUMNS)],
        )
        return {row[0] for row in cursor.fetchall()}


def _threshold_default() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_default FROM information_schema.columns"
            " WHERE table_name = 'classroom_class'"
            " AND column_name = 'token_budget_warning_threshold_percent'"
        )
        return cursor.fetchone()[0]


def _migrate(target: tuple[str, str]) -> None:
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])


@pytest.mark.django_db(transaction=True)
def test_contract_migration_drops_the_budget_columns_and_reverse_restores_them():
    assert _budget_columns() == set()

    _migrate(("classroom", "0030_token_budget_threshold_db_default"))
    try:
        assert _budget_columns() == COLUMNS
        assert _threshold_default() == "80"
    finally:
        _migrate(("classroom", "0032_drop_class_token_budget_columns"))

    assert _budget_columns() == set()
