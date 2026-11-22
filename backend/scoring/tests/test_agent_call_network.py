"""실행기(`agent-grader`)를 부르는 프로세스는 모두 `agent-call` 망에 있다(#1031·#1316).

부르는 쪽을 손으로 적지 않는다. 운영 compose 의 서비스마다 `command` 에서 진입점을 끌어내고(manage.py 명령 →
그 명령 모듈, celery worker → 태스크, gunicorn·uvicorn → API 경로 함수), 백엔드 소스의 호출 그래프(AST)로 그
진입점에서 실행기 HTTP 클라이언트(`agent_grader().request_run`·`check_health`)까지 닿는지 본다.

import 그래프로는 가르지 못한다 — `scoring.apps` 가 앱을 띄울 때 실행기 클라이언트를 등록하므로(#1085) 모든 Django
프로세스가 그 모듈을 import 한다. 그래서 「부르는 코드가 그 프로세스에서 도는가」를 함수 단위 호출로 본다.

#1316: 강의실 에이전트 채점이 `grader` 로 들어왔는데 이 시험이 부르는 쪽을 `celery-worker` 하나로 고정해 두어,
`grader` 에서 실행기 이름이 풀리지 않는 채로 운영에 나갔다.
"""

from __future__ import annotations

import ast
import shlex
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.conf import settings

from core.agent_ports import AgentGrader
from scoring import agent_runner as ar
from scoring.tests.test_agent_runner import _ComposeLoader

REPO_ROOT = settings.BASE_DIR.parent
BACKEND = Path(settings.BASE_DIR)
RUNNER = "agent-grader"
#: 실행기에 HTTP 로 닿는 클라이언트 메서드 — `agent_grader()` 가 돌려주는 등록 구현(`scoring.agent_runner`)의 것.
HTTP_METHODS = frozenset({"request_run", "check_health"})
#: pytest 에서만 켜지는 갈래(`settings.py` 의 `_RUNNING_TESTS`) — 운영 프로세스에서는 돌지 않으므로 그 몸통은 세지 않는다.
TEST_ONLY_SWITCHES = frozenset({"CLASSROOM_GRADER_INLINE"})
ROUTE_DECORATORS = frozenset({"get", "post", "put", "patch", "delete", "api_operation"})


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _sources() -> Iterator[Path]:
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if {"tests", "migrations", ".venv", "node_modules"} & set(rel) or rel[0].startswith("."):
            continue
        yield path


@dataclass
class _Module:
    name: str
    is_package: bool
    tree: ast.Module
    imports: dict[str, str] = field(default_factory=dict)
    defs: set[str] = field(default_factory=set)  # 최상위 함수·클래스 이름


@dataclass
class _Graph:
    modules: dict[str, _Module]
    refs: dict[str, set[str]]  # 함수 노드 → 참조한 이름(정규화 전)
    seeds: set[str]
    tasks: set[str]
    routes: set[str]
    worker_scans: set[str] = field(default_factory=set)  # 워커 안에서 도는 스캔의 함수(`worker_time_limit_seconds`)
    web_scans: set[str] = field(default_factory=set)  # backend 의 `/api/internal/scans/{name}` 안에서 도는 스캔의 함수

    def canon(self, dotted: str, depth: int = 0) -> str:
        """재수출(`from .x import f`)을 따라가 정의된 자리의 이름으로."""

        if dotted in self.refs or depth > 10:
            return dotted
        parts = dotted.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            module = self.modules.get(".".join(parts[:cut]))
            if module is None:
                continue
            head, rest = parts[cut], parts[cut + 1 :]
            target = module.imports.get(head)
            if target is not None and target != dotted:
                return self.canon(".".join([target, *rest]), depth + 1)
            return dotted
        return dotted

    def reaching(self) -> dict[str, str | None]:
        """실행기에 닿는 함수 → 다음 걸음(경로를 찍으려고). 씨앗은 None."""

        callers: dict[str, set[str]] = {}
        for node, names in self.refs.items():
            for name in names:
                callers.setdefault(self.canon(name), set()).add(node)
        nxt: dict[str, str | None] = dict.fromkeys(self.seeds)
        queue = deque(self.seeds)
        while queue:
            node = queue.popleft()
            for caller in callers.get(node, ()):
                if caller not in nxt:
                    nxt[caller] = node
                    queue.append(caller)
        return nxt


def _resolve_import(module: _Module, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    base = module.name.split(".")
    if not module.is_package:
        base = base[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _is_test_only(test: ast.expr) -> bool:
    return isinstance(test, ast.Attribute) and test.attr in TEST_ONLY_SWITCHES


class _Refs(ast.NodeVisitor):
    def __init__(self, module: _Module, cls: str | None) -> None:
        self.module, self.cls = module, cls
        self.names: set[str] = set()
        self.calls_runner = False

    def resolve(self, expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Name):
            if expr.id in self.module.defs:
                return f"{self.module.name}.{expr.id}"
            return self.module.imports.get(expr.id)
        if isinstance(expr, ast.Attribute):
            value = expr.value
            if isinstance(value, ast.Name) and value.id in {"self", "cls"} and self.cls:
                return f"{self.module.name}.{self.cls}.{expr.attr}"
            if isinstance(value, ast.Call):  # `Grader().run_forever` → 클래스의 메서드
                value = value.func
            base = self.resolve(value)
            return f"{base}.{expr.attr}" if base else None
        return None

    def visit_If(self, node: ast.If) -> None:
        if _is_test_only(node.test):
            for stmt in node.orelse:
                self.visit(stmt)
            return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if (name := self.resolve(node)) is not None:
            self.names.add(name)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr in HTTP_METHODS
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "agent_grader"
        ):
            self.calls_runner = True
        if (name := self.resolve(node)) is not None:
            self.names.add(name)
        self.generic_visit(node)


def _decorated(func: ast.FunctionDef | ast.AsyncFunctionDef, names: frozenset[str]) -> bool:
    for deco in func.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name in names:
            return True
    return False


def _build() -> _Graph:
    modules: dict[str, _Module] = {}
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _Module(_module_name(path), path.name == "__init__.py", tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        module.imports[alias.asname] = alias.name
                    else:
                        head = alias.name.split(".")[0]
                        module.imports[head] = head
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_import(module, node)
                for alias in node.names:
                    module.imports[alias.asname or alias.name] = f"{base}.{alias.name}"
        module.defs = {
            n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
        modules[module.name] = module

    graph = _Graph(modules, {}, set(), set(), set())
    for module in modules.values():
        for top in module.tree.body:
            funcs: list[tuple[str | None, ast.FunctionDef | ast.AsyncFunctionDef]] = []
            if isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef):
                funcs.append((None, top))
            elif isinstance(top, ast.ClassDef):
                funcs += [(top.name, f) for f in top.body if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)]
            for cls, func in funcs:
                node = ".".join(filter(None, [module.name, cls, func.name]))
                refs = _Refs(module, cls)
                for stmt in func.body:
                    refs.visit(stmt)
                graph.refs[node] = refs.names
                if refs.calls_runner:
                    graph.seeds.add(node)
                if _decorated(func, frozenset({"shared_task", "task"})):
                    graph.tasks.add(node)
                if _decorated(func, ROUTE_DECORATORS):
                    graph.routes.add(node)
        _collect_scans(graph, module)
    return graph


def _collect_scans(graph: _Graph, module: _Module) -> None:
    """스캔은 등록부(`core.scans.SCAN_REGISTRY`)를 거쳐 이름으로 불린다 — 호출 그래프에 이어지지 않으므로 `ScanSpec(...)`
    의 함수 인자를 진입점으로 삼는다. `worker_time_limit_seconds` 가 있으면 celery 워커 안에서, 없으면 backend 의 내부
    엔드포인트 안에서 돈다(`core.tasks.run_scan`)."""

    for call in ast.walk(module.tree):
        if not isinstance(call, ast.Call):
            continue
        refs = _Refs(module, None)
        if graph.canon(refs.resolve(call.func) or "") != "core.scans.ScanSpec":
            continue
        in_worker = False
        for kw in call.keywords:
            if kw.arg == "worker_time_limit_seconds":
                in_worker = not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
            else:
                refs.visit(kw.value)
        (graph.worker_scans if in_worker else graph.web_scans).update(refs.names)


def _entries(graph: _Graph, command: str) -> set[str]:
    """서비스 command 에서 그 프로세스가 도는 진입점 함수들. 모르는 꼴이면 실패한다 — 여기에 가르쳐야 한다."""

    words = shlex.split(command)
    entries: set[str] = set()
    known = False
    if "gunicorn" in words or "uvicorn" in words:
        entries |= graph.routes | graph.web_scans
        known = True
    if "celery" in words and "worker" in words:
        entries |= graph.tasks | graph.worker_scans
        known = True
    for i, word in enumerate(words[:-1]):
        if word == "manage.py":
            known = True
            name = words[i + 1]
            for module in graph.modules:
                if module.endswith(f".management.commands.{name}"):
                    entries |= {n for n in graph.refs if n.startswith(f"{module}.")}
            # 없으면 Django 내장 명령(collectstatic 등) — 이 소스의 코드를 부르지 않는다.
    assert known, f"진입점을 끌어내지 못하는 command: {command!r} — test_agent_call_network._entries 에 가르친다"
    return entries


def _command(svc: dict) -> str | None:
    command = svc.get("command")
    if command is None:
        return None
    text = command if isinstance(command, str) else shlex.join(command)
    if text.startswith("sh -c "):
        text = shlex.split(text)[2]
    return " ".join(text.split())


def _path(nxt: dict[str, str | None], start: str) -> str:
    steps = [start]
    while (step := nxt[steps[-1]]) is not None:
        steps.append(step)
    return " → ".join(steps)


def _compose(name: str) -> dict:
    return yaml.load((REPO_ROOT / "docker" / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


def _members(compose: dict, network: str) -> set[str]:
    return {name for name, svc in compose["services"].items() if network in (svc.get("networks") or ["default"])}


def runner_callers(compose: dict) -> dict[str, str]:
    """실행기를 부르는 서비스 → 그 경로 하나(진입점 → … → 실행기 클라이언트)."""

    graph = _build()
    nxt = graph.reaching()
    callers: dict[str, str] = {}
    for name, svc in compose["services"].items():
        if "codemit-backend:" not in str(svc.get("image", "")) or (command := _command(svc)) is None:
            continue
        hits = sorted({graph.canon(e) for e in _entries(graph, command)} & nxt.keys())
        if hits:
            callers[name] = _path(nxt, hits[0])
    return callers


def test_the_call_graph_sees_the_runner_client() -> None:
    """씨앗이 사라지면(이름이 바뀌면) 아래 대조가 「부르는 쪽 없음」으로 조용히 초록이 된다 — 그걸 막는다."""

    assert HTTP_METHODS <= set(dir(AgentGrader)) and HTTP_METHODS <= set(dir(ar))
    graph = _build()
    assert "core.agent_scoring.request_run" in graph.seeds
    nxt = graph.reaching()
    for known in ("classroom.grader.Grader.run_forever", "classroom.agent_grading.run_scoring"):
        assert known in nxt, known
    # pytest 전용 동기 갈래는 운영에서 돌지 않는다 — 그 길로는 API 가 실행기에 닿지 않는다.
    assert settings.CLASSROOM_GRADER_INLINE is True  # 시험 중이므로 켜져 있다(settings.py 의 `_RUNNING_TESTS`)


def test_every_process_that_calls_the_runner_is_on_agent_call() -> None:
    """부르는 프로세스가 `agent-call` 에 없으면 `http://agent-grader:8003` 이름이 풀리지 않아 모든 실행이
    「에이전트 실행기에 닿지 못했다: URLError」다(#1316). 거꾸로, 부르지 않는 프로세스는 넣지 않는다 — 실행기에서
    보이는 것을 늘리지 않는다."""

    prod = _compose("compose.prod.yaml")
    assert ar.DEFAULT_SERVICE_URL == f"http://{RUNNER}:{ar.SERVICE_PORT}"
    callers = runner_callers(prod)
    assert {"celery-worker", "grader"} <= callers.keys(), callers
    on_call = _members(prod, "agent-call") - {RUNNER}
    missing = {name: path for name, path in callers.items() if name not in on_call}
    assert not missing, f"실행기를 부르는데 agent-call 에 없다: {missing}"
    assert on_call == callers.keys(), f"실행기를 부르지 않는데 agent-call 에 있다: {on_call - callers.keys()}"
    for name in callers:
        assert set(prod["services"][name]["networks"]) & set(prod["services"][RUNNER]["networks"]) == {"agent-call"}
    # 실행기에서 보이는 것: 프록시(`agent`)와 부르는 쪽(`agent-call`)뿐. 둘 다 밖으로 나가는 길이 없다.
    assert _members(prod, "agent") == {RUNNER, "llm-proxy"}
    assert prod["networks"]["agent-call"] == {"internal": True}


def test_ci_check_calls_the_runner_from_where_prod_callers_call_it() -> None:
    """검사 driver 는 운영의 부르는 쪽 모두와 같은 자리(`agent-call`, `agent` 아님)에 선다(#1031·#1316)."""

    prod = _compose("compose.prod.yaml")
    check = _compose("compose.agent-grader-check.yaml")
    driver = set(check["services"]["driver"]["networks"])
    assert "agent" not in driver
    assert driver & set(check["services"][RUNNER]["networks"]) == {"agent-call"}
    for name in runner_callers(prod):
        prod_seat = set(prod["services"][name]["networks"]) & set(prod["services"][RUNNER]["networks"])
        assert prod_seat == driver & set(check["services"][RUNNER]["networks"]), name
    assert check["networks"]["agent-call"] == {"internal": True}
