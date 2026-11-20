"""새 마이그레이션이 base(병합 대상) 코드와 호환되는지 본다 (#1091, spec #1079 결정 7).

**규칙: 직전 판 코드가 새 스키마에서 돌아야 한다.** 배포는 migrate 를 먼저 돌리고 옛 컨테이너가 요청을 받는
채로 겹쳐 바꾸고(ADR-0053), 자동 되돌리기(#1092)는 코드만 되돌리고 스키마는 그대로 둔다. 그래서 base 코드가
읽고 쓰는 테이블·칸을 지우거나, 이름을 바꾸거나, 그 코드의 INSERT 가 깨지게 바꾸는 마이그레이션은 거절한다.
파괴적 변경은 두 단계다 — 「코드 먼저(상태에서만 지운다), 정리는 다음 배포」(docs/ops/migrations.md).

**base 코드가 무엇을 쓰는지**는 base 에 있던 마이그레이션까지 쌓은 상태(ProjectState)로 안다 — 모델이
마이그레이션과 어긋나지 않는다는 전제다(makemigrations 가 만든다). 그래서 첫 단계(`SeparateDatabaseAndState` 로
상태에서만 지움)가 base 에 들어가 있으면 다음 PR 의 DB 정리는 base 상태에 그 칸이 없어 통과한다. 같은 PR 에
둘 다 있으면 base 상태에는 칸이 남아 있어 거절된다. 예외 표식은 두지 않는다.

보지 않는 것: 제약·고유 색인 추가(옛 코드가 새 제약을 어기는 쓰기를 할 수 있는지는 코드를 봐야 안다),
RunPython(데이터만 바꾼다고 본다). 모르는 모양의 RunSQL 은 거절한다.

    cd backend && uv run python ../scripts/ci/migration_compat.py --base origin/main
    cd backend && uv run python ../scripts/ci/migration_compat.py --base-list <파일>   # CI: base 의 마이그레이션 경로 목록

설정을 읽으므로 DJANGO_* 환경이 있어야 한다(CI 는 scripts/ci/backend-test.env). DB 에는 붙지 않는다.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.operations.base import Operation
    from django.db.migrations.state import ModelState, ProjectState
    from django.db.models import Field

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"

Node = tuple[str, str]  # (app_label, migration name)


@dataclass(frozen=True)
class Column:
    null: bool
    db_type: str | None  # 관계 칸은 None — 대상 모델을 풀어야 알 수 있어 to 로 비교한다
    target: str | None  # 관계 칸의 대상 모델("app.model"), 아니면 None
    has_db_default: bool
    unique: bool


@dataclass
class BaseSchema:
    """base 코드가 읽고 쓰는 테이블 → 칸, 그리고 자동 사이 테이블을 가진 다대다 (테이블, 필드)."""

    tables: dict[str, dict[str, Column]]
    m2m: set[tuple[str, str]]


# ---------------------------------------------------------------------------- 상태에서 DB 이름 읽기


def _connection() -> BaseDatabaseWrapper:
    from django.db import connections

    return connections["default"]


def db_table(app_label: str, model_state: ModelState) -> str:
    from django.db.backends.utils import truncate_name

    table = model_state.options.get("db_table")
    if table:
        return table
    return truncate_name(f"{app_label}_{model_state.name_lower}", _connection().ops.max_name_length())


def owns_table(model_state: ModelState) -> bool:
    """이 모델의 연산이 DB 테이블을 건드리는가 — 프록시·unmanaged 는 아니다."""
    return model_state.options.get("managed", True) and not model_state.options.get("proxy", False)


def _is_m2m(field: Field) -> bool:
    return bool(getattr(field, "many_to_many", False))


def _auto_through(field: Field) -> bool:
    through = getattr(field.remote_field, "through", None)
    return through is None or (not isinstance(through, str) and through._meta.auto_created)


def column_name(name: str, field: Field) -> str:
    if field.db_column:
        return field.db_column
    if getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False):
        return f"{name}_id"
    return name


def _target(field: Field) -> str | None:
    if not field.is_relation:
        return None
    model = field.remote_field.model
    label = model if isinstance(model, str) else model._meta.label
    return label.lower()


def describe(field: Field) -> Column:
    from django.db.models import NOT_PROVIDED

    relation = field.is_relation
    return Column(
        null=bool(field.null),
        db_type=None if relation else field.db_type(_connection()),
        target=_target(field) if relation else None,
        has_db_default=field.db_default is not NOT_PROVIDED,
        unique=bool(field.unique or field.primary_key),
    )


def base_schema(state: ProjectState) -> BaseSchema:
    tables: dict[str, dict[str, Column]] = {}
    m2m: set[tuple[str, str]] = set()
    for (app_label, _), model_state in state.models.items():
        if not owns_table(model_state):
            continue
        table = db_table(app_label, model_state)
        columns = tables.setdefault(table, {})
        for name, field in model_state.fields.items():
            if _is_m2m(field):
                if _auto_through(field):
                    m2m.add((table, name))
                continue
            columns[column_name(name, field)] = describe(field)
    return BaseSchema(tables=tables, m2m=m2m)


# ---------------------------------------------------------------------------- 판정


_VARCHAR = re.compile(r"^varchar\((\d+)\)$")


def type_change_is_compatible(old: str | None, new: str | None) -> bool:
    """옛 코드가 쓰던 값이 그대로 들어가고 그대로 읽히는가 — 같거나 varchar 를 넓히기만."""
    if old == new:
        return True
    old_m, new_m = _VARCHAR.match(old or ""), _VARCHAR.match(new or "")
    if old_m and new_m:
        return int(new_m.group(1)) >= int(old_m.group(1))
    return bool(old_m) and new == "text"


def alter_problems(old: Column, new: Column) -> list[str]:
    problems = []
    if old.null and not new.null:
        problems.append("null 을 막는다 — 옛 코드는 None 을 쓸 수 있다")
    if old.target != new.target:
        problems.append(f"관계 대상을 바꾼다({old.target} → {new.target})")
    elif not type_change_is_compatible(old.db_type, new.db_type):
        problems.append(f"칸 타입을 바꾼다({old.db_type} → {new.db_type})")
    if old.has_db_default and not new.has_db_default and not new.null:
        problems.append("DB 기본값을 지운다 — 옛 코드의 INSERT 는 그 칸을 DEFAULT 로 둔다")
    if new.unique and not old.unique:
        problems.append("고유 제약을 더한다 — 옛 코드는 같은 값을 쓸 수 있다")
    return problems


_SAFE_SQL_HEAD = re.compile(r"^(UPDATE|INSERT|DELETE|SELECT|CREATE|COMMENT|ANALYZE|VACUUM|SET|WITH)\b")
_ALTER_TABLE = re.compile(r"^ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?\"?(\w+)\"?\s+(.*)$", re.S)
_DROP_TABLE = re.compile(r"^DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(.*?)(?:\s+(?:CASCADE|RESTRICT))?$", re.S)
_DROP_COLUMN = re.compile(r"^DROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?\"?(\w+)\"?(?:\s+(?:CASCADE|RESTRICT))?$")
_ALTER_COLUMN = re.compile(r"^ALTER\s+(?:COLUMN\s+)?\"?(\w+)\"?\s+(.*)$")


def _sql_statements(sql: str | list[str | tuple[str, object]]) -> list[str]:
    items = [sql] if isinstance(sql, str) else list(sql)
    statements = []
    for item in items:
        text = item[0] if isinstance(item, (list, tuple)) else item
        for part in str(text).split(";"):
            part = re.sub(r"--[^\n]*", "", part)
            part = " ".join(part.split())
            if part:
                statements.append(part)
    return statements


def _split_actions(actions: str) -> list[str]:
    """ALTER TABLE 의 동작 목록을 쉼표로 가른다(괄호 안 쉼표는 두고)."""
    parts, depth, current = [], 0, []
    for ch in actions:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def sql_problems(sql: str | list[str | tuple[str, object]], base: BaseSchema) -> list[str]:
    problems = []
    for statement in _sql_statements(sql):
        upper = statement.upper()
        if _SAFE_SQL_HEAD.match(upper):
            continue
        drop = _DROP_TABLE.match(upper)
        if drop:
            for name in drop.group(1).split(","):
                table = name.strip().strip('"').lower()
                if table in base.tables:
                    problems.append(f"RunSQL — base 코드가 쓰는 테이블 {table} 을 지운다")
            continue
        alter = _ALTER_TABLE.match(upper)
        if not alter:
            problems.append(f"RunSQL — 판정할 수 없는 문장: {statement[:80]}")
            continue
        table = alter.group(1).lower()
        columns = base.tables.get(table)
        if columns is None:
            continue  # base 코드가 모르는 테이블
        for action in _split_actions(alter.group(2)):
            problems.extend(_alter_action_problems(table, columns, action))
    return problems


def _alter_action_problems(table: str, columns: dict[str, Column], action: str) -> list[str]:
    if action.startswith("ADD CONSTRAINT") or action.startswith("VALIDATE CONSTRAINT"):
        return []
    if action.startswith("ADD"):
        if "NOT NULL" in action and "DEFAULT" not in action:
            return [f"RunSQL — {table} 에 기본값 없는 NOT NULL 칸을 더한다"]
        return []
    drop = _DROP_COLUMN.match(action)
    if drop and not action.startswith("DROP CONSTRAINT"):
        column = drop.group(1).lower()
        return [f"RunSQL — base 코드가 쓰는 칸 {table}.{column} 을 지운다"] if column in columns else []
    alter = _ALTER_COLUMN.match(action)
    if alter:
        column, change = alter.group(1).lower(), alter.group(2)
        if column not in columns or change.startswith("DROP NOT NULL") or change.startswith("SET DEFAULT"):
            return []
        return [f"RunSQL — base 코드가 쓰는 칸 {table}.{column} 을 바꾼다({change[:40]})"]
    if action.startswith("DROP CONSTRAINT"):
        return []
    return [f"RunSQL — base 코드가 쓰는 테이블 {table} 을 바꾼다({action[:60]})"]


def operation_problems(op: Operation, app_label: str, state: ProjectState, base: BaseSchema) -> list[str]:
    """연산 하나가 base 코드를 깨뜨리는 까닭 — state 는 그 연산 직전의 상태다."""
    from django.db import migrations

    name = type(op).__name__
    if isinstance(op, migrations.SeparateDatabaseAndState):
        found = []
        db_state = state.clone()
        for inner in op.database_operations:
            found.extend(operation_problems(inner, app_label, db_state, base))
            inner.state_forwards(app_label, db_state)
        return found
    if isinstance(op, migrations.RunSQL):
        return sql_problems(op.sql, base)
    if isinstance(op, (migrations.RunPython, migrations.CreateModel)):
        return []

    model_name = getattr(op, "model_name_lower", None) or getattr(op, "name_lower", None)
    if isinstance(op, migrations.RenameModel):
        model_name = op.old_name_lower
    model_state = state.models.get((app_label, model_name)) if model_name else None
    if model_state is None or not owns_table(model_state):
        return []
    table = db_table(app_label, model_state)
    columns = base.tables.get(table)
    if columns is None:
        return []  # 이 PR 이 만든 테이블 — base 코드는 모른다

    if isinstance(op, migrations.DeleteModel):
        return [f"{name} — base 코드가 쓰는 테이블 {table} 을 지운다"]
    if isinstance(op, migrations.RenameModel):
        after = state.clone()
        op.state_forwards(app_label, after)
        new_table = db_table(app_label, after.models[(app_label, op.new_name_lower)])
        return [f"{name} — 테이블 이름을 바꾼다({table} → {new_table})"] if new_table != table else []
    if isinstance(op, migrations.AlterModelTable):
        new_table = op.table or db_table(app_label, _without_table(model_state))
        return [f"{name} — 테이블 이름을 바꾼다({table} → {new_table})"] if new_table != table else []
    if isinstance(op, migrations.RemoveField):
        field = model_state.fields[op.name]
        if _is_m2m(field):
            return [f"{name} — base 코드가 쓰는 다대다 {table}.{op.name} 을 지운다"] if (table, op.name) in base.m2m else []
        column = column_name(op.name, field)
        return [f"{name} — base 코드가 쓰는 칸 {table}.{column} 을 지운다"] if column in columns else []
    if isinstance(op, migrations.RenameField):
        field = model_state.fields[op.old_name]
        if _is_m2m(field):
            return [f"{name} — 다대다 이름을 바꾼다({op.old_name} → {op.new_name})"] if (table, op.old_name) in base.m2m else []
        old_column, new_column = column_name(op.old_name, field), column_name(op.new_name, field)
        if old_column != new_column and old_column in columns:
            return [f"{name} — 칸 이름을 바꾼다({table}.{old_column} → {new_column})"]
        return []
    if isinstance(op, migrations.AddField):
        field = op.field
        if _is_m2m(field) or field.null or describe(field).has_db_default:
            return []
        return [
            f"{name} — {table}.{column_name(op.name, field)} 를 DB 기본값 없는 NOT NULL 로 더한다 "
            "(base 코드의 INSERT 는 그 칸을 모른다 — null=True 나 db_default 를 쓴다)"
        ]
    if isinstance(op, migrations.AlterField):
        old_field = model_state.fields[op.name]
        if _is_m2m(old_field) or _is_m2m(op.field):
            return []
        old_column, new_column = column_name(op.name, old_field), column_name(op.name, op.field)
        if old_column not in columns:
            return []
        if old_column != new_column:
            return [f"{name} — 칸 이름을 바꾼다({table}.{old_column} → {new_column})"]
        return [f"{name} — {table}.{old_column}: {p}" for p in alter_problems(columns[old_column], describe(op.field))]
    return []


def _without_table(model_state: ModelState) -> ModelState:
    clone = model_state.clone()
    clone.options.pop("db_table", None)
    return clone


# ---------------------------------------------------------------------------- 그래프 걷기


def node_path(loader: MigrationLoader, node: Node) -> str | None:
    """backend/ 아래 마이그레이션이면 'app/migrations/xxxx.py', 아니면(설치된 패키지) None."""
    module = sys.modules.get(type(loader.graph.nodes[node]).__module__)
    file = getattr(module, "__file__", None)
    if not file:
        return None
    path = Path(file).resolve()
    try:
        rel = path.relative_to(BACKEND_ROOT.resolve())
    except ValueError:
        return None
    return None if ".venv" in rel.parts else rel.as_posix()


def check(loader: MigrationLoader, base_paths: set[str], only: set[str] | None = None) -> list[str]:
    """base 에 없던 backend 마이그레이션을 그래프 순서로 걸으며 base 코드를 깨뜨리는 연산을 모은다.

    only 를 주면 그 경로의 마이그레이션만 판정한다(지난 이력 훑기용).
    """
    graph = loader.graph
    plan: list[Node] = []
    seen: set[Node] = set()
    for leaf in sorted(graph.leaf_nodes()):
        for node in graph.forwards_plan(leaf):
            if node not in seen:
                seen.add(node)
                plan.append(node)
    paths = {node: node_path(loader, node) for node in plan}
    base_nodes = [n for n in plan if paths[n] is None or paths[n] in base_paths]
    new_nodes = [n for n in plan if n not in set(base_nodes)]
    if only is not None:
        new_nodes = [n for n in new_nodes if paths[n] in only]

    state = graph.make_state(nodes=base_nodes, at_end=True, real_apps=loader.unmigrated_apps)
    base = base_schema(state)
    problems = []
    for node in new_nodes:
        migration = graph.nodes[node]
        for op in migration.operations:
            for problem in operation_problems(op, node[0], state, base):
                problems.append(f"{paths[node]}: {problem}")
            op.state_forwards(node[0], state)
    return problems


def base_paths_from_git(ref: str) -> set[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", "."],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {line for line in out.splitlines() if re.fullmatch(r"[^/]+/migrations/[^/]+\.py", line)}


def load_graph() -> MigrationLoader:
    sys.path.insert(0, str(BACKEND_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.db.migrations.loader import MigrationLoader

    return MigrationLoader(None, ignore_no_migrations=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--base", help="병합 대상 git ref (예: origin/main)")
    source.add_argument("--base-list", type=Path, help="base 의 backend 마이그레이션 경로 목록 파일(한 줄에 하나)")
    args = parser.parse_args(argv)

    if args.base:
        base_paths = base_paths_from_git(args.base)
    else:
        lines = args.base_list.read_text(encoding="utf-8").splitlines()
        base_paths = {line.strip().removeprefix("backend/") for line in lines if line.strip()}
    if not base_paths:
        print("base 마이그레이션 목록이 비었다 — base ref 를 확인한다", file=sys.stderr)
        return 2

    problems = check(load_graph(), base_paths)
    if problems:
        print("base(병합 대상) 코드가 새 스키마에서 깨지는 마이그레이션이다 — 두 단계로 나눈다(docs/ops/migrations.md):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("마이그레이션 호환: base 코드가 새 스키마에서 돈다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
