"""로컬 시험 고르기(`scripts/affected_tests.py`, #1330) — 바뀐 파일이 백엔드·vitest·e2e 의 어느 시험을 고르나.

대장 #5800 의 PR 검사 조사에서 로컬에서 잡을 수 있었는데 PR 검사에서야 빨갛던 것들을 그 PR 의 바뀐 파일로 재현한다.
CI 의 pytest 잡은 얕게 체크아웃하므로 커밋 범위 대신 그 PR 의 바뀐 파일 목록을 여기 적어 둔다(가짜 diff) —
고르기는 지금 트리를 읽는다.

- #1305: `scoring/tests/test_agent_runner.py::test_only_the_agent_scorer_calls_the_runner`(classroom 만 바꿨는데 소스 전체를
  훑는 가드), e2e `class-settings.spec.ts:189`·`staged-citations.spec.ts:43`.
- #1309: e2e `staged-citations.spec.ts:43`. #1315: e2e `class-settings.spec.ts:213`.
- #1328: `tests/integration/test_agent_ports.py`(계약 시험).

`staged-citations.spec.ts` 는 #1312 가 지웠다 — 그 PR 들이 그 스펙도 고쳤으므로 그때의 트리처럼 겹쳐 놓고 본다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "affected_tests.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("affected_tests", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


at = _load()
TREE = at.WorkTree(REPO)

STAGED = "frontend/e2e/classroom/staged-citations.spec.ts"

PR_1305 = [
    "CONTEXT.md",
    "backend/classroom/api.py",
    "backend/classroom/mcp_read_tools.py",
    "backend/classroom/schemas.py",
    "backend/classroom/scoring_calculator.py",
    "backend/classroom/scoring_cost.py",
    "backend/classroom/tests/test_classroom_mcp_read_tools.py",
    "backend/classroom/tests/test_classroom_scoring_calculator.py",
    "backend/core/model_context.py",
    "classroom/app/classes/[id]/scoring-calculator.tsx",
    "classroom/lib/classes/grading-cost.ts",
    "classroom/lib/scoring/calculator.test.ts",
    "classroom/lib/scoring/calculator.ts",
    "docs/features/backend.md",
    "docs/features/classroom.md",
    "frontend/e2e/classroom/class-settings.spec.ts",
    STAGED,
    "packages/bff-client/src/schema.gen.ts",
]
PR_1309 = [
    "CONTEXT.md",
    "backend/classroom/api.py",
    "backend/classroom/schemas.py",
    "backend/classroom/scoring_calculator.py",
    "backend/classroom/tests/test_classroom_scoring_calculator.py",
    "classroom/app/classes/[id]/grading-method-section.tsx",
    "classroom/app/classes/[id]/scoring-calculator.tsx",
    "classroom/lib/scoring/calculator.test.ts",
    "classroom/lib/scoring/calculator.ts",
    "docs/features/backend.md",
    "docs/features/classroom.md",
    "frontend/e2e/classroom/class-settings.spec.ts",
    STAGED,
    "packages/bff-client/src/schema.gen.ts",
]
PR_1315 = [
    "classroom/app/classes/[id]/grading-method-section.tsx",
    "classroom/app/classes/[id]/scoring-calculator.tsx",
    "classroom/app/classes/[id]/settings/page.tsx",
    "classroom/lib/scoring/calculator.test.ts",
    "classroom/lib/scoring/calculator.ts",
    "docs/features/classroom.md",
    "frontend/e2e/classroom/class-settings.spec.ts",
]
PR_1328 = [
    "backend/classroom/agent_grading.py",
    "backend/classroom/platform_failures.py",
    "backend/classroom/tests/test_classroom_scoring_proxy_unreachable.py",
    "backend/core/agent_ports.py",
    "backend/core/agent_scoring.py",
    "backend/scoring/agent_runner.py",
    "backend/scoring/selfloop_scoring.py",
    "backend/scoring/tests/test_agent_runner.py",
    "backend/tests/integration/test_agent_repo_paths.py",
    "backend/tests/integration/test_selfloop_scoring.py",
    "docs/features/backend.md",
    "docs/features/classroom.md",
    "docs/ops/operations.md",
]


class Overlay:
    """지금 트리 위에 파일을 더하거나 바꾼 트리."""

    def __init__(self, base: object, extra: dict[str, str]) -> None:
        self.base = base
        self.extra = extra

    def files(self) -> list[str]:
        return sorted({*self.base.files(), *self.extra})

    def read(self, path: str) -> str:
        return self.extra[path] if path in self.extra else self.base.read(path)


#: #1312 이 지우기 전의 staged-citations 스펙 머리 — 고르기가 읽는 import 와 testid 만 남긴다
THEN = Overlay(TREE, {STAGED: 'import { test } from "@playwright/test";\ntest("@exclusive 판정 근거", async () => {});\n'})


def backend(plan: object, tier: int = 1) -> set[str]:
    return set(plan.targets("backend", tier))


def e2e(plan: object) -> set[str]:
    return set(plan.targets("e2e"))


def test_pr_1305_picks_the_runner_guard_and_both_failed_specs() -> None:
    plan = at.choose(PR_1305, THEN)
    assert "scoring/tests/test_agent_runner.py::test_only_the_agent_scorer_calls_the_runner" in backend(plan)
    assert {"e2e/classroom/class-settings.spec.ts", "e2e/classroom/staged-citations.spec.ts"} <= e2e(plan)


def test_pr_1309_picks_the_failed_staged_citations_spec() -> None:
    assert "e2e/classroom/staged-citations.spec.ts" in e2e(at.choose(PR_1309, THEN))


def test_pr_1315_picks_class_settings_from_the_screen_alone() -> None:
    # 스펙을 고치지 않았어도 — 계산기 화면의 testid 를 쓰는 스펙이 골라진다
    screens_only = [f for f in PR_1315 if not f.startswith("frontend/e2e/")]
    plan = at.choose(screens_only, TREE)
    picked = plan.targets("e2e")
    assert "e2e/classroom/class-settings.spec.ts" in picked
    assert any("testid" in r for r in picked["e2e/classroom/class-settings.spec.ts"])
    # 화면만 바꾼 PR 은 앱의 e2e 전부가 아니라 그 일부다
    assert len(picked) < len([f for f in TREE.files() if f.startswith("frontend/e2e/classroom/") and f.endswith(".spec.ts")])


def test_pr_1328_picks_the_agent_ports_contract() -> None:
    assert "tests/integration/test_agent_ports.py" in backend(at.choose(PR_1328, TREE))


def test_a_changed_module_picks_the_tests_that_import_it_at_the_second_tier() -> None:
    plan = at.choose(["backend/classroom/scoring_calculator.py"], TREE)
    assert "classroom/tests/test_classroom_scoring_calculator.py" in backend(plan, tier=2)
    assert "classroom/tests/test_classroom_scoring_calculator.py" not in backend(plan, tier=1)


def test_an_inner_backend_module_picks_no_e2e_and_says_so() -> None:
    plan = at.choose(["backend/classroom/agent_grading.py"], TREE)
    assert not e2e(plan)
    assert any("classroom" in n for n in plan.notes["e2e"])


def test_an_http_surface_change_picks_that_apps_e2e_folder() -> None:
    picked = e2e(at.choose(["backend/classroom/api.py"], TREE))
    assert picked and all(s.startswith("e2e/classroom/") for s in picked)


def test_a_screen_with_no_matching_spec_widens_to_the_whole_app_and_says_so() -> None:
    lonely = "classroom/app/nowhere/page.tsx"
    tree = Overlay(TREE, {lonely: 'export default function P() { return <div data-testid="nowhere-only" />; }\n'})
    plan = at.choose([lonely], tree)
    classroom_specs = {f.removeprefix("frontend/") for f in tree.files() if f.startswith("frontend/e2e/classroom/") and f.endswith(".spec.ts")}
    assert e2e(plan) == classroom_specs
    assert any("스펙을 못 찾음" in n for n in plan.notes["e2e"])


def test_an_e2e_helper_picks_the_specs_that_import_it() -> None:
    plan = at.choose(["frontend/e2e/classroom/lib/cross-app-session.ts"], TREE)
    users = {
        f.removeprefix("frontend/")
        for f in TREE.files()
        if f.startswith("frontend/e2e/") and f.endswith(".spec.ts") and "cross-app-session" in TREE.read(f)
    }
    assert users and e2e(plan) == users


def test_a_lib_change_picks_the_vitest_that_reaches_it() -> None:
    plan = at.choose(["classroom/lib/scoring/calculator.ts"], TREE)
    assert "classroom/lib/scoring/calculator.test.ts" in plan.targets("vitest")


def test_generated_types_pick_no_vitest_and_say_so() -> None:
    plan = at.choose(["packages/bff-client/src/schema.gen.ts"], TREE)
    assert not plan.targets("vitest")
    assert plan.notes["vitest"]


@pytest.mark.parametrize("entry", at.GUARDS, ids=lambda g: g[0])
def test_every_guard_in_the_table_exists(entry: tuple[str, tuple[str, ...], str]) -> None:
    path, _, func = entry[0].partition("::")
    source = (REPO / "backend" / path).read_text(encoding="utf-8")
    if func:
        assert re.search(rf"^def {re.escape(func)}\(", source, re.MULTILINE), f"{path} 에 {func} 이 없다 — GUARDS 표를 고친다"
