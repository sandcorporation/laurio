"""e2e 계획(scripts/ci/e2e_plan.py, #1089) — 폴더 이름이 앱 표시이고, 바뀐 파일이 맞는 조각을 고른다."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import e2e_durations  # noqa: E402
import e2e_plan  # noqa: E402
from app_deps import load_table  # noqa: E402

TABLE = load_table()


def picked(*changed: str) -> set[str]:
    return {p for shard in e2e_plan.plan(list(changed))["include"] for p in shard["paths"].split()}


class FolderNamesAreAppMarks(unittest.TestCase):
    def test_every_folder_is_a_declared_app_or_frontend(self) -> None:
        for project, apps in e2e_plan.folders().items():
            for app in apps:
                self.assertIn(app, {*TABLE, e2e_plan.PSEUDO_APP}, f"{project}: e2e 폴더 {app} 는 app_deps.toml 의 앱도 frontend 도 아니다")

    def test_no_spec_sits_outside_an_app_folder(self) -> None:
        for spec in e2e_plan.E2E.glob("*.spec.ts"):
            self.fail(f"{spec.name} — 시험은 앱 폴더 안에 둔다")
        for spec in (e2e_plan.E2E / "operator").glob("*.spec.ts"):
            self.fail(f"operator/{spec.name} — 시험은 앱 폴더 안에 둔다")


class Selection(unittest.TestCase):
    def test_docs_only_runs_nothing(self) -> None:
        self.assertEqual(picked("docs/ops/ci.md"), set())

    def test_backend_app_runs_its_folders_and_users(self) -> None:
        got = picked("backend/payments/api.py")
        self.assertTrue(any(f.startswith("e2e/payments/") for f in got))
        self.assertFalse(any(f.startswith("e2e/frontend/") for f in got))

    def test_unattributed_backend_file_runs_everything(self) -> None:
        self.assertEqual(picked("backend/config/settings.py"), picked("scripts/ci/e2e.sh"))

    def test_backend_test_files_alone_run_nothing(self) -> None:
        self.assertEqual(picked("backend/tests/integration/test_classroom_hidden_items.py"), set())
        self.assertEqual(picked("backend/classroom/tests/test_api.py", "backend/tests/conftest.py"), set())

    def test_backend_test_files_do_not_widen_a_code_change(self) -> None:
        self.assertEqual(picked("backend/payments/api.py", "backend/tests/integration/test_x.py"), picked("backend/payments/api.py"))

    def test_classroom_front_runs_only_classroom(self) -> None:
        got = picked("classroom/app/page.tsx")
        self.assertTrue(got and all(f.startswith("e2e/classroom/") for f in got))

    def test_a_spec_folder_change_runs_that_folder(self) -> None:
        got = picked("frontend/e2e/contests/contests-list.spec.ts")
        self.assertTrue(got and all(f.startswith("e2e/contests/") for f in got))

    def test_shared_helper_runs_everything(self) -> None:
        self.assertEqual(picked("frontend/e2e/lib/seed.ts"), picked("scripts/ci/e2e.sh"))

    def test_all_covers_every_spec_once(self) -> None:
        shards = e2e_plan.plan(None)["include"]
        files = [f for s in shards for f in s["paths"].split()]
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(len(files), sum(len(v) for apps in e2e_plan.folders().values() for v in apps.values()))


def fake_present(public: dict[str, float], classroom: dict[str, float]) -> dict[str, dict[str, dict[str, int]]]:
    return {
        "public": {"a": {f: 1 for f in public}},
        "operator": {},
        "classroom": {"classroom": {f: 1 for f in classroom}},
    }


class ShardsByRecordedTime(unittest.TestCase):
    """#1112 — 조각은 시험 수가 아니라 기록된 시간으로 나눈다."""

    def test_shards_are_balanced_by_time_not_count(self) -> None:
        # 공개: 1초짜리 12개, 강의실: 6초짜리 4개 — 수로 나누면 강의실 한 조각이 24초, 시간으로는 고르게
        u = e2e_plan.SHARD_SECONDS / 15  # 합이 SHARD_SECONDS 의 2.4배가 되게
        public = {f"e2e/a/p{i:02}.spec.ts": u for i in range(12)}
        classroom = {f"e2e/classroom/c{i}.spec.ts": 6 * u for i in range(4)}
        present = fake_present(public, classroom)
        out = e2e_plan.shards(present, {"public": {"a"}, "operator": set(), "classroom": {"classroom"}}, {**public, **classroom})
        cost = {**public, **classroom}
        loads = [sum(cost[f] for f in s["paths"].split()) for s in out]
        self.assertEqual(len(out), 3)  # 합 2.4 × SHARD_SECONDS → 3조각
        self.assertEqual(sorted(s["project"] for s in out), ["classroom", "classroom", "public"])
        self.assertLessEqual(max(loads) - min(loads), 1e-9)

    def test_new_spec_without_record_counts_as_the_average(self) -> None:
        present = fake_present({"e2e/a/old.spec.ts": 1, "e2e/a/new.spec.ts": 1}, {"e2e/classroom/c.spec.ts": 1})
        cost = e2e_plan.costs({"e2e/a/old.spec.ts": 2.0, "e2e/classroom/c.spec.ts": 10.0, "e2e/gone.spec.ts": 99.0}, present)
        self.assertEqual(cost["e2e/a/new.spec.ts"], 6.0)  # 지금 있는 파일의 기록 평균 — 지운 파일(99초)은 세지 않는다

    def test_shard_count_stays_within_bounds(self) -> None:
        many = {f"e2e/a/p{i:03}.spec.ts": 10.0 for i in range(100)}
        present = fake_present(many, {"e2e/classroom/c.spec.ts": 0.5})
        out = e2e_plan.shards(present, {"public": {"a"}, "operator": set(), "classroom": {"classroom"}}, {**many, "e2e/classroom/c.spec.ts": 0.5})
        self.assertEqual(len(out), e2e_plan.MAX_SHARDS)
        self.assertIn("classroom", {s["project"] for s in out})  # 짧아도 프로젝트마다 한 조각은 있다
        tiny = e2e_plan.shards(present, {"public": set(), "operator": set(), "classroom": {"classroom"}}, {"e2e/classroom/c.spec.ts": 0.5})
        self.assertEqual(len(tiny), 1)

    def test_seed_record_covers_every_spec(self) -> None:
        seed = e2e_durations.read_record()
        missing = e2e_durations.spec_files() - set(seed)
        self.assertLessEqual(len(missing), 5, f"씨앗 기록이 많이 낡았다 — e2e.yml 의 e2e-durations 산출물로 다시 쓴다: {sorted(missing)}")

    def test_real_plan_spread_on_the_seed(self) -> None:
        shards = e2e_plan.plan(None, e2e_durations.read_record())["include"]
        seconds = [float(s["seconds"]) for s in shards]
        self.assertLess(max(seconds) - min(seconds), 15, shards)


def report(*tests: tuple[str, float, str]) -> dict[str, object]:
    return {"suites": [{"file": f, "specs": [{"file": f, "tests": [{"results": [{"duration": ms, "status": st}]}]}], "suites": []} for f, ms, st in tests]}


class DurationRecord(unittest.TestCase):
    def measure(self, *reports: dict[str, object]) -> dict[str, float]:
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i, r in enumerate(reports):
                path = Path(d) / f"{i}.json"
                path.write_text(json.dumps(r))
                paths.append(path)
            return e2e_durations.measured(paths)

    def test_passes_are_summed_and_failures_are_not_measured(self) -> None:
        got = self.measure(
            report(("e2e/a/x.spec.ts", 1500, "passed"), ("e2e/a/bad.spec.ts", 3000, "failed")),
            report(("e2e/a/x.spec.ts", 500, "passed"), ("e2e/a/live.spec.ts", 0, "skipped")),
        )
        self.assertEqual(got, {"e2e/a/x.spec.ts": 2.0, "e2e/a/live.spec.ts": 0.0})

    def test_tests_without_results_are_not_measured(self) -> None:
        empty = {"suites": [{"file": "e2e/a/x.spec.ts", "specs": [{"file": "e2e/a/x.spec.ts", "tests": [{"results": []}]}]}]}
        self.assertEqual(self.measure(empty), {})

    def test_merge_averages_keeps_unmeasured_and_drops_deleted(self) -> None:
        got = e2e_durations.merge(
            {"keep.spec.ts": 3.0, "avg.spec.ts": 4.0, "gone.spec.ts": 9.0},
            {"avg.spec.ts": 2.0, "new.spec.ts": 5.0},
            {"keep.spec.ts", "avg.spec.ts", "new.spec.ts", "never.spec.ts"},
        )
        self.assertEqual(got, {"avg.spec.ts": 3.0, "keep.spec.ts": 3.0, "new.spec.ts": 5.0})


if __name__ == "__main__":
    unittest.main()
