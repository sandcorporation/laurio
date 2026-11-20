"""base(병합 대상) 코드가 새 스키마에서 도는지 보는 검사기(`scripts/ci/migration_compat.py`, #1091).

검사기는 CI 의 static 묶음이 PR 의 base 마이그레이션 목록을 받아 돌린다. 여기서는 판정 규칙을 합성 상태로,
그리고 실제 그래프 위의 두 단계(classroom 0029 → 0032)를 base 목록만 바꿔 고정한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from django.db import migrations, models
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ModelState, ProjectState

from tests.ast_scan_support import BACKEND_ROOT

_SCRIPT = BACKEND_ROOT.parent / "scripts" / "ci" / "migration_compat.py"
_spec = importlib.util.spec_from_file_location("migration_compat", _SCRIPT)
assert _spec and _spec.loader
mc = importlib.util.module_from_spec(_spec)
sys.modules["migration_compat"] = mc
_spec.loader.exec_module(mc)


def _state() -> ProjectState:
    """base 코드가 쓰는 모델 하나 — shop_item(name varchar(20), note null, flag db_default, owner FK)."""
    state = ProjectState()
    state.add_model(ModelState("auth", "user", [("id", models.AutoField(primary_key=True))]))
    state.add_model(
        ModelState(
            "shop",
            "item",
            [
                ("id", models.AutoField(primary_key=True)),
                ("name", models.CharField(max_length=20)),
                ("note", models.TextField(null=True)),
                ("flag", models.BooleanField(db_default=False)),
                ("owner", models.ForeignKey("auth.user", on_delete=models.CASCADE)),
                ("tags", models.ManyToManyField("auth.user", related_name="+")),
            ],
        )
    )
    return state


def _problems(op, state: ProjectState | None = None) -> list[str]:
    state = state or _state()
    return mc.operation_problems(op, "shop", state, mc.base_schema(_state()))


@pytest.mark.parametrize(
    "op",
    [
        migrations.RemoveField("item", "name"),
        migrations.RemoveField("item", "owner"),
        migrations.RemoveField("item", "tags"),
        migrations.DeleteModel("item"),
        migrations.RenameField("item", "name", "title"),
        migrations.RenameModel("item", "product"),
        migrations.AlterModelTable("item", "shop_product"),
        migrations.AddField("item", "price", models.IntegerField(default=0)),
        migrations.AlterField("item", "note", models.TextField()),
        migrations.AlterField("item", "name", models.IntegerField()),
        migrations.AlterField("item", "name", models.CharField(max_length=10)),
        migrations.AlterField("item", "name", models.CharField(max_length=20, unique=True)),
        migrations.AlterField("item", "flag", models.BooleanField()),
        migrations.AlterField("item", "name", models.CharField(max_length=20, db_column="title")),
        migrations.RunSQL("ALTER TABLE shop_item DROP COLUMN IF EXISTS name"),
        migrations.RunSQL("ALTER TABLE shop_item RENAME COLUMN name TO title"),
        migrations.RunSQL("ALTER TABLE shop_item ALTER COLUMN note SET NOT NULL"),
        migrations.RunSQL("DROP TABLE IF EXISTS shop_item"),
        migrations.RunSQL("TRUNCATE shop_item"),
        migrations.SeparateDatabaseAndState(database_operations=[migrations.RemoveField("item", "name")]),
    ],
    ids=lambda op: op.describe(),
)
def test_breaking_operations_on_what_base_code_uses_are_rejected(op):
    assert _problems(op)


@pytest.mark.parametrize(
    "op",
    [
        migrations.AddField("item", "price", models.IntegerField(null=True)),
        migrations.AddField("item", "price", models.IntegerField(db_default=0)),
        migrations.AddField("item", "fans", models.ManyToManyField("auth.user", related_name="+")),
        migrations.AlterField("item", "name", models.CharField(max_length=200, choices=[("a", "A")])),
        migrations.AlterField("item", "name", models.TextField()),
        migrations.AlterField("item", "note", models.TextField(null=True, help_text="바뀜")),
        migrations.AlterField("item", "name", models.CharField(max_length=20, null=True)),
        migrations.CreateModel("box", [("id", models.AutoField(primary_key=True))]),
        migrations.RunPython(migrations.RunPython.noop),
        migrations.RunSQL("UPDATE shop_item SET note = NULL"),
        migrations.RunSQL("CREATE UNIQUE INDEX shop_item_name ON shop_item (name)"),
        migrations.RunSQL("ALTER TABLE shop_item ALTER COLUMN name SET DEFAULT ''"),
        migrations.RunSQL("ALTER TABLE shop_item ALTER COLUMN name DROP NOT NULL"),
        migrations.RunSQL("ALTER TABLE shop_item ADD COLUMN price integer NULL"),
        migrations.RunSQL("ALTER TABLE shop_other DROP COLUMN name"),
        # 첫 단계: 상태에서만 지운다 — DB 는 그대로라 base 코드가 계속 읽고 쓴다
        migrations.SeparateDatabaseAndState(state_operations=[migrations.RemoveField("item", "name")]),
    ],
    ids=lambda op: op.describe(),
)
def test_compatible_operations_pass(op):
    assert _problems(op) == []


def test_operations_on_a_table_this_change_created_pass():
    state = _state()
    create = migrations.CreateModel("box", [("id", models.AutoField(primary_key=True)), ("x", models.IntegerField())])
    create.state_forwards("shop", state)
    assert _problems(migrations.RemoveField("box", "x"), state) == []
    assert _problems(migrations.AddField("box", "y", models.IntegerField(default=0)), state) == []


def test_second_step_drop_passes_once_base_no_longer_has_the_column():
    base_state = _state()
    migrations.SeparateDatabaseAndState(state_operations=[migrations.RemoveField("item", "name")]).state_forwards(
        "shop", base_state
    )
    base = mc.base_schema(base_state)
    drop = migrations.RunSQL("ALTER TABLE shop_item DROP COLUMN IF EXISTS name")
    assert mc.operation_problems(drop, "shop", base_state, base) == []


# ---------------------------------------------------------------------------- 실제 그래프


@pytest.fixture(scope="module")
def loader() -> MigrationLoader:
    return MigrationLoader(None, ignore_no_migrations=True)


@pytest.fixture(scope="module")
def all_paths(loader) -> set[str]:
    return {p for node in loader.graph.nodes if (p := mc.node_path(loader, node))}


def test_repository_migrations_are_found_under_backend(all_paths):
    assert "classroom/migrations/0029_remove_class_token_budget.py" in all_paths
    assert all(not p.startswith(".venv") for p in all_paths)


def test_nothing_new_means_nothing_to_report(loader, all_paths):
    assert mc.check(loader, all_paths) == []


def _without(loader, all_paths: set[str], name: str) -> set[str]:
    """그 마이그레이션과 그 뒤에 쌓인 것을 뺀 base — 실제 base 처럼 의존이 닫혀 있다."""
    later, todo = set(), [loader.graph.node_map[("classroom", name)]]
    while todo:
        node = todo.pop()
        if node.key not in later:
            later.add(node.key)
            todo.extend(node.children)
    return all_paths - {mc.node_path(loader, key) for key in later}


def test_two_steps_in_one_change_are_rejected_but_pass_across_two_deploys(loader, all_paths):
    first = "classroom/migrations/0029_remove_class_token_budget.py"
    second = "classroom/migrations/0032_drop_class_token_budget_columns.py"

    together = mc.check(loader, _without(loader, all_paths, "0029_remove_class_token_budget"), only={first, second})
    assert any(second in p and "token_budget" in p for p in together), together
    assert not any(first in p for p in together)

    after_first_deploy = mc.check(
        loader, _without(loader, all_paths, "0032_drop_class_token_budget_columns"), only={second}
    )
    assert after_first_deploy == []
