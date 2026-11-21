"""스펙 브랜치 흐름(#1210) — PR 검사의 기준(pr-base.sh)과 scripts/spec/spec.py 의 판정.

임시 git 저장소(맨 원격 하나 + 클론)로 기준 계산·start·sync 를 실제로 돌리고, gh 는 가짜 응답으로 merge-ticket·finish·report 를 본다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "spec"))
import spec

PR_BASE = HERE / "ci" / "pr-base.sh"
CHANGED = HERE / "ci" / "changed.sh"

os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def commit(root: Path, path: str, text: str = "y", msg: str = "c") -> str:
    f = root / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)
    return git(root, "rev-parse", "HEAD")


class FakeGh:
    """args 를 한 줄로 이어 붙여 조각이 모두 들어 있는 첫 경로의 응답을 낸다. 부른 것은 calls 에 남는다."""

    def __init__(self, routes: Sequence[tuple[Sequence[str], str | Callable[[Sequence[str]], str]]]):
        self.routes = routes
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        line = " ".join(args)
        for parts, out in self.routes:
            if all(p in line for p in parts):
                return out(args) if callable(out) else out
        raise AssertionError(f"가짜 gh 에 없는 부름: {line}")

    def called(self, *parts: str) -> bool:
        return any(all(p in " ".join(c) for p in parts) for c in self.calls)


class PrBaseTest(unittest.TestCase):
    """기준 — base 가 main 이면 예전(merge-base origin/main HEAD)과 같고, spec/* 이면 그 PR 의 차이만."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = r = Path(self.tmp.name)
        git(r, "init", "-q", "-b", "main")
        self.main = commit(r, "seed")
        git(r, "update-ref", "refs/remotes/origin/main", self.main)
        git(r, "checkout", "-q", "-b", "spec/x")
        self.spec = commit(r, "backend/a/models.py")  # 스펙에 먼저 모인 티켓
        git(r, "checkout", "-q", "-b", "ticket")
        commit(r, "frontend/app/page.tsx")  # 이 티켓 PR 의 차이

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def base(self, target: str) -> str:
        return subprocess.run(["bash", str(PR_BASE), target], cwd=self.root, check=True, capture_output=True,
                              text=True).stdout.strip()

    def plan(self, base: str) -> dict[str, str]:
        out = subprocess.run(["bash", str(CHANGED), base], cwd=self.root, check=True, capture_output=True, text=True).stdout
        return dict(line.split("=", 1) for line in out.split())

    def test_spec_base_sees_only_the_ticket(self) -> None:
        b = self.base(self.spec)
        self.assertEqual(b, self.spec)
        self.assertEqual(self.plan(b), {"TESTS": "1", "BACK": "0", "FRONT": "1"})

    def test_main_base_is_unchanged(self) -> None:
        old = git(self.root, "merge-base", "origin/main", "HEAD")
        self.assertEqual(self.base(self.main), old)
        self.assertEqual(self.base(""), old)
        self.assertEqual(self.plan(old)["BACK"], "1")  # main 으로 가는 PR 은 스펙 전체가 바뀐 것

    def test_unknown_base_falls_back_to_main(self) -> None:
        self.assertEqual(self.base("ab" * 20), self.main)


def checks(*runs: tuple[str, str | None, str]) -> str:
    return json.dumps([{"id": i, "status": s, "conclusion": c, "started_at": t, "html_url": f"u{i}"}
                       for i, (s, c, t) in enumerate(runs)])


def pr(base: str = "spec/x", state: str = "OPEN", draft: bool = False) -> str:
    return json.dumps({"number": 7, "baseRefName": base, "headRefOid": "f" * 40, "state": state, "isDraft": draft})


class MergeTicketTest(unittest.TestCase):
    def gh(self, view: str, runs: str) -> FakeGh:
        return FakeGh([(["pr", "view"], view), (["check-runs", "check_name=결과"], runs), (["pr", "merge"], "")])

    def refused(self, gh: FakeGh, word: str) -> None:
        with self.assertRaises(spec.Refused) as e:
            spec.merge_ticket("7", gh)
        self.assertIn(word, str(e.exception))
        self.assertFalse(gh.called("pr", "merge"))

    def test_merges_green_spec_pr(self) -> None:
        gh = self.gh(pr(), checks(("completed", "success", "2026-11-21T01:00:00Z")))
        spec.merge_ticket("7", gh)
        self.assertTrue(gh.called("pr", "merge", "7", "--squash", "--match-head-commit", "f" * 40))

    def test_refuses_main_base(self) -> None:
        self.refused(self.gh(pr(base="main"), checks(("completed", "success", "t"))), "enqueue.sh")

    def test_refuses_red(self) -> None:
        self.refused(self.gh(pr(), checks(("completed", "failure", "t"))), "failure")

    def test_refuses_running_and_missing(self) -> None:
        self.refused(self.gh(pr(), checks(("in_progress", None, "t"))), "아직")
        self.refused(self.gh(pr(), "[]"), "없다")

    def test_latest_run_decides(self) -> None:
        self.refused(self.gh(pr(), checks(("completed", "success", "2026-11-21T01:00:00Z"),
                                          ("completed", "failure", "2026-11-21T02:00:00Z"))), "failure")
        gh = self.gh(pr(), checks(("completed", "failure", "2026-11-21T01:00:00Z"),
                                  ("completed", "success", "2026-11-21T02:00:00Z")))
        spec.merge_ticket("7", gh)
        self.assertTrue(gh.called("pr", "merge"))

    def test_refuses_closed_and_draft(self) -> None:
        self.refused(self.gh(pr(state="MERGED"), checks(("completed", "success", "t"))), "MERGED")
        self.refused(self.gh(pr(draft=True), checks(("completed", "success", "t"))), "초안")


class GitFlowTest(unittest.TestCase):
    """start·sync — 맨 원격 하나와 클론 둘(사람 하나는 main 에, 하나는 스펙 워크트리에)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.origin = t / "origin.git"
        git(t, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.a = t / "a"
        git(t, "clone", "-q", str(self.origin), str(self.a))
        commit(self.a, "shared.txt", "base\n")
        git(self.a, "push", "-q", "origin", "HEAD:main")
        self.assertIn("spec/x 만듦", spec.start("x", cwd=self.a))
        self.b = t / "b"
        git(t, "clone", "-q", "-b", "spec/x", str(self.origin), str(self.b))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def spec_log(self) -> str:
        git(self.a, "fetch", "-q", "origin")
        return git(self.a, "log", "--format=%B", "origin/spec/x")

    def test_start_marks_and_refuses_twice(self) -> None:
        self.assertIn("Spec-Start: x", self.spec_log())
        with self.assertRaises(spec.Refused):
            spec.start("x", cwd=self.a)
        with self.assertRaises(spec.Refused):
            spec.start("Bad Name", cwd=self.a)

    def test_clean_sync_records_zero(self) -> None:
        commit(self.a, "main-only.txt")
        git(self.a, "push", "-q", "origin", "HEAD:main")
        commit(self.b, "spec-only.txt")
        git(self.b, "push", "-q", "origin", "HEAD:spec/x")
        self.assertIn("충돌 0", spec.sync("x", cwd=self.b))
        self.assertIn("Spec-Sync-Conflicts: 0", self.spec_log())
        self.assertIn("push 할 것 없음", spec.sync("x", cwd=self.b))

    def test_conflict_stops_and_trailer_survives_commit(self) -> None:
        commit(self.a, "shared.txt", "main\n")
        git(self.a, "push", "-q", "origin", "HEAD:main")
        commit(self.b, "shared.txt", "spec\n")
        git(self.b, "push", "-q", "origin", "HEAD:spec/x")
        with self.assertRaises(spec.Refused) as e:
            spec.sync("x", cwd=self.b)
        self.assertIn("충돌 1개", str(e.exception))
        self.assertIn("shared.txt", str(e.exception))
        self.assertNotIn("Spec-Sync-Conflicts", self.spec_log())  # 멈췄으니 push 없음
        (self.b / "shared.txt").write_text("both\n")
        git(self.b, "add", "shared.txt")
        git(self.b, "commit", "-q", "--no-edit")
        self.assertIn("push", spec.sync("x", cwd=self.b))
        self.assertIn("Spec-Sync-Conflicts: 1", self.spec_log())

    def test_sync_refuses_other_branch(self) -> None:
        with self.assertRaises(spec.Refused) as e:
            spec.sync("x", cwd=self.a)
        self.assertIn("spec/x 를 체크아웃한", str(e.exception))


class FinishTest(unittest.TestCase):
    def test_body_collects_closes_once(self) -> None:
        tickets = [{"number": 12, "title": "둘", "body": "Closes #5\nRefs #1\nfixes #6"},
                   {"number": 11, "title": "하나", "body": "Closes #5"}]
        gh = FakeGh([(["--state", "merged"], json.dumps(tickets)), (["--state", "open"], "[]"),
                     (["pr", "create"], "https://example.test/pull/20\n")])
        out = spec.finish("x", None, gh)
        self.assertIn("enqueue.sh 20 --wait", out)
        create = next(c for c in gh.calls if c[:2] == ["pr", "create"])
        body = create[create.index("--body") + 1]
        self.assertEqual([ln for ln in body.splitlines() if ln.startswith("Closes")], ["Closes #5", "Closes #6"])
        self.assertNotIn("#1\n", body.replace("Refs #1", ""))
        self.assertLess(body.index("#11 하나"), body.index("#12 둘"))
        self.assertEqual(create[create.index("--base") + 1], "main")
        self.assertEqual(create[create.index("--head") + 1], "spec/x")


def runs(*items: tuple[int, str, str]) -> str:
    return json.dumps([{"id": i, "head_branch": b, "created_at": t} for i, b, t in items])


def cm(date: str, msg: str) -> dict[str, object]:
    return {"sha": "s", "commit": {"message": msg, "author": {"date": date}}}


class ReportTest(unittest.TestCase):
    def test_spec_numbers(self) -> None:
        main_pr = [{"number": 30, "headRefName": "spec/x", "state": "MERGED", "mergedAt": "2026-11-22T05:00:00Z",
                    "mergeCommit": {"oid": "m" * 40}}]
        commits = [cm("2026-11-21T01:00:00Z", "spec/x 착수\n\nSpec-Start: x"),
                   cm("2026-11-21T03:00:00Z", "티켓"),
                   cm("2026-11-21T09:00:00Z", "spec/x ← main 따라잡기\n\nSpec-Sync-Conflicts: 2"),
                   cm("2026-11-22T01:00:00Z", "spec/x ← main 따라잡기\n\nSpec-Sync-Conflicts: 1")]
        gh = FakeGh([
            (["pr list --base spec/x"], json.dumps([{"number": 21}, {"number": 22}, {"number": 23}])),
            (["pr list --head spec/x"], json.dumps(main_pr)),
            (["pulls/30/commits"], json.dumps(commits)),
            (["branch=spec/x", "event=pull_request"], runs((101, "spec/x", "2026-11-22T02:00:00Z"),
                                                           (102, "spec/x", "2026-11-22T03:00:00Z"))),
            (["event=merge_group"], runs((201, "gh-readonly-queue/main/pr-30-abc", "2026-11-22T04:00:00Z"),
                                         (202, "gh-readonly-queue/main/pr-31-abc", "2026-11-22T04:30:00Z"))),
            (["statuses"], json.dumps([{"context": "sandcorp/deploy", "state": "pending", "created_at": "2026-11-22T05:10:00Z"},
                                       {"context": "sandcorp/deploy", "state": "success", "created_at": "2026-11-22T05:20:00Z"}])),
            (["runs/201/jobs"], json.dumps([{"conclusion": "success"}, {"conclusion": "failure"}, {"conclusion": "skipped"}])),
        ])
        n = spec.report_spec("x", gh)
        self.assertEqual((n.started, n.deployed), ("2026-11-21T01:00:00Z", "2026-11-22T05:20:00Z"))
        self.assertEqual((n.tickets, n.pr_checks, n.queue_checks, n.deploys), (3, 2, 1, 1))
        self.assertEqual((n.last_run, n.last_failures), (201, 1))
        self.assertEqual((n.conflicts, n.syncs), (3, 2))
        self.assertIn("1일 4시간 20분", "\n".join(n.lines()))

    def test_per_ticket_prs(self) -> None:
        def view(args: Sequence[str]) -> str:
            k = int(args[2])
            return json.dumps({"number": k, "headRefName": f"t{k}", "state": "MERGED", "mergedAt": "x",
                               "mergeCommit": {"oid": f"{k}" * 20}})

        def pr_runs(args: Sequence[str]) -> str:
            b = next(a for a in args if a.startswith("branch="))[len("branch="):]
            return runs((int(b[1:]) * 10, b, f"2026-11-2{b[-1]}T00:00:00Z"))

        gh = FakeGh([
            (["pr", "view"], view),
            (["pulls/1/commits"], json.dumps([cm("2026-11-20T00:00:00Z", "a")])),
            (["pulls/2/commits"], json.dumps([cm("2026-11-19T00:00:00Z", "b")])),
            (["event=pull_request"], pr_runs),
            (["event=merge_group"], runs((5, "gh-readonly-queue/main/pr-1-x", "2026-11-20T00:00:00Z"),
                                         (6, "gh-readonly-queue/main/pr-2-x", "2026-11-20T01:00:00Z"))),
            (["commits/11111111111111111111/statuses"], json.dumps([{"context": "sandcorp/deploy", "state": "success",
                                                                       "created_at": "2026-11-21T00:00:00Z"}])),
            (["commits/22222222222222222222/statuses"], json.dumps([{"context": "sandcorp/deploy", "state": "success",
                                                                       "created_at": "2026-11-22T00:00:00Z"}])),
            (["/jobs"], json.dumps([{"conclusion": "success"}])),
        ])
        n = spec.report_prs([1, 2], gh)
        self.assertEqual((n.started, n.deployed), ("2026-11-19T00:00:00Z", "2026-11-22T00:00:00Z"))
        self.assertEqual((n.tickets, n.pr_checks, n.queue_checks, n.deploys), (2, 2, 2, 2))
        self.assertEqual((n.last_run, n.last_failures), (20, 0))
        self.assertIsNone(n.conflicts)


if __name__ == "__main__":
    unittest.main()
