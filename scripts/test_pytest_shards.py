"""pytest 조각 나누기(#1083) — `scripts/ci/pytest_shards.py`. 네트워크·도커 없음, PR 검사 static 이 돌린다."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))

from pytest_shards import durations_from_junit, file_of, shards, test_files  # noqa: E402


class ShardsTest(unittest.TestCase):
    def test_slow_files_spread_so_shards_are_even(self) -> None:
        durations = {"a.py": 40.0, "b.py": 30.0, "c.py": 20.0, "d.py": 10.0, "e.py": 10.0, "f.py": 10.0}
        out = shards(durations, durations, 3)
        loads = [sum(durations[f] for f in s) for s in out]
        self.assertEqual(sorted(loads), [40.0, 40.0, 40.0])

    def test_every_file_lands_in_exactly_one_shard(self) -> None:
        files = [f"t{i}.py" for i in range(23)]
        out = shards(files, {}, 4)
        self.assertEqual(sorted(f for s in out for f in s), sorted(files))
        self.assertEqual([len(s) for s in out], [6, 6, 6, 5])

    def test_unrecorded_file_counts_as_the_average(self) -> None:
        # 기록 평균 20 → 새 파일 new.py 는 20 으로 세어 가벼운 조각(10)으로 간다
        out = shards(["big.py", "small.py", "new.py"], {"big.py": 30.0, "small.py": 10.0}, 2)
        self.assertEqual(out, [["big.py"], ["new.py", "small.py"]])

    def test_same_input_gives_same_shards(self) -> None:
        durations = {f"t{i}.py": float(i % 5) for i in range(40)}
        self.assertEqual(shards(durations, durations, 4), shards(reversed(list(durations)), durations, 4))


class JunitTest(unittest.TestCase):
    FILES = {"tests/test_a.py", "tests/api/test_b.py"}

    def test_classname_maps_to_the_file(self) -> None:
        self.assertEqual(file_of("tests.test_a.TestX", self.FILES), "tests/test_a.py")
        self.assertEqual(file_of("tests.test_a", self.FILES), "tests/test_a.py")
        self.assertEqual(file_of("tests.api.test_b.TestY.TestZ", self.FILES), "tests/api/test_b.py")
        self.assertIsNone(file_of("tests.gone.TestX", self.FILES))

    def test_times_summed_per_file_across_shard_reports(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            one, two = Path(d, "1.xml"), Path(d, "2.xml")
            one.write_text(
                '<testsuites><testsuite><testcase classname="tests.test_a.T" name="x" time="1.5"/>'
                '<testcase classname="tests.gone.T" name="y" time="9"/></testsuite></testsuites>'
            )
            two.write_text(
                '<testsuites><testsuite><testcase classname="tests.test_a" name="z" time="0.25"/>'
                '<testcase classname="tests.api.test_b.T" name="w" time="2"/></testsuite></testsuites>'
            )
            self.assertEqual(
                durations_from_junit([one, two], self.FILES), {"tests/api/test_b.py": 2.0, "tests/test_a.py": 1.75}
            )

    def test_file_with_no_cases_is_recorded_as_zero_not_average(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            one = Path(d, "1.xml")
            one.write_text('<testsuite><testcase classname="tests.test_a.T" name="x" time="3"/></testsuite>')
            self.assertEqual(durations_from_junit([one], self.FILES), {"tests/api/test_b.py": 0.0, "tests/test_a.py": 3.0})


class RealTreeTest(unittest.TestCase):
    def test_backend_has_test_files_and_four_shards_cover_them(self) -> None:
        files = test_files()
        self.assertGreater(len(files), 100)
        self.assertTrue(all(f.startswith("tests/") and f.endswith(".py") for f in files))
        out = shards(files, {}, 4)
        self.assertEqual(sum(len(s) for s in out), len(files))


if __name__ == "__main__":
    unittest.main()
