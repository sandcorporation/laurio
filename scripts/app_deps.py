"""앱 의존 선언 표(`backend/app_deps.toml`)를 코드와 맞대고, 바뀐 파일 → 다시 돌 앱 집합을 낸다 — #1086, spec #1079.

    python3 scripts/app_deps.py check                  # 선언 밖 결합·순환·예외 표식·무리 규칙(Django 없이 — ORM 경로 빼고)
    python3 scripts/app_deps.py draft                  # 지금 코드에서 뽑은 선언(표를 고칠 때 견줄 것)
    python3 scripts/app_deps.py affected FILE...       # 바뀐 파일 → 다시 돌 앱(줄마다 하나, 전부면 `ALL`)
    git diff --name-only origin/main... | python3 scripts/app_deps.py affected -

결합은 두 갈래로 센다.

- **쓴다(`uses`)** — 위 앱이 아래 앱을 부른다: import(함수 안 포함, `if TYPE_CHECKING:` 아래 제외), 모델 문자열
  `"app.Model"`, 다른 앱 모듈을 가리키는 dotted path 문자열, 다른 앱의 celery 작업 이름 문자열, 다른 앱을 가리키는
  설정을 읽는 것, 아래 앱 모델로 걷는 ORM 경로.
- **꽂는다(`plugs`)** — 위 앱이 아래 앱의 자리에 제 구현을 올려, 아래 앱이 돌 때 위 앱 코드가 돈다: `Slot`·`Slots`
  `.register`, `register_*()`, 시그널 `.connect`·`@receiver`, `sender=` 로 남의 모델에 거는 것, 아래 앱이 읽는 설정의
  dotted path 가 위 앱을 가리키는 것. import 에는 안 보이고, 빠뜨리면 선택 실행이 아래 앱 시험을 놓친다.
아래 앱이 Django 역관계로 위 앱의 행을 걷는 ORM 경로(`select_related("score")`)는 받을 칸이 없다 — `uses` 에 적으면
순환이다. 위 앱이 관계 이름과 판정 함수를 아래 앱의 자리에 올린다(#1102, `contests.ports.NEXT_ACTION_RELATIONS`).

ORM 경로는 모델 관계를 알아야 해서 Django 가 뜬 경계 시험(`backend/tests/test_app_boundaries.py`)만 센다.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_import_cycles import (  # noqa: E402 — 같은 폴더의 분석기를 쓴다
    BACKEND,
    MODEL_LABEL,
    SKIP_DIRS,
    all_imports,
    apps,
    strongly_connected,
    targets,
)

TABLE = BACKEND / "app_deps.toml"
SETTINGS = BACKEND / "config" / "settings.py"
GROUPS = ("shared", "contest", "classroom")
KINDS = ("uses", "plugs")
#: 다시 돌 앱을 고를 수 없는 바뀐 파일(config/·tests/·pyproject·이 표 …) — 모든 앱이 기댄다
ALL = "ALL"
#: 이 부름의 문자열 인자는 결합이 아니다 — `Slot("이름", "ops_metrics.apps")` 의 둘째 인자는 올리는 곳을 적은 글이고
#: (결합은 올리는 쪽의 `register` 로 센다), `getLogger("payments.charges")` 는 운영 로그 검색이 잡는 이름이다
NOT_COUPLING_CALLS = {"Slot": 1, "Slots": 1, "getLogger": 0}
#: 주석 안의 표식만 센다 — 문서가 이 이름을 말하는 것은 표식이 아니다
MARKER_RE = re.compile(r"#.*APP-BOUNDARY-EXCEPTION")
DOTTED = re.compile(r"^([a-z_][a-z0-9_]*)((?:\.[A-Za-z_][A-Za-z0-9_]*)+)$")
#: ORM 경로가 놓이는 부름 — 위치 인자의 `"score"` 처럼 `__` 없는 이름도 경로다
ORM_CALLS = frozenset(
    {
        "filter", "exclude", "get", "get_or_create", "update_or_create", "Q", "F", "OuterRef",
        "select_related", "prefetch_related", "Prefetch", "values", "values_list", "only", "defer",
        "order_by", "Count", "Sum", "Max", "Min", "Avg",
    }
)
LOOKUP = re.compile(r"^-?[a-z_][a-z0-9_]*(?:__[a-z0-9_]+)*$")

#: (시작이 될 수 있는 앱들, 경로 조각, 사슬 맨 앞 이름) → 그럴듯한 시작 모델 모두가 지나는 앱, 시작 모델이 없으면 None
Resolver = Callable[[frozenset[str], list[str], "str | None"], "set[str] | None"]


@dataclass(frozen=True)
class Coupling:
    """한 파일이 다른 앱에 묶이는 한 자리. `kind` 는 `uses`·`plugs`·`orm`(·가르기 전 `setting`)."""

    src: str
    dst: str
    kind: str
    path: str
    line: int
    how: str

    def where(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Context:
    """파일 하나를 읽을 때 저장소 전체에서 알아 둘 것."""

    known: frozenset[str]
    #: 설정 이름 → 그 값이 가리키는 앱들
    settings_apps: dict[str, frozenset[str]]
    #: celery 작업 이름 → 그 작업을 가진 앱
    task_apps: dict[str, str]


@dataclass(frozen=True)
class Source:
    app: str
    path: str
    text: str
    tree: ast.Module


# --- 파일 하나 ---------------------------------------------------------------------


def _module_exists(dotted: str) -> bool:
    """`app.mod.Name` 의 모듈 부분(`app.mod`, 앱 이름만은 아니다)이 backend 안 파일·패키지면 참."""

    parts = dotted.split(".")
    for end in range(len(parts), 1, -1):
        base = BACKEND.joinpath(*parts[:end])
        if base.with_suffix(".py").is_file() or (base / "__init__.py").is_file():
            return True
    return False


def _imported_names(tree: ast.AST, own: str, known: frozenset[str]) -> dict[str, str]:
    """이 파일 안 이름 → 그 이름을 내준 다른 앱(`from b.x import NAME`, `import b.x as m`)."""

    names: dict[str, str] = {}
    for node in all_imports(tree):
        for target in targets(node, own):
            if target not in known or target == own:
                continue
            for alias in node.names:
                if isinstance(node, ast.Import):
                    names[alias.asname or alias.name.split(".")[0]] = target
                else:
                    names[alias.asname or alias.name] = target
    return names


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _call_name(func: ast.expr) -> str | None:
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def _not_coupling_args(tree: ast.AST) -> set[int]:
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (start := NOT_COUPLING_CALLS.get(_call_name(node.func) or "")) is not None:
            skip.update(id(arg) for arg in node.args[start:])
    return skip


def file_couplings(source: str, *, app: str, path: str, ctx: Context, tree: ast.AST | None = None) -> list[Coupling]:
    """소스 하나가 다른 앱에 묶이는 자리(ORM 경로 빼고). 파일을 읽지 않는다 — 합성 소스로 빨강을 고정할 수 있게."""

    tree = tree if tree is not None else ast.parse(source)
    found: list[Coupling] = []

    def add(dst: str, kind: str, line: int, how: str) -> None:
        if dst != app and dst in ctx.known:
            found.append(Coupling(app, dst, kind, path, line, how))

    for node in all_imports(tree):
        for target in targets(node, app):
            add(target, "uses", node.lineno, "import")

    imported = _imported_names(tree, app, ctx.known)
    skip = _not_coupling_args(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            text = node.value
            if (m := MODEL_LABEL.match(text)) and m.group(1) in ctx.known:
                add(m.group(1), "uses", node.lineno, f'모델 문자열 "{text}"')
            elif (m := DOTTED.match(text)) and m.group(1) in ctx.known and _module_exists(text):
                add(m.group(1), "uses", node.lineno, f'dotted path "{text}"')
            if text in ctx.task_apps:
                add(ctx.task_apps[text], "uses", node.lineno, f'celery 작업 "{text}"')
            for owner in ctx.settings_apps.get(text, ()):
                add(owner, "setting", node.lineno, f"설정 {text}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "settings":
            for owner in ctx.settings_apps.get(node.attr, ()):
                add(owner, "setting", node.lineno, f"설정 {node.attr}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"register", "connect"}:
                if owner := imported.get(_root_name(func.value) or ""):
                    add(owner, "plugs", node.lineno, f".{func.attr}()")
            elif isinstance(func, ast.Name) and func.id.startswith("register") and func.id in imported:
                add(imported[func.id], "plugs", node.lineno, f"{func.id}()")
            elif isinstance(func, ast.Name) and func.id == "receiver":
                for arg in node.args:
                    if owner := imported.get(_root_name(arg) or ""):
                        add(owner, "plugs", node.lineno, "@receiver")
            for kw in node.keywords:
                if kw.arg == "sender" and (owner := imported.get(_root_name(kw.value) or "")):
                    add(owner, "plugs", node.lineno, "sender=")
    return found


def orm_paths(tree: ast.AST) -> list[tuple[str, int, str | None]]:
    """ORM 경로 후보(문자열, 줄, 부름 사슬 맨 앞 이름): 부름의 `__` 키워드와 `__` 가 든 문자열 전부, 그리고 ORM 부름의
    이름 인자·키워드. 맨 앞 이름(`ContestSubmission.objects.filter(…)` 의 `ContestSubmission`)은 시작 모델을 좁힌다."""

    found: list[tuple[str, int, str | None]] = []
    in_call: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        orm = _call_name(node.func) in ORM_CALLS
        root = _root_name(node.func) if orm and isinstance(node.func, ast.Attribute) else None
        for kw in node.keywords:
            if kw.arg and ("__" in kw.arg or orm):
                found.append((kw.arg, node.lineno, root))
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and LOOKUP.match(arg.value):
                if orm or "__" in arg.value:
                    found.append((arg.value, arg.lineno, root))
                    in_call.add(id(arg))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in in_call:
            if "__" in node.value and LOOKUP.match(node.value) and not node.value.startswith("__"):
                found.append((node.value, node.lineno, None))
    return found


def orm_couplings(sources: Iterable[Source], table: dict[str, Declared], resolve: Resolver) -> list[Coupling]:
    """앱마다 ORM 경로가 지나는 다른 앱. 시작 모델은 그 앱과 그 앱이 쓰는 앱의 것 — 그럴듯한 시작 모두가 지나는 앱만 센다
    (`score__gte` 가 제 모델의 정수 칸인지 남의 역관계인지 모를 때 세지 않는다)."""

    found: list[Coupling] = []
    for src in sources:
        declared = table.get(src.app)
        starts = frozenset({src.app} | (declared.uses if declared else frozenset()))
        for text, line, root in orm_paths(src.tree):
            reached = resolve(starts, text.lstrip("-").split("__"), root)
            for dst in sorted((reached or set()) - {src.app}):
                if dst in table:
                    found.append(Coupling(src.app, dst, "orm", src.path, line, f"ORM 경로 {text}"))
    return found


def django_resolver() -> Resolver:
    """Django 가 뜬 뒤에 부른다 — 모든 모델의 칸 이름으로 경로를 걷는다."""

    from django.apps import apps as registry

    fields = {
        model: {name: f for f in model._meta.get_fields() for name in {f.name, getattr(f, "attname", f.name)}}
        for model in registry.get_models()
    }

    def walk(model: type, segs: list[str]) -> set[str]:
        seen: set[str] = set()
        for seg in segs:
            f = fields.get(model, {}).get(seg)
            if f is None or not f.is_relation or f.related_model is None:
                break
            model = f.related_model
            seen.add(model._meta.app_label)
        return seen

    def resolve(starts: frozenset[str], segs: list[str], root: str | None) -> set[str] | None:
        candidates = [m for m in fields if m._meta.app_label in starts and segs[0] in fields[m]]
        named = [m for m in candidates if m.__name__ == root]
        reached = [walk(m, segs) for m in named or candidates]
        return set.intersection(*reached) if reached else None

    return resolve


def markers(source: str) -> list[int]:
    return [i for i, line in enumerate(source.split("\n"), 1) if MARKER_RE.search(line)]


# --- 저장소 ------------------------------------------------------------------------


def _settings_apps(known: frozenset[str]) -> dict[str, frozenset[str]]:
    """`config/settings.py` 의 대문자 이름마다 그 값 안의 dotted path 가 가리키는 앱."""

    out: dict[str, frozenset[str]] = {}
    tree = ast.parse(SETTINGS.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        names = [t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)]
        pointed = {
            m.group(1)
            for c in ast.walk(node.value)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
            and (m := DOTTED.match(c.value)) and m.group(1) in known and _module_exists(c.value)
        }
        for name in names:
            if name.isupper() and pointed:
                out[name] = frozenset(pointed)
    return out


def _task_apps(sources: Iterable[Source]) -> dict[str, str]:
    """`@shared_task(name="…")`·`@app.task(name="…")` 의 이름 → 그 작업을 가진 앱."""

    out: dict[str, str] = {}
    for src in sources:
        for node in ast.walk(src.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call):
                        for kw in deco.keywords:
                            if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                out[kw.value.value] = src.app
    return out


def app_sources() -> list[Source]:
    """앱 코드 전부 — `tests/`·`migrations/` 는 앱 코드가 아니라 뺀다."""

    out: list[Source] = []
    for app in sorted(apps()):
        for path in sorted((BACKEND / app).rglob("*.py")):
            rel = path.relative_to(BACKEND)
            if SKIP_DIRS & set(rel.parts):
                continue
            text = path.read_text(encoding="utf-8")
            out.append(Source(app, str(rel), text, ast.parse(text, filename=str(rel))))
    return out


def repository_couplings(sources: list[Source]) -> tuple[list[Coupling], list[str]]:
    """(ORM 경로 밖 결합 전부, 예외 표식 자리). `setting` 은 `classify` 가 가른다."""

    known = frozenset(apps())
    ctx = Context(known, _settings_apps(known), _task_apps(sources))
    found: list[Coupling] = []
    marked: list[str] = []
    for src in sources:
        found += file_couplings(src.text, app=src.app, path=src.path, ctx=ctx, tree=src.tree)
        marked += [f"{src.path}:{n}" for n in markers(src.text)]
    return found, marked


# --- 선언 표 ------------------------------------------------------------------------


@dataclass(frozen=True)
class Declared:
    group: str
    uses: frozenset[str] = frozenset()
    plugs: frozenset[str] = frozenset()


def load_table(path: Path = TABLE) -> dict[str, Declared]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return {app: Declared(entry["group"], *(frozenset(entry.get(k, [])) for k in KINDS)) for app, entry in raw.items()}


def classify(found: Iterable[Coupling], table: dict[str, Declared]) -> list[Coupling]:
    """설정 결합을 가른다: 읽는 앱이 그 앱을 `uses` 로 선언했으면 쓰는 것, 아니면 가리켜진 앱이 읽는 앱에 꽂는 것."""

    out: list[Coupling] = []
    for c in found:
        if c.kind != "setting":
            out.append(c)
        elif c.src in table and c.dst in table[c.src].uses:
            out.append(Coupling(c.src, c.dst, "uses", c.path, c.line, c.how))
        else:
            out.append(Coupling(c.dst, c.src, "plugs", c.path, c.line, f"{c.how} 이(가) {c.dst} 를 가리킨다"))
    return out


def problems(
    table: dict[str, Declared],
    found: Iterable[Coupling],
    marked: Iterable[str],
    installed: set[str],
    *,
    orm_counted: bool = True,
) -> list[str]:
    """표가 코드와 어긋나는 것 전부 — 사람이 읽을 문장으로. `orm_counted` 가 거짓이면(Django 없이) ORM 경로에만 기댄
    선언이 「코드에 없다」로 읽히므로 남는 선언은 따지지 않는다."""

    out = [f"{where}: `APP-BOUNDARY-EXCEPTION` 표식은 더 받지 않는다 — 선언 표에 적거나 자리(core.registry)로 뒤집는다" for where in marked]
    out += [f"{app}: 표에 없다 — backend/app_deps.toml 에 group·uses·plugs 를 적는다" for app in sorted(installed - set(table))]
    for app, d in sorted(table.items()):
        if d.group not in GROUPS:
            out.append(f"{app}: group 은 {GROUPS} 중 하나다 — {d.group!r}")
        for dst in sorted((d.uses | d.plugs) - set(table)):
            out.append(f"{app}: 표에 없는 앱 {dst} 를 적었다")
        if app in d.uses | d.plugs:
            out.append(f"{app}: 저 자신을 적었다")

    seen: dict[tuple[str, str, str], list[Coupling]] = defaultdict(list)
    for c in found:
        seen[(c.src, c.dst, c.kind)].append(c)
    for (src, dst, kind), cs in sorted(seen.items()):
        d = table.get(src)
        if d is None:
            continue
        allowed = d.plugs if kind == "plugs" else d.uses
        if dst not in allowed:
            sites = ", ".join(f"{c.where()}({c.how})" for c in cs[:4]) + (" …" if len(cs) > 4 else "")
            fix = (
                f"{dst} 가 {src} 아래면 {src} uses 에 적고, 위면 관계 이름을 {dst} 가 {src} 의 자리에 올린다"
                f"(contests.ports.NEXT_ACTION_RELATIONS 꼴)"
                if kind == "orm"
                else f"backend/app_deps.toml 의 {src} {kind} 에 적거나 결합을 푼다"
            )
            out.append(f"{src} → {dst}: 선언 밖 결합 — {sites}. {fix}")

    backed = {(s, d, k) for (s, d, k) in seen}
    for app, d in sorted(table.items()):
        stale = {
            "uses": {x for x in d.uses if (app, x, "uses") not in backed and (app, x, "orm") not in backed},
            "plugs": {x for x in d.plugs if (app, x, "plugs") not in backed},
        }
        if not orm_counted:
            stale["uses"] = set()
        for kind, xs in stale.items():
            out += [f"{app}.{kind} 의 {x}: 코드에 그런 결합이 없다 — 표에서 지운다(선언은 좁게)" for x in sorted(xs)]

    out += group_problems(table)
    layered = {app: set(d.uses | d.plugs) & set(table) for app, d in table.items()}
    out += [
        f"순환: {' '.join(comp)} — 한 방향 층만 허용한다(uses·plugs 모두 위 → 아래)"
        for comp in strongly_connected(layered)
        if len(comp) > 1
    ]
    return out


def group_problems(table: dict[str, Declared]) -> list[str]:
    """무리 규칙 둘: 공유층은 기능 앱에 묶이지 않는다(꽂힐 수는 있다 — 꽂는 쪽이 위다), 강의실 ↮ 공모전 가족."""

    out: list[str] = []
    for app, d in sorted(table.items()):
        for dst in sorted(d.uses | d.plugs):
            other = table.get(dst)
            if other is None:
                continue
            if d.group == "shared" and other.group != "shared":
                out.append(f"{app} → {dst}: 공유층이 기능 앱에 묶인다 — 공유층에 자리를 두고 {dst} 가 올린다")
            if {d.group, other.group} == {"contest", "classroom"}:
                out.append(f"{app} → {dst}: 강의실과 공모전은 서로를 부를 수 없다 — 공유층으로 옮기거나 각자 갖는다(ADR-0037)")
    return out


def draft(found: Iterable[Coupling], table: dict[str, Declared]) -> str:
    """지금 코드가 말하는 표. ORM 경로는 Django 없이 못 센다 — 아래 앱으로 걷는 ORM 경로는 import 와 겹쳐 대개 잡힌다."""

    acc: dict[str, dict[str, set[str]]] = {app: {k: set() for k in KINDS} for app in sorted(apps())}
    for c in found:
        acc[c.src]["uses" if c.kind == "orm" else c.kind].add(c.dst)
    lines: list[str] = []
    for app, kinds in sorted(acc.items()):
        lines += [f"[{app}]", f'group = "{table[app].group if app in table else "?"}"']
        lines += [f"{k} = [" + ", ".join(f'"{x}"' for x in sorted(kinds[k])) + "]" for k in KINDS]
        lines.append("")
    return "\n".join(lines)


# --- 다시 돌 앱 ---------------------------------------------------------------------


def affected(changed: Iterable[str], table: dict[str, Declared]) -> set[str] | None:
    """바뀐 파일(저장소 기준 경로) → 시험을 다시 돌 앱. 고를 수 없으면 None(전부).

    바뀐 앱, 그 앱을 쓰는 앱(닫힘), 그리고 그 앱들이 꽂힌 앱 — 꽂힌 앱은 제 시험만 다시 돌고 거기서 더 번지지
    않는다. 꽂힌 자리는 그 앱 코드가 부르고, 그 앱을 쓰는 앱마다 번지면 모두가 기대는 `core` 의 등록부(스캔·지표) 탓에
    무엇을 바꿔도 전부가 된다. backend 밖(프런트·문서)은 고르지 않는다.
    """

    users: dict[str, set[str]] = defaultdict(set)
    for app, d in table.items():
        for dst in d.uses:
            users[dst].add(app)

    seeds: set[str] = set()
    for name in changed:
        parts = Path(name.strip()).parts
        if not parts or parts[0] != "backend":
            continue
        if len(parts) > 2 and parts[1] in table:
            seeds.add(parts[1])
        else:
            return None

    out: set[str] = set()
    stack = list(seeds)
    while stack:
        app = stack.pop()
        if app not in out:
            out.add(app)
            stack += users[app]
    return out | {dst for app in out for dst in table[app].plugs}


def installed_apps() -> set[str]:
    """`INSTALLED_APPS` 중 django.contrib 밖의 것 — 설정을 불러오지 않고 글자로 읽는다."""

    tree = ast.parse(SETTINGS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "INSTALLED_APPS" for t in node.targets):
            return {
                c.value
                for c in ast.walk(node.value)
                if isinstance(c, ast.Constant) and isinstance(c.value, str) and "." not in c.value
            }
    raise SystemExit("config/settings.py 에서 INSTALLED_APPS 를 찾지 못했다")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("draft")
    aff = sub.add_parser("affected")
    aff.add_argument("files", nargs="+", help="바뀐 파일(저장소 기준). `-` 면 표준 입력에서 줄마다")
    args = parser.parse_args()

    table = load_table() if TABLE.exists() else {}
    if args.cmd == "affected":
        files = sys.stdin.read().split() if args.files == ["-"] else args.files
        picked = affected(files, table)
        print(ALL if picked is None else "\n".join(sorted(picked)))
        return 0
    raw, marked = repository_couplings(app_sources())
    found = classify(raw, table)
    if args.cmd == "draft":
        print(draft(found, table))
        return 0
    issues = problems(table, found, marked, installed_apps(), orm_counted=False)
    print("\n".join(issues) if issues else f"앱 {len(table)}개, 선언과 코드가 맞다(ORM 경로는 경계 시험이 센다)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
