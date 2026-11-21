"""스펙 브랜치 흐름(#1210, #1228) — PR 검사의 기준(pr-base.sh)과 scripts/spec/spec.py 의 판정.

임시 git 저장소(맨 원격 하나 + 클론)로 기준 계산·start·sync 를 실제로 돌리고, push·finish·blame 도 실제 git 으로, gh 는 가짜 응답으로 finish·blame·report 를 본다.
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


def ticket(root: Path, path: str, n: int | None, text: str = "y", subject: str | None = None) -> str:
    msg = subject or f"티켓 {n} ({'#' + str(n) if n else '-'})"
    if n is not None:
        msg += f"\n\nSpec-Ticket: #{n}\nCo-Authored-By: t <t@t>"
    return commit(root, path, text, msg)


class SpecRepo(unittest.TestCase):
    """맨 원격 하나 + main 클론(a, 조율자) + 작업자 워크트리 흉내 둘(w1·w2, origin/spec/x 에서 딴 로컬 브랜치)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        t = self.t = Path(self.tmp.name)
        self.origin = t / "origin.git"
        git(t, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.a = t / "a"
        git(t, "clone", "-q", str(self.origin), str(self.a))
        commit(self.a, "shared.txt", "base\n")
        commit(self.a, "backend/a/tests/test_a.py", "base\n")
        git(self.a, "push", "-q", "origin", "HEAD:main")
        spec.start("x", cwd=self.a)
        self.w1 = self.worker("w1")
        self.w2 = self.worker("w2")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def worker(self, name: str) -> Path:
        w = self.t / name
        git(self.t, "clone", "-q", str(self.origin), str(w))
        git(w, "checkout", "-q", "-b", f"t-{name}", "origin/spec/x")
        return w

    def spec_log(self, fmt: str = "%s") -> list[str]:
        git(self.a, "fetch", "-q", "origin")
        return git(self.a, "log", f"--format={fmt}", "origin/main..origin/spec/x").splitlines()


class PushTest(SpecRepo):
    def test_two_chains_land_without_pr(self) -> None:
        ticket(self.w1, "backend/a/one.py", 11)
        ticket(self.w2, "frontend/two.ts", 12)
        self.assertIn("push", spec.push("x", cwd=self.w1))
        self.assertIn("#12", spec.push("x", cwd=self.w2))  # 앞선 w1 을 받아 합치고 올린다
        log = self.spec_log()
        self.assertIn("티켓 11 (#11)", log)
        self.assertIn("티켓 12 (#12)", log)
        ticket(self.w1, "backend/a/three.py", 13)
        spec.push("x", cwd=self.w1)
        self.assertIn("티켓 13 (#13)", self.spec_log())
        self.assertIn("올릴 것 없음", spec.push("x", cwd=self.w1))

    def test_overtaken_between_fetch_and_push_retries(self) -> None:
        ticket(self.w1, "backend/a/one.py", 11)
        ticket(self.w2, "frontend/two.ts", 12)
        raced = []

        def race() -> None:
            if not raced:
                raced.append(1)
                spec.push("x", cwd=self.w2)

        out = spec.push("x", cwd=self.w1, before_push=race)
        self.assertIn("2번째에", out)
        self.assertEqual(len([s for s in self.spec_log() if s.startswith("티켓")]), 2)

    def test_gives_up_after_tries(self) -> None:
        ticket(self.w1, "backend/a/one.py", 11)
        k = iter(range(100))

        def race() -> None:
            ticket(self.w2, f"frontend/f{next(k)}.ts", 12)
            spec.push("x", cwd=self.w2)

        with self.assertRaises(spec.Refused) as e:
            spec.push("x", cwd=self.w1, before_push=race)
        self.assertIn(f"{spec.PUSH_TRIES}번", str(e.exception))

    def test_refuses_dirty_tree(self) -> None:
        ticket(self.w1, "backend/a/one.py", 11)
        (self.w1 / "backend/a/one.py").write_text("half\n")
        with self.assertRaises(spec.Refused) as e:
            spec.push("x", cwd=self.w1)
        self.assertIn("더럽다", str(e.exception))
        self.assertEqual(self.spec_log(), ["spec/x 착수"])

    def test_refuses_commit_without_trailer(self) -> None:
        ticket(self.w1, "backend/a/one.py", 11)
        ticket(self.w1, "backend/a/two.py", None, subject="꼬리말 없음")
        with self.assertRaises(spec.Refused) as e:
            spec.push("x", cwd=self.w1)
        self.assertIn("꼬리말 없음", str(e.exception))
        self.assertIn("Spec-Ticket", str(e.exception))
        self.assertEqual(self.spec_log(), ["spec/x 착수"])

    def test_refuses_conflict_and_names_files(self) -> None:
        ticket(self.w1, "shared.txt", 11, "one\n")
        ticket(self.w2, "shared.txt", 12, "two\n")
        spec.push("x", cwd=self.w1)
        with self.assertRaises(spec.Refused) as e:
            spec.push("x", cwd=self.w2)
        self.assertIn("충돌 1개", str(e.exception))
        self.assertIn("shared.txt", str(e.exception))
        self.assertNotIn("티켓 12 (#12)", self.spec_log())
        (self.w2 / "shared.txt").write_text("both\n")
        git(self.w2, "add", "shared.txt")
        git(self.w2, "commit", "-q", "--no-edit")
        spec.push("x", cwd=self.w2)  # merge 커밋은 꼬리말을 묻지 않는다
        self.assertIn("티켓 12 (#12)", self.spec_log())


    def test_refuses_migration_overlap(self) -> None:
        ticket(self.w1, "backend/a/migrations/0002_one.py", 11)
        ticket(self.w2, "backend/a/migrations/0002_two.py", 12)
        ticket(self.w2, "backend/b/migrations/0002_b.py", 12)
        spec.push("x", cwd=self.w1)
        with self.assertRaises(spec.Refused) as e:
            spec.push("x", cwd=self.w2)
        self.assertIn("앱 backend/a)", str(e.exception))
        git(self.w2, "merge", "-q", "--no-edit", "origin/spec/x")
        git(self.w2, "mv", "backend/a/migrations/0002_two.py", "backend/a/migrations/0003_two.py")
        git(self.w2, "commit", "-q", "-m", "번호 옮김\n\nSpec-Ticket: #12")
        self.assertIn("push", spec.push("x", cwd=self.w2))


class FinishTest(SpecRepo):
    def gh(self) -> FakeGh:
        return FakeGh([(["--state", "open"], "[]"), (["pr", "create"], "https://example.test/pull/20\n")])

    def test_body_from_trailers(self) -> None:
        ticket(self.w1, "backend/a/one.py", 12)
        ticket(self.w1, "backend/a/one2.py", 11)
        spec.push("x", cwd=self.w1)
        fix = ticket(self.w2, "frontend/two.ts", 12, subject="12 고침")
        spec.push("x", cwd=self.w2)
        gh = self.gh()
        out = spec.finish("x", None, gh, cwd=self.a)
        self.assertIn("enqueue.sh 20 --wait", out)
        self.assertIn("spec.py push x", out)  # 붉으면 같은 브랜치에 push → 같은 PR
        self.assertIn("spec.py blame x", out)
        create = next(c for c in gh.calls if c[:2] == ["pr", "create"])
        body = create[create.index("--body") + 1]
        self.assertEqual([ln for ln in body.splitlines() if ln.startswith("Closes")], ["Closes #11", "Closes #12"])
        self.assertIn(f"  - {fix[:12]} 12 고침", body)
        self.assertLess(body.index("- #11"), body.index("- #12"))
        self.assertNotIn("착수", body.split("##", 1)[1])
        self.assertEqual(create[create.index("--head") + 1], "spec/x")
        self.assertFalse(gh.called("--state", "merged"))  # 티켓 PR 을 찾지 않는다

    def test_refuses_empty_spec(self) -> None:
        with self.assertRaises(spec.Refused):
            spec.finish("x", None, self.gh(), cwd=self.a)

    def test_open_pr_gets_new_body(self) -> None:
        ticket(self.w1, "backend/a/one.py", 11)
        spec.push("x", cwd=self.w1)
        gh = FakeGh([(["--state", "open"], json.dumps([{"url": "https://example.test/pull/20"}])), (["pr", "edit"], "")])
        self.assertIn("본문만", spec.finish("x", None, gh, cwd=self.a))
        self.assertFalse(gh.called("pr", "create"))


class BlameTest(SpecRepo):
    def setUp(self) -> None:
        super().setUp()
        ticket(self.w1, "backend/a/tests/test_a.py", 11, "one\n")
        self.last = ticket(self.w1, "backend/a/tests/test_a.py", 13, "three\n", subject="셋 (#13)")
        ticket(self.w1, "frontend/e2e/page.spec.ts", 12)
        spec.push("x", cwd=self.w1)

    def test_by_path_names_last_ticket(self) -> None:
        out = spec.blame("x", "backend/a/tests/test_a.py", cwd=self.a)
        self.assertEqual(out, f"backend/a/tests/test_a.py ← #13 {self.last[:12]} 셋 (#13)")
        self.assertIn("바꾸지 않았다", spec.blame("x", "shared.txt", cwd=self.a))

    def test_by_run_reads_failed_log(self) -> None:
        log = ("pytest (1)\tRun\t2026-11-21T01:00:00Z FAILED backend/a/tests/test_a.py::test_x - assert 1\n"
               "e2e (frontend)\tRun\t2026-11-21T01:00:00Z   1) [chromium] › e2e/page.spec.ts:12:3 › 화면\n"
               "x\ty\tz Traceback in /usr/lib/python3/site.py\n")
        gh = FakeGh([(["run", "view", "4242", "--log-failed"], log)])
        lines = spec.blame("x", "4242", gh, cwd=self.a).splitlines()
        self.assertEqual([ln.split(" ← ")[0] for ln in lines], ["backend/a/tests/test_a.py", "frontend/e2e/page.spec.ts"])
        self.assertIn("#12", lines[1])

    def test_run_without_paths_refuses(self) -> None:
        with self.assertRaises(spec.Refused):
            spec.blame("x", "4242", FakeGh([(["--log-failed"], "boom\n")]), cwd=self.a)


def runs(*items: tuple[int, str, str]) -> str:
    return json.dumps([{"id": i, "head_branch": b, "created_at": t} for i, b, t in items])


def cm(date: str, msg: str) -> dict[str, object]:
    return {"sha": "s", "commit": {"message": msg, "author": {"date": date}}}


class ReportTest(unittest.TestCase):
    def test_spec_numbers(self) -> None:
        main_pr = [{"number": 30, "headRefName": "spec/x", "state": "MERGED", "mergedAt": "2026-11-22T05:00:00Z",
                    "mergeCommit": {"oid": "m" * 40}}]
        commits = [cm("2026-11-21T01:00:00Z", "spec/x 착수\n\nSpec-Start: x"),
                   cm("2026-11-21T03:00:00Z", "하나 (#21)\n\nSpec-Ticket: #21"),
                   cm("2026-11-21T04:00:00Z", "둘 (#22)\n\nSpec-Ticket: #22\nSpec-Ticket: #23"),
                   cm("2026-11-21T05:00:00Z", "둘 고침\n\nSpec-Ticket: #22"),
                   cm("2026-11-21T09:00:00Z", "spec/x ← main 따라잡기\n\nSpec-Sync-Conflicts: 2"),
                   cm("2026-11-22T01:00:00Z", "spec/x ← main 따라잡기\n\nSpec-Sync-Conflicts: 1")]
        gh = FakeGh([
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
