"""CI 재실행 판정(scripts/ci/rerun_verdict.py, #1207) — 저장된 로그 조각(가짜 데이터)으로 판정한다. 네트워크 없음."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))

import rerun_verdict as rv  # noqa: E402

TS = "2026-01-01T00:00:00.0000000Z"


def job(step: str, *lines: str, name: str = "e2e demo-1") -> rv.FailedJob:
    return rv.FailedJob(name, step, [f"{name}\t{step}\t{TS} {x}" for x in lines])


PROXY = "Error response from daemon: failed to start userland proxy for port mapping 0.0.0.0:1:2:3/tcp: timed out"
FETCH = "DownloadError: Failed to fetch manifest from https://github.com/example/tree-sitter-language-pack/releases/parsers.json"
CAUSES = [
    rv.Cause("프록시", re.compile("failed to start userland proxy for port mapping"), 1, ""),
    rv.Cause("문법 받기", re.compile(r"Failed to fetch manifest from https://github\.com/.*/tree-sitter-language-pack"), 0, "#1"),
]


class Verdicts(unittest.TestCase):
    def test_known_cause_before_tests_first_time_is_allowed(self) -> None:
        v = rv.judge_job(job("e2e(e2e.sh)", "빌드 시작", FETCH), CAUSES, 0)
        self.assertTrue(v.ok)
        self.assertEqual(v.cause, "문법 받기")
        self.assertIn("Failed to fetch manifest", v.cause_line)

    def test_proxy_cause_is_not_allowed_because_already_counted_once(self) -> None:
        v = rv.judge_job(job("e2e(e2e.sh)", PROXY), CAUSES, 0)
        self.assertFalse(v.ok)
        self.assertIn("티켓을 올려라", v.reason)

    def test_counted_cause_names_its_ticket(self) -> None:
        causes = [rv.Cause("프록시", re.compile("userland proxy"), 2, "#7")]
        self.assertIn("#7", rv.judge_job(job("e2e", PROXY), causes, 0).reason)

    def test_test_step_is_not_allowed(self) -> None:
        v = rv.judge_job(job("pytest 조각", FETCH), CAUSES, 0)
        self.assertFalse(v.ok)
        self.assertIn("시험 단계", v.reason)

    def test_cause_line_after_tests_started_is_not_allowed(self) -> None:
        v = rv.judge_job(job("e2e(e2e.sh)", "Running 12 tests using 2 workers", FETCH), CAUSES, 0)
        self.assertFalse(v.ok)
        self.assertIn("시험이 시작된 뒤", v.reason)

    def test_unknown_cause_is_not_allowed(self) -> None:
        v = rv.judge_job(job("e2e(e2e.sh)", "Error: something else"), CAUSES, 0)
        self.assertFalse(v.ok)
        self.assertIn("알려진 인프라 원인 줄이 없다", v.reason)

    def test_second_rerun_on_same_pr_is_not_allowed(self) -> None:
        v = rv.judge_job(job("e2e(e2e.sh)", FETCH), CAUSES, 1)
        self.assertFalse(v.ok)
        self.assertIn("이 PR 에서", v.reason)

    def test_cumulative_second_is_not_allowed_even_on_new_pr(self) -> None:
        causes = [rv.Cause("문법 받기", re.compile("Failed to fetch manifest"), 1, "#1")]
        v = rv.judge_job(job("e2e(e2e.sh)", FETCH), causes, 0)
        self.assertFalse(v.ok)
        self.assertIn("티켓을 올려라", v.reason)


class Run(unittest.TestCase):
    def test_allowed_run_prints_comment_body_with_run_number_and_cause_line(self) -> None:
        ok, text = rv.judge_run("123", [job("e2e(e2e.sh)", FETCH)], CAUSES, 0)
        self.assertTrue(ok)
        self.assertTrue(text.startswith("재실행 가능 — "))
        self.assertIn(rv.COMMENT_PREFIX + "run 123", text)
        self.assertIn("Failed to fetch manifest", text)

    def test_one_bad_job_makes_the_whole_run_not_allowed(self) -> None:
        ok, text = rv.judge_run("1", [job("e2e", FETCH), job("e2e", "Error: x", name="e2e demo-2")], CAUSES, 0)
        self.assertFalse(ok)
        self.assertTrue(text.startswith("재실행 불가 — "))

    def test_no_failed_job_is_not_allowed(self) -> None:
        self.assertFalse(rv.judge_run("1", [], CAUSES, 0)[0])

    def test_rerun_comments_are_counted_by_first_line_marker(self) -> None:
        self.assertEqual(rv.count_reruns([rv.COMMENT_PREFIX + "run 1\n- 원인", "그냥 댓글", "text " + rv.COMMENT_PREFIX]), 1)

    def test_failed_log_is_split_by_job_and_step_and_prefix_is_stripped(self) -> None:
        raw = f"a\tb\t{TS} one\na\tb\t{TS} two\nc\td\t{TS} three"
        parts = rv.split_failed_log(raw)
        self.assertEqual(len(parts[("a", "b")]), 2)
        self.assertEqual(rv.strip_prefix(parts[("c", "d")][0]), "three")

    def test_shipped_table_has_the_two_known_causes(self) -> None:
        names = {c.ticket for c in rv.load_causes()}
        self.assertIn("#1205", names)
        self.assertTrue(any(c.pattern.search(PROXY) for c in rv.load_causes()))


if __name__ == "__main__":
    unittest.main()
