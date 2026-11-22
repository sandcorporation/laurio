"""로컬 시험 고르기 — 바뀐 파일에서 백엔드·vitest·e2e 를 골라 돌린다(#1330, spec local-tests).

    scripts/test.sh affected [--base <커밋>] [--list] [--only backend,vitest,e2e]

작업자가 TDD 로 개발하면서 push 전에 돌린다. PR 검사의 고르기(`scripts/ci/pytest_plan.py`·`e2e_plan.py`)는 앱
단위로 넓게 고르고, 이 명령은 **파일 단위로 좁게** 고른다 — 로컬은 한 번에 400개까지라 앱 하나의 pytest 도
넘칠 수 있고, e2e 는 스택을 굽는 값이 크다. 넓은 판은 그대로 PR 검사가 돈다.

바뀐 파일 = 기준 커밋 뒤의 커밋 + 커밋하지 않은 변경 + 추적하지 않는 새 파일. 기준을 주지 않으면 `origin/main` 과
`origin/spec/*` 가운데 HEAD 와의 merge-base 가 가장 가까운 것(스펙 길의 티켓이면 그 스펙 브랜치).

고르는 규칙 — 줄마다 까닭이 붙는다(`docs/ops/testing.md` 「로컬 시험 고르기」).

- 백엔드: 바뀐 시험 파일 / 바뀐 모듈을 import 하는(또는 경로 문자열로 가리키는) 시험 — 같은 앱 안에서 그 모듈을 쓰는
  모듈을 한 단계 더 따라간다 / 소스를 훑는 가드 시험(`GUARDS` 표 — 경계·계약·권한·선언).
- vitest: 바뀐 파일에서 import 를 거꾸로 따라 닿는 `*.test.ts(x)`. 워크스페이스 설정이 바뀌면 그 워크스페이스 전부.
- e2e: 바뀐 스펙 파일 / 바뀐 e2e 도우미를 import 하는 스펙 / 바뀐 화면 파일에서 import 를 거꾸로 따라 닿는 파일의
  `data-testid` 를 쓰거나 그 파일들이 만드는 라우트로 `goto` 하는 스펙 / 바뀐 백엔드 앱의 e2e 폴더. 화면 파일에서
  스펙을 못 찾거나 루트 레이아웃까지 번지면 그 앱의 e2e 전부로 넓히고 그렇다고 말한다 — 조용히 0개로 가지 않는다.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

ROOT = Path(__file__).resolve().parents[1]

Kind = Literal["backend", "vitest", "e2e"]
KINDS: tuple[Kind, ...] = ("backend", "vitest", "e2e")


class Tree(Protocol):
    """고르기가 읽는 저장소 — 지금 워크트리, 또는 시험이 겹쳐 쓴 것."""

    def files(self) -> list[str]: ...

    def read(self, path: str) -> str: ...


class WorkTree:
    """git 이 아는 파일(추적 + 무시되지 않은 새 파일) 중 지금 있는 것."""

    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self._files: list[str] | None = None
        self._text: dict[str, str] = {}

    def files(self) -> list[str]:
        if self._files is None:
            out = git("ls-files", "-co", "--exclude-standard", cwd=self.root)
            self._files = sorted(f for f in set(out.split("\n")) if f and (self.root / f).is_file())
        return self._files

    def read(self, path: str) -> str:
        if path not in self._text:
            try:
                self._text[path] = (self.root / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self._text[path] = ""
        return self._text[path]


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@dataclass
class Pick:
    kind: Kind
    target: str  # 백엔드: backend/ 기준 시험 파일(또는 `::함수`) · vitest: 저장소 기준 시험 파일 · e2e: frontend/ 기준 스펙 파일
    reason: str
    tier: int = 1  # 백엔드만: 1 = 바뀐 시험·가드, 2 = 바뀐 모듈을 가리키는 시험(400 한도를 넘으면 뺀다)


@dataclass
class Plan:
    picks: list[Pick] = field(default_factory=list)
    notes: dict[Kind, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add(self, kind: Kind, target: str, reason: str, tier: int = 1) -> None:
        self.picks.append(Pick(kind, target, reason, tier))

    def note(self, kind: Kind, line: str) -> None:
        if line not in self.notes[kind]:
            self.notes[kind].append(line)

    def targets(self, kind: Kind, tier: int = 2) -> dict[str, list[str]]:
        """대상 → 까닭들(처음 나온 차례). tier 이하만."""

        out: dict[str, list[str]] = {}
        whole: set[str] = set()
        if kind == "backend":
            # 파일 전체를 고른 것이 있으면 그 파일의 `::함수` 는 겹친다
            whole = {p.target for p in self.picks if p.kind == kind and p.tier <= tier and "::" not in p.target}
        for p in self.picks:
            if kind == "backend" and "::" in p.target and p.target.split("::")[0] in whole:
                continue
            if p.kind == kind and p.tier <= tier:
                reasons = out.setdefault(p.target, [])
                if p.reason not in reasons:
                    reasons.append(p.reason)
        return dict(sorted(out.items()))


# ── 백엔드 ────────────────────────────────────────────────────────────────────────────────────────

#: 소스를 훑거나 선언·계약을 대조하는 가드 시험(파일, 또는 가드인 함수만 `파일::함수`) → 어떤 파일이 바뀌면 고르나(fnmatch, 저장소 기준) · 까닭.
#: 「그 시험 파일을 import 하지 않아도 깨지는」 것만 둔다. 새 가드 시험을 만들면 여기에 더한다.
#: `SRC` 는 백엔드 소스 전부(시험·마이그레이션 밖의 backend/**/*.py) — 소스 트리를 통째로 훑는 가드다.
SRC = "<backend 소스>"
FRONT_SRC = ("frontend/*.ts", "frontend/*.tsx", "operator/*.ts", "operator/*.tsx", "classroom/*.ts", "classroom/*.tsx", "packages/*.ts", "packages/*.tsx")
DEPLOY = ("deploy.sh", "scripts/deploy*", "scripts/ci/*.py", "scripts/ci/*.sh", "docker/compose*.yaml", "docker/*.env*")
GUARDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("tests/test_app_boundaries.py", (SRC, "backend/app_deps.toml"), "앱 경계 표 ↔ 코드"),
    ("tests/test_shared_layer_ports.py", (SRC,), "공유층 import 순환"),
    ("tests/test_runtime_settings_port.py::test_the_shared_layer_has_no_top_level_import_cycle", (SRC,), "공유층 설정 포트"),
    ("tests/test_current_score_reads.py", (SRC,), "현재 점수 읽기 허용 목록"),
    ("contests/tests/test_contest_status_writes_are_declared.py", (SRC,), "공모전 상태 쓰기 선언"),
    ("contests/tests/test_contest_transition_graph.py", ("backend/contests/*.py", "docs/features/backend.md"), "상태 전이 그림 ↔ 코드"),
    ("scoring/tests/test_agent_runner.py::test_only_the_agent_scorer_calls_the_runner", (SRC,), "실행기를 부르는 곳 허용 목록"),
    ("scoring/tests/test_agent_runner.py", ("docker/agent-grader*",), "실행기 이미지 계약"),
    ("scoring/tests/test_agent_call_network.py", (SRC, "docker/compose*.yaml"), "에이전트 호출 경로"),
    ("core/tests/test_scoring_parser_paths.py::test_every_parser_call_site_is_in_the_table", (SRC,), "채점 파서 호출 자리 표"),
    ("tests/integration/test_agent_ports.py", ("backend/core/agent_*.py", "backend/scoring/agent_*.py", "backend/scoring/selfloop*.py"), "에이전트 포트 계약 ↔ 실행기"),
    ("tests/test_classroom_instructor_scope_structure.py", ("backend/classroom/*.py", "backend/submissions/resolvers.py"), "강사 범위 구조"),
    ("classroom/tests/test_classroom_co_instructor_permissions.py::test_the_table_covers_every_instructor_route", ("backend/classroom/api.py", "backend/classroom/template_api.py"), "공동 강사 권한 표 ↔ 라우트"),
    ("classroom/tests/test_classroom_syntax_check.py::test_contest_scoring_module_does_not_import_classroom_syntax_check", ("backend/scoring/*.py",), "scoring 이 classroom 을 import 하지 않음"),
    ("classroom/tests/test_grammar_prefetch.py", ("docker/backend.Dockerfile",), "문법 미리받기 ↔ Dockerfile"),
    ("classroom/tests/test_classroom_gradability_hint.py::test_the_screen_note_is_the_same_sentence_in_python_and_the_classroom_app", ("classroom/lib/problems/gradability.ts",), "채점 가능 힌트 문구 ↔ 앞단"),
    ("classroom/tests/test_privacy_policy_lock.py", ("frontend/app/privacy/*",), "개인정보 처리방침 문구"),
    ("tests/test_migration_compat.py", ("backend/*/migrations/*.py",), "마이그레이션 호환"),
    ("tests/test_migration_rolling_safety.py", ("backend/*/migrations/*.py", "docker/compose*.yaml"), "겹쳐 바꾸기 안전"),
    ("tests/test_admin_is_gone.py", ("backend/*/admin.py",), "admin 없음"),
    ("tests/test_banned_word_field_registration.py", ("backend/*schemas*.py", "backend/core/banned_word_rules.py"), "금칙어 필드 등록"),
    ("tests/test_next_font_stays_local.py", FRONT_SRC, "next/font 는 로컬만"),
    ("tests/test_next_public_env_stays_out.py", FRONT_SRC, "NEXT_PUBLIC_ env 금지"),
    ("tests/test_metrics_snippet_stays_in_public_apps.py", (*FRONT_SRC[:2], *FRONT_SRC[4:6], "docker/compose*.yaml"), "지표 스니펫 자리"),
    ("tests/test_compose_commands_exec.py", ("docker/compose*.yaml",), "compose 명령 exec 꼴"),
    ("tests/test_health_deploy_wiring.py", ("docker/compose.prod.yaml",), "health 배선"),
    ("tests/test_pgbouncer_config.py", ("docker/pgbouncer/*",), "풀러 설정"),
    ("tests/test_required_settings.py", ("backend/config/*", "scripts/ci/post-deploy-check.sh"), "필수 설정"),
    ("tests/test_cpu_speed.py::test_the_committed_reference_names_test_files_that_exist", ("backend/tests/cpu_reference.json",), "CPU 기준 열쇠"),
    *((f"tests/test_deploy_{n}.py", DEPLOY, "배포 스크립트 계약") for n in (
        "celery_beat_in_worker", "migrate_pooler_host", "rolling_deadline", "predeploy_dump", "postdeploy", "plan_rolling", "plan_app_env",
    )),
)


#: 화면이 부르는 HTTP 겉면 — 이 파일이 바뀐 백엔드 앱은 그 앱의 e2e 폴더를 고른다
HTTP_SURFACE = re.compile(r"/(?:[a-z_]*api|schemas?|urls|[a-z_]*_api|views)\.py$|/(?:api|schemas)/")


def is_source(path: str) -> bool:
    return path.startswith("backend/") and path.endswith(".py") and not BACKEND_TEST.match(path) and "/migrations/" not in path and "/tests/" not in path


def guard_hits(path: str, globs: tuple[str, ...]) -> bool:
    return any(is_source(path) if g == SRC else fnmatch.fnmatchcase(path, g) for g in globs)

BACKEND_TEST = re.compile(r"^backend/(?:tests|[^/]+/tests)/(?:.+/)?test_[^/]*\.py$")
#: 이 파일들이 바뀌면 고를 수 없다 — 가드만 고르고 「전부는 PR 검사」라고 말한다
BACKEND_WIDE = ("backend/conftest.py", "backend/pyproject.toml", "backend/uv.lock", "backend/config/*", "backend/*/conftest.py", "backend/tests/conftest.py")


def module_of(path: str) -> str | None:
    """backend/classroom/scoring_calculator.py → classroom.scoring_calculator."""

    if not (path.startswith("backend/") and path.endswith(".py")):
        return None
    parts = path.removeprefix("backend/").removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def refers_to(text: str, module: str) -> bool:
    """이 소스가 그 모듈을 import 하거나 경로 문자열(`mock.patch("a.b.c")`)로 가리키나."""

    if re.search(rf"^\s*(?:from|import)\s+{re.escape(module)}(?:\s|\.|$|,)", text, re.MULTILINE):
        return True
    if re.search(rf"[\"']{re.escape(module)}(?:[\"'.])", text):
        return True
    pkg, _, leaf = module.rpartition(".")
    if pkg:
        for m in re.finditer(rf"^\s*from\s+{re.escape(pkg)}\s+import\s+(\([^)]*\)|[^\n]+)", text, re.MULTILINE):
            if re.search(rf"\b{re.escape(leaf)}\b", m.group(1)):
                return True
    return False


def pick_backend(changed: Iterable[str], tree: Tree, plan: Plan) -> None:
    files = tree.files()
    present = set(files)
    tests = [f for f in files if BACKEND_TEST.match(f)]

    def add(test: str, reason: str, tier: int = 1) -> None:
        plan.add("backend", test.removeprefix("backend/"), reason, tier)

    for f in changed:
        for test, globs, why in GUARDS:
            if f"backend/{test.split('::')[0]}" in present and guard_hits(f, globs):
                add(f"backend/{test}", f"가드 — {why}")
        if not f.startswith("backend/") or f.endswith(".md"):
            continue
        if any(fnmatch.fnmatchcase(f, g) for g in BACKEND_WIDE):
            plan.note("backend", f"{f} 이 바뀌었다 — 고를 수 없어 가드·바뀐 시험만 돈다. 전부는 PR 검사가 돈다")
            continue
        if BACKEND_TEST.match(f):
            if f in present:
                add(f, "바뀐 시험")
            continue
        module = module_of(f)
        if module is None or f not in present:
            continue
        # 같은 앱 안에서 이 모듈을 쓰는 모듈까지 한 단계 — api.py 가 바뀐 계산기를 부르면 api 시험도 고른다
        for t in tests:
            if refers_to(tree.read(t), module):
                add(t, f"{module} 을 가리킨다", 2)


# ── 프런트(vitest·e2e 가 함께 쓰는 import 그래프) ─────────────────────────────────────────────────

#: 화면 앱 → e2e 프로젝트
APPS: dict[str, str] = {"frontend": "public", "operator": "operator", "classroom": "classroom"}
#: 워크스페이스 폴더 → pnpm 패키지 이름(package.json 의 name)
SOURCE = re.compile(r"\.(?:ts|tsx|mts)$")
IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\(\s*)["']([^"']+)["']""")
TESTID = re.compile(r"""data-testid=(?:"([^"]+)"|'([^']+)'|\{\s*["']([^"']+)["']\s*\}|\{\s*`([^`$]*)(\$)?)""")
GOTO = re.compile(r"""\.goto\(\s*([`'"])(.*?)\1""")
#: 이 파일들이 바뀌면 그 워크스페이스의 vitest 전부
VITEST_WIDE = ("package.json", "tsconfig.json", "vitest.config.*", "vitest.setup.*", "test/setup.*")


def workspace_of(path: str) -> str | None:
    top = path.split("/", 1)[0]
    if top in APPS:
        return top
    if top == "packages" and path.count("/") >= 2:
        return "/".join(path.split("/")[:2])
    return None


def is_e2e(path: str) -> bool:
    return path.startswith("frontend/e2e/") or path.startswith("frontend/playwright")


class Graph:
    """프런트 소스의 import 그래프(거꾸로) — 누가 이 파일을 import 하나."""

    def __init__(self, tree: Tree) -> None:
        self.tree = tree
        files = tree.files()
        self.sources = {f for f in files if SOURCE.search(f) and workspace_of(f) and "/node_modules/" not in f}
        self.packages = {f"@codemit/{p.split('/')[1]}": p for p in {workspace_of(f) for f in self.sources} if p and p.startswith("packages/")}
        self.importers: dict[str, set[str]] = defaultdict(set)
        for f in self.sources:
            for spec in IMPORT.findall(tree.read(f)):
                for target in self.resolve(f, spec):
                    self.importers[target].add(f)

    def resolve(self, src: str, spec: str) -> list[str]:
        ws = workspace_of(src) or ""
        if spec.startswith("@/"):
            base = f"{ws}/{spec[2:]}"
        elif spec.startswith("."):
            base = os.path.normpath(os.path.join(os.path.dirname(src), spec))
        else:
            name = "/".join(spec.split("/")[:2])
            pkg = self.packages.get(name)
            if pkg is None:
                return []
            # 패키지 안 어느 파일이 바뀌어도 그 패키지를 쓰는 곳이 닿게 — 패키지 이름 자체를 한 마디로 둔다
            return [pkg]
        for cand in (base, f"{base}.ts", f"{base}.tsx", f"{base}.mts", f"{base}/index.ts", f"{base}/index.tsx"):
            if cand in self.sources:
                return [cand]
        return []

    def nearest(self, start: str, stop: Callable[[str], bool]) -> set[str]:
        """start 에서 import 를 거꾸로 따라가다 stop 에 맞는 파일에서 멈춘다 — 그 파일들(start 가 맞으면 start)."""

        out: set[str] = set()
        seen: set[str] = set()
        stack = [start]
        ws = workspace_of(start)
        if ws and ws.startswith("packages/"):
            stack.append(ws)
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            if f in self.sources and stop(f):
                out.add(f)
                continue
            stack += self.importers.get(f, ())
        return out

    def upward(self, start: str) -> set[str]:
        """start 와, import 를 거꾸로 따라 닿는 모든 파일. 패키지 파일은 패키지 마디를 거쳐 그 소비자로 번진다."""

        seen: set[str] = set()
        stack = [start]
        ws = workspace_of(start)
        if ws and ws.startswith("packages/"):
            stack.append(ws)
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            stack += self.importers.get(f, ())
        return {f for f in seen if f in self.sources}


def route_of(path: str) -> tuple[str, bool] | None:
    """classroom/app/(main)/classes/[id]/settings/page.tsx → ("/classes/*/settings", 정확히). layout 은 앞부분."""

    ws = workspace_of(path)
    if ws not in APPS or not path.startswith(f"{ws}/app/"):
        return None
    name = Path(path).name.split(".")[0]
    if name not in ("page", "layout"):
        return None
    segs = [s for s in path.removeprefix(f"{ws}/app/").split("/")[:-1] if not (s.startswith("(") and s.endswith(")"))]
    segs = ["*" if s.startswith("[") else s for s in segs]
    return "/" + "/".join(segs), name == "page"


def goto_paths(text: str) -> list[str]:
    out = []
    for _, raw in GOTO.findall(text):
        p = re.sub(r"\$\{[^}]*\}", "*", raw).split("?")[0].split("#")[0]
        if p.startswith("/"):
            out.append(p.rstrip("/") or "/")
    return out


def route_hits(route: str, exact: bool, path: str) -> bool:
    a, b = route.strip("/").split("/"), path.strip("/").split("/")
    if route == "/":
        return path == "/" if exact else True
    if exact and len(a) != len(b):
        return False
    if len(b) < len(a):
        return False
    return all(x == y or x == "*" or y == "*" for x, y in zip(a, b))


def testids(text: str) -> set[tuple[str, bool]]:
    """(값, 앞부분인가) — 템플릿 `x-${i}` 는 앞부분 "x-"."""

    out: set[tuple[str, bool]] = set()
    for a, b, c, d, dollar in TESTID.findall(text):
        v = a or b or c or d
        if v:
            out.add((v, bool(dollar)))
    return out


def spec_uses(text: str, tid: str, prefix: bool) -> bool:
    if prefix:
        return any(f"{q}{tid}" in text for q in "\"'`")
    return any(f"{q}{tid}{q}" in text for q in "\"'`")


def project_of(spec: str) -> str:
    rest = spec.removeprefix("frontend/e2e/")
    return "operator" if rest.startswith("operator/") else "classroom" if rest.startswith("classroom/") else "public"


def pick_front(changed: Iterable[str], tree: Tree, plan: Plan, *, backend_apps: Iterable[str]) -> None:
    files = tree.files()
    present = set(files)
    specs = [f for f in files if f.startswith("frontend/e2e/") and f.endswith(".spec.ts")]
    by_project: dict[str, list[str]] = defaultdict(list)
    for s in specs:
        by_project[project_of(s)].append(s)
    vitests = [f for f in files if re.search(r"\.test\.tsx?$", f) and workspace_of(f) and not is_e2e(f) and "/node_modules/" not in f]
    graph = Graph(tree)

    def e2e(spec: str, reason: str) -> None:
        plan.add("e2e", spec.removeprefix("frontend/"), reason)

    def whole(project: str, reason: str) -> None:
        plan.note("e2e", f"{project} 의 e2e 전부({len(by_project[project])}파일) — {reason}")
        for s in by_project[project]:
            e2e(s, f"{project} 전부")

    for f in changed:
        if f.endswith(".md"):
            continue
        ws = workspace_of(f)
        # e2e 쪽 파일
        if f.startswith("frontend/e2e/"):
            if f.endswith(".spec.ts"):
                if f in present:
                    e2e(f, "바뀐 스펙")
                continue
            if f.endswith(".ts") and f in present:
                users = sorted(e2e_upward(tree, specs, f))
                if users:
                    for s in users:
                        e2e(s, f"{f.removeprefix('frontend/')} 을 쓴다")
                    continue
            for p in APPS.values():
                whole(p, f"e2e 공용 파일 {f.removeprefix('frontend/')}")
            continue
        if f.startswith("frontend/playwright") or f.startswith("frontend/scripts/e2e"):
            for p in APPS.values():
                whole(p, f"e2e 설정 {f.removeprefix('frontend/')}")
            continue
        if ws is None:
            continue
        rel = f.removeprefix(f"{ws}/")
        # vitest
        if any(fnmatch.fnmatchcase(rel, g) for g in VITEST_WIDE):
            plan.note("vitest", f"{ws} 설정 {rel} 이 바뀌었다 — 그 워크스페이스 전부")
            for t in vitests:
                if workspace_of(t) == ws:
                    plan.add("vitest", t, f"{ws} 전부")
        elif f.endswith(".gen.ts"):
            plan.note("vitest", f"{f} — 생성된 타입이라 고르지 않는다(최신성·타입은 typecheck 가 본다)")
        elif f in present and SOURCE.search(f):
            up = graph.upward(f)
            hit = [t for t in vitests if t in up]
            for t in hit:
                plan.add("vitest", t, "바뀐 시험" if t == f else f"{f} 에 닿는다")
            if not hit and not re.search(r"\.test\.tsx?$", f):
                plan.note("vitest", f"{f} — 닿는 단위 시험 없음")
        # e2e
        if re.search(r"\.test\.tsx?$", f) or f.endswith(".gen.ts"):
            continue  # 단위 시험·생성된 타입은 화면을 바꾸지 않는다(생성 타입의 최신성은 PR 검사 static 이 본다)
        if f not in present:
            continue
        up = graph.upward(f) if SOURCE.search(f) else {f}
        apps = {workspace_of(u) for u in up} & set(APPS)
        for app in sorted(a for a in apps if a):
            project = APPS[app]
            mine = {u for u in up if workspace_of(u) == app}
            if f"{app}/app/layout.tsx" in mine or f"{app}/middleware.ts" in mine or not SOURCE.search(f):
                whole(project, f"{f} 이 {app} 전체에 닿는다")
                continue
            # testid 는 바뀐 파일과 가장 가까운 화면 조각(.tsx)에서, 라우트는 가장 가까운 page·layout 에서 — 끝까지 따라가면
            # 공용 lib 하나가 앱의 화면 절반을 고른다
            screens = {u for u in graph.nearest(f, lambda u: u.endswith(".tsx")) if workspace_of(u) == app} | ({f} if f.endswith(".tsx") else set())
            pages = {u for u in graph.nearest(f, lambda u: route_of(u) is not None) if workspace_of(u) == app}
            ids = set().union(*(testids(tree.read(u)) for u in screens)) if screens else set()
            routes = [r for u in pages if (r := route_of(u))]
            found = False
            for s in by_project[project]:
                text = tree.read(s)
                tid = next((t for t, pre in sorted(ids) if spec_uses(text, t, pre)), None)
                if tid:
                    e2e(s, f"{f} 의 testid {tid}")
                    found = True
                    continue
                hit_route = next((r for r, exact in routes for p in goto_paths(text) if route_hits(r, exact, p)), None)
                if hit_route:
                    e2e(s, f"{f} 의 라우트 {hit_route}")
                    found = True
            if not found:
                whole(project, f"{f} 에서 스펙을 못 찾음")
        if ws.startswith("packages/") and not apps:
            plan.note("e2e", f"{f} — 쓰는 화면 없음")

    for app in sorted(set(backend_apps)):
        folder = "frontend/e2e/classroom/" if app == "classroom" else None
        hits = [s for s in specs if (folder and s.startswith(folder)) or s.startswith(f"frontend/e2e/{app}/") or s.startswith(f"frontend/e2e/operator/{app}/")]
        for s in hits:
            e2e(s, f"백엔드 {app} 의 e2e 폴더")
        if not hits:
            plan.note("e2e", f"백엔드 {app} 이 바뀌었다 — 그 앱의 e2e 폴더가 없다(앱 사이 화면은 PR 검사가 앱 표로 고른다)")


def e2e_upward(tree: Tree, specs: list[str], helper: str) -> set[str]:
    """e2e 도우미를 import 하는 스펙들(도우미 사이 import 도 따라간다)."""

    e2e_files = [f for f in tree.files() if f.startswith("frontend/e2e/") and f.endswith(".ts")]
    importers: dict[str, set[str]] = defaultdict(set)
    for f in e2e_files:
        for spec in IMPORT.findall(tree.read(f)):
            if spec.startswith("."):
                base = os.path.normpath(os.path.join(os.path.dirname(f), spec))
                for cand in (base, f"{base}.ts", f"{base}/index.ts"):
                    if cand in e2e_files:
                        importers[cand].add(f)
    seen: set[str] = set()
    stack = [helper]
    while stack:
        f = stack.pop()
        if f not in seen:
            seen.add(f)
            stack += importers.get(f, ())
    return seen & set(specs)


# ── 모으기 ───────────────────────────────────────────────────────────────────────────────────────


def choose(changed: list[str], tree: Tree | None = None) -> Plan:
    tree = tree or WorkTree()
    plan = Plan()
    pick_backend(changed, tree, plan)
    backend_apps = {f.split("/")[1] for f in changed if is_source(f) and f.count("/") >= 2 and HTTP_SURFACE.search(f)}
    inner = sorted({f.split("/")[1] for f in changed if is_source(f) and f.count("/") >= 2 and not HTTP_SURFACE.search(f)} - backend_apps)
    if inner:
        plan.note("e2e", f"백엔드 {', '.join(inner)} 의 안쪽 모듈만 바뀌었다 — 화면 시험은 고르지 않는다(PR 검사가 앱 표로 고른다)")
    pick_front(changed, tree, plan, backend_apps=backend_apps)
    common = [f for f in changed if f.split("/", 1)[0] not in ("backend", "frontend", "operator", "classroom", "packages", "docs") and not f.endswith(".md")]
    if common:
        shown = ", ".join(common[:3]) + (f" 외 {len(common) - 3}" if len(common) > 3 else "")
        for k in KINDS:
            plan.note(k, f"공통 경로({shown})는 고르지 않는다 — PR 검사가 전부를 돈다")
    return plan


def default_base() -> str:
    """origin/main·origin/spec/* 가운데 HEAD 와의 merge-base 가 가장 가까운 것."""

    refs = ["origin/main", *git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/spec/").split()]
    best: tuple[int, str] | None = None
    for ref in refs:
        try:
            mb = git("merge-base", "HEAD", ref).strip()
            n = int(git("rev-list", "--count", f"{mb}..HEAD").strip())
        except subprocess.CalledProcessError:
            continue
        if best is None or n < best[0]:
            best = (n, ref)
    if best is None:
        raise SystemExit("기준을 못 찾았다 — --base 를 준다")
    return best[1]


def changed_files(base: str) -> list[str]:
    mb = git("merge-base", "HEAD", base).strip()
    out = set(git("diff", "--name-only", mb).split("\n")) | set(git("ls-files", "-o", "--exclude-standard").split("\n"))
    return sorted(f for f in out if f)


WORKSPACE_NAMES = {"frontend": "codemit-frontend", "operator": "codemit-operator", "classroom": "codemit-classroom"}


def package_name(ws: str) -> str:
    if ws in WORKSPACE_NAMES:
        return WORKSPACE_NAMES[ws]
    return "@codemit/" + ws.split("/", 1)[1]


def commands(plan: Plan, only: Iterable[Kind], *, tier: int = 2) -> Iterator[tuple[Kind, list[str]]]:
    only = set(only)
    if "backend" in only and (back := plan.targets("backend", tier)):
        yield "backend", ["scripts/test.sh", "backend", *back, "-q"]
    if "vitest" in only:
        by_ws: dict[str, list[str]] = defaultdict(list)
        for t in plan.targets("vitest"):
            ws = workspace_of(t) or ""
            by_ws[ws].append(t.removeprefix(f"{ws}/"))
        for ws, tests in sorted(by_ws.items()):
            yield "vitest", ["pnpm", "--filter", package_name(ws), "exec", "vitest", "run", *tests]
    if "e2e" in only and (specs := plan.targets("e2e")):
        yield "e2e", ["scripts/test.sh", "e2e", *specs]


#: pytest 가 쓰임 오류(UsageError — conftest 의 400 한도)로 끝날 때의 종료 코드
PYTEST_USAGE_ERROR = 4


def run(plan: Plan, only: Iterable[Kind]) -> list[str]:
    failed: list[str] = []
    for kind, cmd in commands(plan, only):
        print(f"\n▶ {kind}: {' '.join(cmd[:6])}{' …' if len(cmd) > 6 else ''}", flush=True)
        code = subprocess.run(cmd, cwd=ROOT).returncode
        if kind == "backend" and code == PYTEST_USAGE_ERROR and plan.targets("backend", 1) != plan.targets("backend"):
            print("\n고른 백엔드 시험이 로컬 한도(400)를 넘는다 — 바뀐 시험·가드만 돈다. 바뀐 모듈을 가리키는 시험은 파일을 골라 돌리거나 PR 검사가 본다", flush=True)
            (_, cmd1), *_ = commands(plan, ["backend"], tier=1)
            code = subprocess.run(cmd1, cwd=ROOT).returncode
        if code != 0:
            failed.append(kind)
    return failed


def show(plan: Plan, only: Iterable[Kind], base: str, changed: list[str]) -> None:
    print(f"기준 {base} · 바뀐 파일 {len(changed)}")
    for k in only:
        targets = plan.targets(k)
        print(f"\n[{k}] {len(targets)}")
        for line in plan.notes.get(k, []):
            print(f"  ! {line}")
        for t, reasons in targets.items():
            more = f" 외 {len(reasons) - 1}" if len(reasons) > 1 else ""
            print(f"  {t}  ← {reasons[0]}{more}")
        if k == "backend" and len(targets) != len(plan.targets(k, 1)):
            print(f"  (바뀐 시험·가드 {len(plan.targets(k, 1))} · 나머지는 바뀐 모듈을 가리키는 시험)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/test.sh affected", description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", help="기준 커밋(기본: origin/main·origin/spec/* 중 가장 가까운 것)")
    parser.add_argument("--list", action="store_true", help="고르기만 하고 돌리지 않는다")
    parser.add_argument("--only", default=",".join(KINDS), help="돌릴 종류(쉼표로): backend,vitest,e2e")
    args = parser.parse_args(argv)
    only: list[Kind] = [k for k in KINDS if k in args.only.split(",")]
    base = args.base or default_base()
    changed = changed_files(base)
    plan = choose(changed)
    show(plan, only, base, changed)
    if args.list:
        return 0
    failed = run(plan, only)
    print("\n" + ("통과" if not failed else f"실패: {', '.join(failed)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
