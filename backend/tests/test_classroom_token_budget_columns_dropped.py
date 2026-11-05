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


_CONTRACT = ("classroom", "0032_drop_class_token_budget_columns")
_BEFORE = ("classroom", "0031_class_scoring_connection_verified_at")


def _run_contract_migration(*, backwards: bool) -> None:
    """0032 하나만 되돌리거나 다시 적용한다 — 실행 기록(`django_migrations`)은 건드리지 않는다.

    예전에는 executor 로 classroom 을 0030 까지 내렸다 올렸다. 연결된 앱을 core 로 옮긴
    `core.0005`(classroom.0034 에 기댄다)와 그것에 기대는 `contests.0011` 이 생기자(#870) 그
    둘까지 함께 내려가 모델 다섯을 다시 그리느라 CPU 한도를 넘었고, classroom 의 leaf 만 다시
    올려 `contests.0011` 이 빠진 채로 남아 같은 워커의 공모전 시험이 `archived_at` 없음으로
    떨어졌다. 이 시험이 보는 것은 0032 의 되돌리기뿐이므로 그것만 돌린다 — 0031 끝의 상태는
    그 조상만 그린다."""

    loader = MigrationExecutor(connection).loader
    migration = loader.graph.nodes[_CONTRACT]
    before = loader.project_state(_BEFORE, at_end=True)
    with connection.schema_editor(atomic=migration.atomic) as editor:
        if backwards:
            migration.unapply(before, editor)
        else:
            migration.apply(before, editor)


@pytest.mark.django_db(transaction=True)
def test_contract_migration_drops_the_budget_columns_and_reverse_restores_them():
    assert _budget_columns() == set()

    _run_contract_migration(backwards=True)
    try:
        assert _budget_columns() == COLUMNS
        assert _threshold_default() == "80"
    finally:
        _run_contract_migration(backwards=False)

    assert _budget_columns() == set()
