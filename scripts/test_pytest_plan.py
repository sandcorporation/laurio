"""pytest 계획(scripts/ci/pytest_plan.py, #1088) — 바뀐 파일이 그 앱과 기대는 앱의 시험, 닿는 통합 시험, 구조 시험을 고른다.

네트워크·도커 없음. PR 검사 plan 잡이 돌린다.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest_plan  # noqa: E402
from app_deps import Declared, affected, load_table  # noqa: E402
from pytest_shards import chosen_files, test_files  # noqa: E402

TABLE = load_table()
FILES = test_files()


def picked(*changed: str) -> set[str] | None:
    out = pytest_plan.plan(list(changed))
    if out["PYTEST"] == "0":
        return set()
    return None if out["ALL"] == "1" else set(out["FILES"].split())


def app_of(f: str) -> str:
    return f.split("/", 1)[0]


class Selection(unittest.TestCase):
    def test_docs_and_front_run_no_pytest(self) -> None:
        self.assertEqual(picked("docs/ops/ci.md", "backend/README.md"), set())
        self.assertEqual(picked("frontend/app/page.tsx", "operator/app/page.tsx", "packages/ui/x.ts"), set())

    def test_shared_base_runs_everything(self) -> None:
        for f in (
            "backend/config/settings.py",
            "backend/conftest.py",
            "backend/uv.lock",
            "backend/pyproject.toml",
            "backend/tests/db_template.py",
            "docker/ci.Dockerfile",
            "scripts/ci/sub-checks.sh",
            ".github/workflows/pr-check.yml",
        ):
            self.assertIsNone(picked(f), f)

    def test_app_change_runs_its_users_and_not_the_rest(self) -> None:
        got = picked("backend/payouts/services.py")
        assert got is not None
        apps = affected(["backend/payouts/services.py"], TABLE)
        assert apps is not None
        self.assertTrue(any(f.startswith("payouts/tests/") for f in got))
        for f in got:
            if not f.startswith("tests/"):
                self.assertIn(app_of(f), apps, f)
        # 고른 앱의 시험은 빠짐없이
        self.assertEqual({f for f in FILES if app_of(f) in apps}, {f for f in got if not f.startswith("tests/")})
        # 쓰는 쪽이 아닌 강의실은 돌지 않는다
        self.assertNotIn("classroom", apps)
        self.assertFalse(any(f.startswith("classroom/tests/") for f in got))

    def test_structure_tests_always_run_with_pytest(self) -> None:
        got = picked("backend/payouts/services.py")
        assert got is not None
        root = {f for f in FILES if f.startswith("tests/") and f.count("/") == 1}
        self.assertTrue(root and root <= got)

    def test_test_only_change_runs_that_file_and_structure(self) -> None:
        target = next(f for f in FILES if f.startswith("tests/integration/"))
        got = picked(f"backend/{target}")
        assert got is not None
        self.assertIn(target, got)
        self.assertFalse(any(f.startswith("tests/integration/") and f != target for f in got))
        self.assertFalse(any(not f.startswith("tests/") for f in got))

    def test_deleted_test_file_runs_nothing(self) -> None:
        self.assertEqual(picked("backend/tests/integration/test_gone_long_ago.py"), set())

    def test_all_runs_max_shards_without_a_file_list(self) -> None:
        out = pytest_plan.plan(None)
        self.assertEqual((out["PYTEST"], out["ALL"], out["FILES"]), ("1", "1", ""))
        names = [m["name"] for m in json.loads(out["MATRIX"])["include"]]
        self.assertEqual(names, [f"pytest-{i}of{pytest_plan.MAX_SHARDS}" for i in range(1, pytest_plan.MAX_SHARDS + 1)])


class Integration(unittest.TestCase):
    """앱 사이 시험은 닿는 앱이 고른 앱과 겹칠 때만, 다 안 보이면 늘."""

    TABLE = {
        "a": Declared(group="shared", uses=frozenset(), plugs=frozenset()),
        "b": Declared(group="shared", uses=frozenset(), plugs=frozenset()),
    }
    FILES = ["a/tests/test_a.py", "b/tests/test_b.py", "tests/integration/test_ab.py", "tests/integration/test_b.py",
             "tests/integration/test_hidden.py", "tests/test_structure.py"]
    REACH = {"tests/integration/test_ab.py": {"a", "b"}, "tests/integration/test_b.py": {"b"}, "tests/integration/test_hidden.py": None}

    def test_picks_integration_by_touched_apps(self) -> None:
        got = pytest_plan.select(["backend/a/models.py"], self.TABLE, self.FILES, self.REACH)
        self.assertEqual(got, {"a/tests/test_a.py", "tests/integration/test_ab.py", "tests/integration/test_hidden.py", "tests/test_structure.py"})

    def test_every_integration_file_has_a_reach(self) -> None:
        reach = pytest_plan.touched()
        for f in FILES:
            if f.startswith("tests/integration/"):
                self.assertIn(f, reach, f"{f} — tests_layout.touched() 가 이 파일을 못 읽으면 선택 실행이 놓친다")


class Shards(unittest.TestCase):
    def test_shard_count_follows_recorded_time(self) -> None:
        self.assertEqual(pytest_plan.shard_count(["x.py"], {"x.py": 10.0}), 1)
        self.assertEqual(pytest_plan.shard_count(["x.py", "y.py"], {"x.py": 200.0, "y.py": 100.0}), 3)
        self.assertEqual(pytest_plan.shard_count(["x.py"], {"x.py": 10_000.0}), pytest_plan.MAX_SHARDS)

    def test_picker_honours_the_plan_file_list(self) -> None:
        some = FILES[:3]
        self.assertEqual(chosen_files(" ".join(some)), sorted(some))
        self.assertEqual(chosen_files(""), FILES)
        with self.assertRaises(SystemExit):
            chosen_files("tests/test_no_such_file.py")

    def test_picker_reads_the_environment(self) -> None:
        old = os.environ.get("CODEMIT_PYTEST_FILES")
        os.environ["CODEMIT_PYTEST_FILES"] = FILES[0]
        try:
            self.assertEqual(chosen_files(), [FILES[0]])
        finally:
            if old is None:
                del os.environ["CODEMIT_PYTEST_FILES"]
            else:
                os.environ["CODEMIT_PYTEST_FILES"] = old


if __name__ == "__main__":
    unittest.main()
