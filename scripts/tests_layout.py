#!/usr/bin/env python3
"""백엔드 시험 파일을 앱 폴더로 옮긴다 — 다시 돌릴 수 있다(#1087).

    python3 scripts/tests_layout.py plan    # 어디로 갈지와 까닭만 보인다(아무것도 안 바꾼다)
    python3 scripts/tests_layout.py apply   # git mv·참조 고치기·앱 시험 꾸러미·시간 기록 키 고치기

본 저장소 main 을 당겨 `backend/tests/` 에 새 시험이 생기면 다시 돌린다. 이미 옮긴 파일도 다시 재고 자리가 바뀌었으면
옮기며, 시험 모듈을 가리키는 참조(`tests.test_x`·`<앱>.tests.test_x`)는 모두 지금 자리로 고친다.

어디로 가는가 — 파일이 닿는 앱으로 정한다. 닿는 앱은 import 하는 앱(헬퍼·다른 시험 파일을 거친 것 포함 — 다른
시험 파일은 통째로)과 부르는 주소의 앱(`config/routes.py` 의 라우터 선언과 맞춰 본다 — 다른 시험 파일에서는 가져온
이름이 부르는 주소만)이다:

- `<앱>/tests/`  닿는 앱이 모두 그 앱이거나 그 앱이 쓰는 아래 앱(`app_deps.toml` 의 `uses` 닫힘)이다. 앱 시험의
                 주소도 그 범위(`tests/app_urls.py`)고, 아래 앱이 바뀌면 그 앱이 다시 돈다(`app_deps.py affected`).
- `tests/integration/`  그런 앱이 없다 — 옆 앱·위 앱에 닿는 앱 사이 흐름.
- `tests/` 그대로   앱에 닿지 않거나(저장소 구조 시험) 전체 주소(`config.urls`·`/api/health` 등)에 기댄다.

손으로 정할 파일은 `OVERRIDES` 에 적는다.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"
INTEGRATION = "integration"
STAY = "tests"
DURATIONS = ROOT / "scripts" / "ci" / "pytest-durations.json"

sys.path.insert(0, str(ROOT / "scripts"))
from app_deps import load_table  # noqa: E402

#: 손으로 정한 자리 — 파일 이름 → 앱 이름 · "integration" · "tests"(그대로)
OVERRIDES: dict[str, str] = {
    # 저장소 전체의 앱 경계·공유층을 재는 구조 시험 — 어느 한 앱의 시험이 아니다
    "test_app_boundaries.py": STAY,
    "test_shared_layer_ports.py": STAY,
    "test_runtime_settings_port.py": STAY,
    # 정적으로 안 보이는 주소를 부른다 — 시드 명령이 안에서 운영자 주소를 친다, 헬퍼가 주소를 조립한다
    "test_e2e_seed_api.py": INTEGRATION,
    "test_operator_free_contests.py": INTEGRATION,
}

#: 앱이 아니라 전체 주소에 붙는 것
CONFIG_URLS = ("/api/health", "/api/openapi.json", "/api/docs", "/metrics")
CONFIG_MODULES = ("config.api", "config.urls")

DOTTED = re.compile(r"^([a-z_][a-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_.]*$")
HOLE = "\x00"


# --- 주소 → 앱 ---------------------------------------------------------------


def _route_regex(full: str) -> re.Pattern[str]:
    out, pos = "", 0
    for m in re.finditer(r"\{([^}]*)\}", full):
        out += re.escape(full[pos : m.start()])
        out += ".+" if m.group(1).startswith("path:") else "[^/]+"
        pos = m.end()
    out += re.escape(full[pos:])
    return re.compile(f"^{out}/?$")


def _router_paths(module: str, var: str) -> list[str]:
    file = BACKEND.joinpath(*module.split(".")).with_suffix(".py")
    tree = ast.parse(file.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                continue
            owner = deco.func.value
            if not (isinstance(owner, ast.Name) and owner.id == var):
                continue
            args = deco.args[1:] if deco.func.attr == "api_operation" else deco.args
            if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                out.append(args[0].value)
    return out


def _routes_module() -> ast.Module:
    return ast.parse((BACKEND / "config" / "routes.py").read_text(encoding="utf-8"))


def route_table() -> list[tuple[re.Pattern[str], str]]:
    """(주소 정규식, 앱) — `config/routes.py` 의 표 순서대로(먼저 붙은 쪽이 이긴다)."""

    out: list[tuple[re.Pattern[str], str]] = [(re.compile("^" + re.escape(u) + "/?$"), "config") for u in CONFIG_URLS]
    for node in ast.walk(_routes_module()):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        consts = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if node.func.id == "Mount" and len(consts) == 2:
            prefix, dotted = consts
            module, var = dotted.rsplit(".", 1)
            app = dotted.split(".", 1)[0]
            out += [(_route_regex(f"/api{prefix}{p}"), app) for p in _router_paths(module, var)]
        elif node.func.id == "View" and len(consts) == 2:
            out.append((_route_regex("/" + consts[0]), consts[1].split(".", 1)[0]))
    return out


def _url_literals(tree: ast.AST) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else HOLE for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        if text.startswith(("/api/", "/metrics")):
            out.append(text.split("?", 1)[0])
    return out


def url_apps(urls: Iterable[str], table: list[tuple[re.Pattern[str], str]]) -> tuple[set[str], list[str]]:
    found: set[str] = set()
    unknown: list[str] = []
    for url in urls:
        sample = url.replace(HOLE, "x1")
        for regex, app in table:
            if regex.match(sample):
                found.add(app)
                break
        else:
            if HOLE not in url.split("/api/", 1)[-1][:1]:
                unknown.append(url)
    return found, unknown


# --- 파일 하나 ---------------------------------------------------------------


#: 시험 꾸러미 안의 모듈 — `tests.x` · `tests.integration.x` · `<앱>.tests.x` (+ 그 안의 이름)
TEST_REF = re.compile(r"^(?:[a-z_]+\.)?tests(?:\.integration)?\.(\w+)(?:\.(\w+))?")
TEST_PKG = re.compile(r"^(?:[a-z_]+\.)?tests(?:\.integration)?$")


@dataclass
class Info:
    name: str
    tree: ast.Module
    apps: set[str] = field(default_factory=set)
    #: 시험 꾸러미의 모듈 → 가져온 이름(None 이면 모듈 통째)
    deps: dict[str, set[str] | None] = field(default_factory=dict)
    #: 이 파일의 이름 → (가져온 모듈, 그 모듈의 이름)
    aliases: dict[str, tuple[str, str]] = field(default_factory=dict)
    config: bool = False


def _need(info: Info, dep: str, name: str | None) -> None:
    if name is None or info.deps.get(dep, set()) is None:
        info.deps[dep] = None
    else:
        info.deps.setdefault(dep, set()).add(name)  # type: ignore[union-attr]


def scan(path: Path, apps: frozenset[str]) -> Info:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    info = Info(path.stem, tree)
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = f"tests.{module}" if module else "tests"
            ref = TEST_REF.match(module)
            if TEST_PKG.match(module):  # from tests import test_x (as y) — 모듈 통째
                for a in node.names:
                    _need(info, a.name, None)
            elif ref and not ref.group(2):
                for a in node.names:
                    _need(info, ref.group(1), a.name)
                    info.aliases[a.asname or a.name] = (ref.group(1), a.name)
            else:
                modules = [module]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            ref = TEST_REF.match(node.value)
            if ref and DOTTED.match(node.value):
                _need(info, ref.group(1), ref.group(2))
            elif DOTTED.match(node.value) and node.value.split(".", 1)[0] in apps:
                modules = [node.value]
        for name in modules:
            ref = TEST_REF.match(name)
            if ref:
                _need(info, ref.group(1), None)
            elif name.split(".", 1)[0] in apps:
                info.apps.add(name.split(".", 1)[0])
            elif name.startswith(CONFIG_MODULES):
                info.config = True
    return info


def _top_level(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node
    return out


def reach(stem: str, names: set[str] | None, infos: dict[str, Info], seen: set[tuple[str, str]]) -> tuple[set[str], list[str], bool]:
    """(앱, 주소, 전체 주소에 기대는가) — 모듈 `stem` 의 `names`(None 이면 통째)가 닿는 것.

    다른 시험 파일에서는 가져온 이름과 그 이름이 부르는 같은 파일의 이름만 따라간다 — 헬퍼 하나 때문에 그 파일이
    부르는 주소 전부를 물려받지 않게. 앱은 모듈 통째로 센다(빠뜨리면 선택 실행이 이 시험을 놓친다).
    """

    info = infos.get(stem)
    if info is None:
        return set(), [], False
    apps, urls, config = set(info.apps), [], info.config
    if names is None:
        if (stem, "*") in seen:
            return apps, urls, config
        seen.add((stem, "*"))
        urls += _url_literals(info.tree)
        follow: list[tuple[str, set[str] | None]] = list(info.deps.items())
    else:
        top = _top_level(info.tree)
        todo, follow = list(names), []
        while todo:
            name = todo.pop()
            if (stem, name) in seen:
                continue
            seen.add((stem, name))
            if name in info.aliases:
                follow.append((info.aliases[name][0], {info.aliases[name][1]}))
            node = top.get(name)
            if node is None:
                continue
            urls += _url_literals(node)
            todo += [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id != name]
        # 모듈 통째로 가져온 것(`from tests import test_x as y`)·문자열로 가리킨 것은 이 파일 몫 그대로 따라간다
        follow += [(d, n) for d, n in info.deps.items() if n is None]
    for dep, dep_names in follow:
        sub_apps, sub_urls, sub_config = reach(dep, dep_names, infos, seen)
        apps |= sub_apps
        urls += sub_urls
        config |= sub_config
        # 앱은 모듈 통째로
        if dep in infos:
            apps |= _module_apps(dep, infos, set())
    return apps, urls, config


def _module_apps(stem: str, infos: dict[str, Info], seen: set[str]) -> set[str]:
    if stem in seen or stem not in infos:
        return set()
    seen.add(stem)
    out = set(infos[stem].apps)
    for dep in infos[stem].deps:
        out |= _module_apps(dep, infos, seen)
    return out


@dataclass
class Placement:
    dest: str  # 앱 이름 · "integration" · "tests"
    why: str


def below(app: str, table: dict) -> set[str]:
    """앱과 그 앱이 쓰는(`uses`, 닫힘) 아래 앱 — 앱 시험의 주소가 붙는 범위(`tests/app_urls.py`)."""

    out, stack = set(), [app]
    while stack:
        x = stack.pop()
        if x not in out:
            out.add(x)
            stack += table[x].uses
    return out


def place(name: str, reached: tuple[set[str], list[str], bool], table: dict, routes: list) -> Placement:
    if f"{name}.py" in OVERRIDES:
        return Placement(OVERRIDES[f"{name}.py"], "손으로 정함(OVERRIDES)")
    apps, urls, config = reached
    uapps, _ = url_apps(urls, routes)
    if config or "config" in uapps:
        return Placement(STAY, "전체 주소(config)에 기댄다")
    used = apps | uapps
    if not used:
        return Placement(STAY, "앱을 import 하지 않는다(구조)")
    # 그 앱의 시험이 되려면 닿는 앱이 모두 그 앱이거나 그 앱이 쓰는 아래 앱이어야 한다 — 앱 시험의 주소도 그
    # 범위(`tests/app_urls.py`)고, 아래 앱이 바뀌면 그 앱이 다시 돈다(`app_deps.py affected`). 그런 앱은 많아야 하나다
    # (둘이면 서로의 아래라 순환이다).
    cands = [x for x in sorted(used) if used <= below(x, table)]
    if cands:
        return Placement(cands[0], ("주소·import " if uapps else "import ") + ",".join(sorted(used)))
    return Placement(INTEGRATION, "닿는 앱을 다 아래에 두는 앱이 없다: " + ",".join(sorted(used)))


# --- 계획 --------------------------------------------------------------------


def _module_files() -> dict[str, Path]:
    """`tests.<이름>` 로 불리던 모듈 → 지금 파일(옮긴 시험 포함)."""

    out = {p.stem: p for p in TESTS.glob("*.py")}
    for p in sorted(BACKEND.glob("*/tests/test_*.py")) + sorted((TESTS / INTEGRATION).glob("test_*.py")):
        out.setdefault(p.stem, p)
    return out


def plan() -> dict[str, Placement]:
    table = load_table()
    apps = frozenset(table)
    routes = route_table()
    files = _module_files()
    infos = {stem: scan(p, apps) for stem, p in files.items()}
    return {
        p.name: place(p.stem, reach(p.stem, None, infos, set()), table, routes)
        for p in sorted(files.values(), key=lambda p: p.name)
        if p.name.startswith("test_")
    }


def touched() -> dict[str, set[str] | None]:
    """시험 파일(backend 기준 경로) → 닿는 앱(import·주소, 자리를 정한 것과 같은 규칙). pytest 선택 실행(#1088)이 읽는다.

    None 은 「다 안 보인다」 — 전체 주소(config)에 기대거나, 정적으로 안 보이는 주소를 불러 자리를 손으로 정한
    파일(OVERRIDES)이다. 고르는 쪽은 None 을 늘 돌린다.
    """

    table = load_table()
    routes = route_table()
    files = _module_files()
    infos = {stem: scan(p, frozenset(table)) for stem, p in files.items()}
    out: dict[str, set[str] | None] = {}
    for p in files.values():
        if not p.name.startswith("test_"):
            continue
        rel = p.relative_to(BACKEND).as_posix()
        if p.name in OVERRIDES:
            out[rel] = None
            continue
        apps, urls, config = reach(p.stem, None, infos, set())
        uapps, _ = url_apps(urls, routes)
        out[rel] = None if config or "config" in uapps else apps | uapps
    return out


def target(dest: str, name: str) -> Path:
    if dest == STAY:
        return TESTS / name
    if dest == INTEGRATION:
        return TESTS / INTEGRATION / name
    return BACKEND / dest / "tests" / name


def module_of(path: Path) -> str:
    return ".".join(path.relative_to(BACKEND).with_suffix("").parts)


# --- 고치기 -------------------------------------------------------------------

_FILE_PARENTS = re.compile(r"(Path\(__file__\)(?:\.resolve\(\))?)((?:\.parent)+)(?!\w)")
_FILE_PARENTS_N = re.compile(r"(Path\(__file__\)(?:\.resolve\(\))?\.parents\[)(\d+)(\])")


def deepen(text: str) -> str:
    """한 층 깊어진 파일의 `Path(__file__)` 기준 경로를 고친다. `.parent` 하나는 `tests/` 폴더를 뜻했다."""

    def parents(m: re.Match[str]) -> str:
        k = m.group(2).count(".parent")
        if k == 1:
            return 'Path(__file__).resolve().parents[2].joinpath("tests")'
        return m.group(1) + ".parent" * (k + 1)

    # `parents[N]` 먼저 — `.parent` 하나를 바꾼 `parents[2]` 를 다시 늘리지 않게
    text = _FILE_PARENTS_N.sub(lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}", text)
    return _FILE_PARENTS.sub(parents, text)


#: 시험이 있던·있는 꾸러미 — `tests` · `tests.integration` · `<앱>.tests`
_PKG = r"(?:[a-z_]+\.)?tests(?:\.integration)?"


def relink(text: str, where: dict[str, str]) -> str:
    """시험 모듈 참조(import·문자열·`from <꾸러미> import test_x`)를 그 시험의 지금 자리로 — 옮긴 뒤 되돌려도 맞는다."""

    text = re.sub(r"(?<![\w.])" + _PKG + r"\.(test_\w+)", lambda m: where.get(m.group(1), m.group(0)), text)

    def from_pkg(m: re.Match[str]) -> str:
        indent, name = m.group(1), m.group(2)
        if name not in where:
            return m.group(0)
        pkg, mod = where[name].rsplit(".", 1)
        return f"{indent}from {pkg} import {mod}"

    return re.sub(r"^(\s*)from " + _PKG + r" import (test_\w+)", from_pkg, text, flags=re.M)


def relative_helpers(text: str) -> str:
    return re.sub(r"^(\s*)from \.(\w+) import", r"\1from tests.\2 import", text, flags=re.M)


APP_URLS = '''"""{app} 시험의 주소 — {app} 의 라우터·뷰만(#1087, `tests/app_urls.py`)."""

from tests.app_urls import urlpatterns_for

urlpatterns = urlpatterns_for("{app}")
'''


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def apply(placements: dict[str, Placement]) -> None:
    files = _module_files()
    moved_now: list[Path] = []
    for name, p in placements.items():
        src, dst = files[name[:-3]], target(p.dest, name)
        if src == dst:
            continue
        if dst.parent == TESTS:
            # 한 층 얕아지는 길은 경로 고치기(`deepen`)의 반대가 없다 — 손으로 옮긴다
            raise SystemExit(f"{src.relative_to(BACKEND)} → tests/ 는 손으로 옮긴다(Path(__file__) 깊이)")
        pkg = dst.parent
        if not pkg.exists():
            pkg.mkdir(parents=True)
        init = pkg / "__init__.py"
        if not init.exists():
            init.write_text("")
            _git("add", str(init.relative_to(ROOT)))
        if p.dest != INTEGRATION and not (pkg / "urls.py").exists():
            (pkg / "urls.py").write_text(APP_URLS.format(app=p.dest))
            _git("add", str((pkg / "urls.py").relative_to(ROOT)))
        _git("mv", str(src.relative_to(ROOT)), str(dst.relative_to(ROOT)))
        if src.parent == TESTS:  # 한 층 깊어졌다
            moved_now.append(dst)

    for dst in moved_now:
        dst.write_text(relative_helpers(deepen(dst.read_text(encoding="utf-8"))), encoding="utf-8")

    # 옛 이름 → 지금 모듈. 모든 시험 파일·헬퍼·conftest 의 참조를 고친다(다시 돌려도 같다).
    moved = {stem: module_of(path) for stem, path in _module_files().items() if stem.startswith("test_")}
    sources = [*TESTS.rglob("*.py"), *BACKEND.glob("*/tests/*.py"), BACKEND / "conftest.py"]
    for src in sources:
        if not src.exists():
            continue
        old = src.read_text(encoding="utf-8")
        new = relink(old, moved)
        if new != old:
            src.write_text(new, encoding="utf-8")

    if DURATIONS.exists():
        record: dict[str, float] = json.loads(DURATIONS.read_text())
        files = _module_files()
        fixed = {}
        for key, value in record.items():
            stem = Path(key).stem
            if stem in files:
                key = files[stem].relative_to(BACKEND).as_posix()
            fixed[key] = value
        DURATIONS.write_text(json.dumps(dict(sorted(fixed.items())), indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str]) -> int:
    if argv not in (["plan"], ["apply"]):
        print(__doc__, file=sys.stderr)
        return 2
    placements = plan()
    routes = route_table()
    infos = {stem: scan(p, frozenset(load_table())) for stem, p in _module_files().items()}
    for name, p in placements.items():
        print(f"{name}\t{p.dest}\t{p.why}")
    unknown = sorted({u for name in placements for u in url_apps(reach(Path(name).stem, None, infos, set())[1], routes)[1]})
    undecided = [n for n, p in placements.items() if p.dest == INTEGRATION]
    counts: dict[str, int] = {}
    for p in placements.values():
        counts[p.dest] = counts.get(p.dest, 0) + 1
    print("\n# 자리별 파일 수: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), file=sys.stderr)
    if undecided:
        print("# 앱을 못 정한 파일(통합 — 까닭은 위 표): " + ", ".join(undecided), file=sys.stderr)
    if unknown:
        print("# 표에 없는 주소(분류에서 뺐다): " + ", ".join(unknown), file=sys.stderr)
    if argv == ["apply"]:
        apply(placements)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
