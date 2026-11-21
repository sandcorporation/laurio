"""scripts/ci/fail_fast.py — 잡 하나가 실패하면 실행을 멈추는 감시와 「처음 실패」 요약(#1139).

    python3 scripts/test_fail_fast.py
"""

from __future__ import annotations

import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))

from fail_fast import Job, decide, summary, watch  # noqa: E402

SKIP = ("결과", "빨리 멈춤")


def job(name: str, status: str = "completed", conclusion: str | None = "success", at: str | None = "2026-11-21T00:00:10Z") -> Job:
    return Job(name=name, status=status, conclusion=conclusion if status == "completed" else None, completed_at=at)


class FakeApi:
    """GitHub 의 잡 목록·취소를 흉내 낸다 — 취소는 포크 PR 처럼 403 을 줄 수 있다."""

    def __init__(self, polls: list[list[Job] | Exception], cancel_status: int = 202) -> None:
        self.polls = polls
        self.cancel_status = cancel_status
        self.cancelled = 0

    def jobs(self) -> list[Job]:
        item = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        if isinstance(item, Exception):
            raise item
        return item

    def cancel(self) -> int:
        self.cancelled += 1
        if self.cancel_status >= 400:
            raise urllib.error.HTTPError("u", self.cancel_status, "x", Message(), None)
        return self.cancel_status


def run(api: FakeApi) -> list[str]:
    logs: list[str] = []
    self_code = watch(api, SKIP, sleep=lambda _: None, log=logs.append)
    assert self_code == 0
    return logs


class Decide(unittest.TestCase):
    def test_waits_while_jobs_run(self) -> None:
        self.assertEqual(decide([job("plan"), job("checks static", "in_progress")], SKIP), "wait")

    def test_a_failure_cancels_even_while_others_run(self) -> None:
        jobs = [job("plan"), job("e2e web-1", "in_progress"), job("agent-grader", conclusion="failure")]
        self.assertEqual(decide(jobs, SKIP), "cancel")

    def test_timed_out_counts_as_failure(self) -> None:
        self.assertEqual(decide([job("e2e web-1", conclusion="timed_out"), job("celery", "in_progress")], SKIP), "cancel")

    def test_done_when_every_watched_job_finished_green_or_skipped(self) -> None:
        jobs = [job("plan"), job("guard", conclusion="skipped"), job("빨리 멈춤", "in_progress"), job("결과", "queued")]
        self.assertEqual(decide(jobs, SKIP), "done")

    def test_skipped_names_are_not_watched(self) -> None:
        """감시 자신과 「결과」는 실패로도, 끝남으로도 세지 않는다."""
        self.assertEqual(decide([job("결과", conclusion="failure"), job("checks static", "in_progress")], SKIP), "wait")


class Summary(unittest.TestCase):
    def test_first_line_is_the_earliest_failure_not_the_cancelled(self) -> None:
        jobs = [
            job("checks pytest-1", conclusion="cancelled", at="2026-11-21T00:00:05Z"),
            job("e2e web-2", conclusion="failure", at="2026-11-21T00:03:00Z"),
            job("agent-grader", conclusion="failure", at="2026-11-21T00:01:00Z"),
            job("celery", conclusion="cancelled", at="2026-11-21T00:01:20Z"),
            job("결과", conclusion="failure", at="2026-11-21T00:03:30Z"),
        ]
        lines = summary(jobs, SKIP)
        self.assertEqual(lines[0], "처음 실패: agent-grader (failure, 2026-11-21T00:01:00Z)")
        self.assertEqual(lines[1], "그 밖의 실패: e2e web-2")
        self.assertEqual(lines[2], "취소된 잡 2개(처음 실패로 멈춤): celery, checks pytest-1")

    def test_nothing_when_no_job_failed(self) -> None:
        self.assertEqual(summary([job("plan"), job("celery", conclusion="cancelled")], SKIP), [])


class Watch(unittest.TestCase):
    def test_cancels_once_on_the_first_failure(self) -> None:
        api = FakeApi([
            [job("plan"), job("agent-grader", "in_progress"), job("e2e web-1", "in_progress")],
            [job("plan"), job("agent-grader", conclusion="failure"), job("e2e web-1", "in_progress")],
        ])
        logs = run(api)
        self.assertEqual(api.cancelled, 1)
        self.assertTrue(logs[0].startswith("처음 실패: agent-grader"))

    def test_all_green_ends_without_cancel(self) -> None:
        api = FakeApi([[job("plan"), job("celery", "in_progress")], [job("plan"), job("celery")]])
        run(api)
        self.assertEqual(api.cancelled, 0)

    def test_fork_pr_read_only_token_warns_and_ends(self) -> None:
        api = FakeApi([[job("agent-grader", conclusion="failure"), job("celery", "in_progress")]], cancel_status=403)
        logs = run(api)
        self.assertEqual(api.cancelled, 1)
        self.assertIn("포크 PR", logs[-1])

    def test_repeated_api_errors_give_up_without_failing(self) -> None:
        api = FakeApi([urllib.error.URLError("down")])
        logs = run(api)
        self.assertEqual(api.cancelled, 0)
        self.assertIn("감시를 그만둔다", logs[-1])

    def test_a_transient_api_error_keeps_watching(self) -> None:
        api = FakeApi([urllib.error.URLError("blip"), [job("agent-grader", conclusion="failure")]])
        run(api)
        self.assertEqual(api.cancelled, 1)


if __name__ == "__main__":
    unittest.main()
