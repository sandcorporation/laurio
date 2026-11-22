#!/usr/bin/env python3
"""핫픽스 길(#1325) — `python3 scripts/test_hotfix_flow.py` 하나로 돈다(PR 검사의 plan 잡이 부른다).

- push_kind.py: 대기열 커밋 · 표식 있는 핫픽스 · 표식 없는 직접 push 를 실제 git 으로 가른다(gh 는 가짜).
- after-push-notify.sh → ci-issue.sh → ci_red_relay.py: 가짜 gh(이슈를 파일에 둔다)와 가짜 switchboard 로
  「실패 → 대장 메일 1통, 이어지는 실패는 같은 이슈 댓글, 다시 초록이면 복구 알림」과 표식 없는 push 알림을 보인다.
- hotfix.py: 맨 원격 하나 + 클론으로 표식·따라잡기·push·dry-run·거절을 실제 git 으로 돌린다. 진짜 main 에는 닿지 않는다.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "ci"))
sys.path.insert(0, str(HERE))
import ci_red_relay
import hotfix
import push_kind

NOTIFY = HERE / "ci" / "after-push-notify.sh"
RELAY = HERE / "ci" / "ci_red_relay.py"

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


def fake_gh(answers: dict[str, str]) -> push_kind.Gh:
    """args 한 줄에 열쇠 조각이 든 첫 응답. 값이 "!" 면 실패."""

    def gh(args: Sequence[str]) -> str:
        line = " ".join(args)
        for part, out in answers.items():
            if part in line:
                if out == "!":
                    raise RuntimeError("gh 실패")
                return out
        raise AssertionError(f"가짜 gh 에 없는 부름: {line}")

    return gh


# ── push_kind ───────────────────────────────────────────────────────────────────────────
class PushKindTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.r = Path(tmp.name)
        git(self.r, "init", "-q", "-b", "main")
        self.base = commit(self.r, "a.txt", "a")

    def kind(self, sha: str, before: str, queue: str = "0") -> tuple[str, list[str]]:
        return push_kind.classify(sha, before, "o/r", cwd=self.r, gh=fake_gh({"event=merge_group": queue}))

    def test_queue_commit_is_not_checked_again(self) -> None:
        sha = commit(self.r, "b.txt", msg="PR (#1)")
        self.assertEqual(self.kind(sha, self.base, queue="1"), ("queue", []))

    def test_marked_commits_are_hotfix(self) -> None:
        commit(self.r, "b.txt", msg="고침\n\nHotfix: #1316")
        sha = commit(self.r, "c.txt", msg="또 고침\n\nHotfix: #1316\nCo-Authored-By: t <t@t>")
        self.assertEqual(self.kind(sha, self.base), ("hotfix", []))

    def test_one_unmarked_commit_makes_direct(self) -> None:
        bare = commit(self.r, "b.txt", msg="표식 없음")
        sha = commit(self.r, "c.txt", msg="고침\n\nHotfix: #1")
        kind, unmarked = self.kind(sha, self.base)
        self.assertEqual(kind, "direct")
        self.assertEqual(unmarked, [bare[:12]])

    def test_lookup_failure_is_loud(self) -> None:
        sha = commit(self.r, "b.txt", msg="고침\n\nHotfix: #1")
        self.assertEqual(self.kind(sha, self.base, queue="!")[0], "direct")

    def test_unknown_before_looks_at_head_only(self) -> None:
        commit(self.r, "b.txt", msg="표식 없음")
        sha = commit(self.r, "c.txt", msg="고침\n\nHotfix: #1")
        self.assertEqual(self.kind(sha, "0" * 40), ("hotfix", []))


# ── 알림 → 대장 메일 ────────────────────────────────────────────────────────────────────
# 이슈를 $FAKE_STATE 에 둔다. ci-issue.sh 가 쓰는 꼴(-q 로 제목 고르기 · create · comment · close · edit)과
# 전달기가 쓰는 꼴(--state all --json …, view --json comments)만 흉내 낸다.
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
p = os.environ["FAKE_STATE"]
s = json.load(open(p)) if os.path.exists(p) else {"issues": []}
def opt(name):
    return a[a.index(name) + 1] if name in a else None
def find(n):
    return next(i for i in s["issues"] if i["number"] == int(n))
out = ""
if a[:2] == ["issue", "list"]:
    if opt("--state") == "open":
        hit = [i for i in s["issues"] if i["state"] == "OPEN" and i["title"] == os.environ.get("TITLE")]
        out = str(hit[0]["number"]) if hit else ""
    else:
        out = json.dumps([{k: i[k] for k in ("number", "title", "state", "body")} for i in s["issues"]])
elif a[:2] == ["issue", "view"]:
    i = find(a[2])
    out = "1" if opt("--json") == "assignees" else json.dumps({"comments": [{"body": c} for c in i["comments"]]})
elif a[:2] == ["issue", "create"]:
    n = 100 + len(s["issues"])
    s["issues"].append({"number": n, "title": opt("--title"), "state": "OPEN", "body": opt("--body"), "comments": []})
    out = f"https://github.com/o/r/issues/{n}"
elif a[:2] == ["issue", "comment"]:
    find(a[2])["comments"].append(opt("--body"))
elif a[:2] == ["issue", "close"]:
    find(a[2])["state"] = "CLOSED"
elif a[:2] == ["run", "view"]:
    out = os.environ.get("FAKE_FAILED_JOBS", "")
elif a[:2] in (["issue", "edit"], ["label", "create"]):
    pass
else:
    sys.exit(f"가짜 gh 에 없는 부름: {a}")
json.dump(s, open(p, "w"))
if out:
    print(out)
"""

FAKE_SWITCHBOARD = r"""#!/usr/bin/env python3
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(d, "switchboard-fail")):
    print("connection refused", file=sys.stderr); sys.exit(1)
a = sys.argv[1:]
mail = {"profile": os.environ.get("SWITCHBOARD_PROFILE"), "to": a[a.index("--to") + 1],
        "task": a[a.index("--task") + 1], "subject": a[a.index("--subject") + 1], "body": a[a.index("--body") + 1]}
with open(os.path.join(d, "mails.jsonl"), "a") as f:
    f.write(json.dumps(mail, ensure_ascii=False) + "\n")
n = sum(1 for _ in open(os.path.join(d, "mails.jsonl")))
print(f"#{n} {mail['subject']}\n{mail['profile']} → {mail['to']} · pending")
"""


def _exe(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40


class RelayChainTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        (self.d / "bin").mkdir()
        _exe(self.d / "bin" / "gh", FAKE_GH)
        _exe(self.d / "bin" / "switchboard", FAKE_SWITCHBOARD)
        self.env = {
            **os.environ,
            "PATH": f"{self.d / 'bin'}:{os.environ['PATH']}",
            "FAKE_STATE": str(self.d / "issues.json"),
            "CODEMIT_SWITCHBOARD": str(self.d / "bin" / "switchboard"),
            "CODEMIT_CI_RED_RELAY_STATE": str(self.d / "relay.json"),
            "CI_RED_ASSIGNEE": "",
            "GITHUB_STEP_SUMMARY": str(self.d / "summary"),
            "HOME": str(self.d),
        }
        (self.d / "relay.json").write_text("{}")  # 처음 켤 때 `mark` 가 만든다

    def notify(self, mode: str, **env: str) -> None:
        r = subprocess.run(["bash", str(NOTIFY), mode], env={**self.env, **env}, text=True, capture_output=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def fail(self, sha: str, run: int) -> None:
        self.notify("result", KIND="hotfix", RESULT="failure", SHA=sha, RUN_ID=str(run),
                    RUN_URL=f"https://github.com/o/r/actions/runs/{run}", FAKE_FAILED_JOBS="check / checks pytest-1")

    def relay(self, want: int = 1) -> list[dict[str, str]]:
        """전달기를 한 번 돌리고 이번에 간 메일을 돌려준다."""
        log = self.d / "bin" / "mails.jsonl"
        before = len(log.read_text().splitlines()) if log.exists() else 0
        r = subprocess.run([sys.executable, str(RELAY), "relay"], env=self.env, text=True, capture_output=True, check=False)
        self.assertEqual(r.returncode, want, r.stdout + r.stderr)
        lines = log.read_text().splitlines() if log.exists() else []
        return [json.loads(x) for x in lines[before:]]

    def issues(self) -> list[dict[str, object]]:
        return json.loads((self.d / "issues.json").read_text())["issues"]

    def test_failure_mails_once_comments_after_and_recovery_mails(self) -> None:
        self.fail(SHA_A, 11)
        [mail] = self.relay()
        self.assertEqual((mail["to"], mail["profile"], mail["task"]), ("sandcorp/boss", "codemit-coordinator", "codemit-ci-red"))
        self.assertIn("핫픽스 뒤 검사 실패", mail["subject"])
        self.assertIn(SHA_A[:12], mail["body"])
        self.assertIn("https://github.com/o/r/actions/runs/11", mail["body"])
        self.assertNotIn("pytest-1", mail["body"], "번호·종류·sha·run 링크만")

        self.fail(SHA_B, 12)  # 이어지는 실패 — 같은 이슈에 댓글, 메일 없음
        self.assertEqual(self.relay(), [])
        [issue] = self.issues()
        self.assertEqual(issue["state"], "OPEN")
        self.assertEqual(len(issue["comments"]), 1)  # type: ignore[arg-type]

        self.notify("result", KIND="hotfix", RESULT="success", SHA=SHA_C, RUN_URL="https://github.com/o/r/actions/runs/13")
        [mail] = self.relay()
        self.assertIn("복구", mail["subject"])
        self.assertIn(SHA_C[:12], mail["body"])
        self.assertIn("actions/runs/13", mail["body"])
        self.assertEqual(self.relay(), [])

    def test_next_queue_commit_closes_the_red(self) -> None:
        self.fail(SHA_A, 11)
        self.relay()
        self.notify("result", KIND="queue", RESULT="skipped", SHA=SHA_B, RUN_URL="https://github.com/o/r/actions/runs/20")
        [mail] = self.relay()
        self.assertIn("복구", mail["subject"])

    def test_green_or_queue_without_red_opens_nothing(self) -> None:
        self.notify("result", KIND="queue", RESULT="skipped", SHA=SHA_A)
        self.notify("result", KIND="hotfix", RESULT="success", SHA=SHA_A)
        self.assertFalse((self.d / "issues.json").exists() and self.issues())

    def test_cancel_without_failed_job_is_quiet(self) -> None:
        self.notify("result", KIND="hotfix", RESULT="cancelled", SHA=SHA_A, RUN_ID="5", FAKE_FAILED_JOBS="")
        self.assertEqual(self.relay(), [])

    def test_unmarked_direct_push_mails_each_commit(self) -> None:
        self.notify("direct", SHA=SHA_A, UNMARKED=SHA_A[:12], RUN_URL="https://github.com/o/r/actions/runs/30")
        [mail] = self.relay()
        self.assertIn("표식 없는 main 직접 push", mail["subject"])
        self.assertIn(SHA_A[:12], mail["body"])
        self.notify("direct", SHA=SHA_B, UNMARKED=SHA_B[:12], RUN_URL="https://github.com/o/r/actions/runs/31")
        [mail] = self.relay()
        self.assertIn(SHA_B[:12], mail["body"])

    def test_mail_failure_is_retried_next_run(self) -> None:
        self.fail(SHA_A, 11)
        (self.d / "bin" / "switchboard-fail").touch()
        self.assertEqual(self.relay(want=3), [])
        (self.d / "bin" / "switchboard-fail").unlink()
        self.assertEqual(len(self.relay()), 1)

    def test_old_closed_issues_are_not_mailed_on_first_run(self) -> None:
        self.fail(SHA_A, 11)
        self.notify("result", KIND="hotfix", RESULT="success", SHA=SHA_B)
        self.assertEqual(self.relay(), [])

    def test_other_ci_red_kinds_are_not_relayed(self) -> None:
        subprocess.run(["bash", str(HERE / "ci" / "ci-issue.sh"), "fail", "release 이미지 실패 — production 승격·배포 멈춤", "x"],
                       env=self.env, check=True, capture_output=True)
        self.assertEqual(self.relay(), [])

    def test_missing_or_broken_state_does_not_flood(self) -> None:
        """기록이 사라지거나 깨져도 열린 이슈를 한꺼번에 다시 보내지 않는다 — 기록만 다시 만들고 3 으로 한 번 드러낸다."""
        self.fail(SHA_A, 11)
        self.notify("direct", SHA=SHA_B, UNMARKED=SHA_B[:12])
        self.assertEqual(len(self.relay()), 2)
        for broken in (None, "{깨짐"):
            state = self.d / "relay.json"
            if broken is None:
                state.unlink()
            else:
                state.write_text(broken)
            self.assertEqual(self.relay(want=3), [])
            self.assertEqual(self.relay(), [])
        self.notify("result", KIND="hotfix", RESULT="success", SHA=SHA_C)  # 다시 만든 기록으로도 복구는 간다
        [mail] = self.relay()
        self.assertIn("복구", mail["subject"])

    def test_gh_failure_is_exit_two(self) -> None:
        def broken(args: Sequence[str]) -> str:
            raise RuntimeError("gh 실패")

        self.assertEqual(ci_red_relay.relay(self.d / "s.json", gh=broken, send=lambda s, b: True), 2)


# ── hotfix.py ───────────────────────────────────────────────────────────────────────────
class HotfixPushTest(unittest.TestCase):
    """맨 원격 하나 + 클론 둘(w: 핫픽스 워크트리, o: main 을 앞으로 미는 남)."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = self.t = Path(tmp.name)
        self.origin = t / "origin.git"
        git(t, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.o = t / "o"
        git(t, "clone", "-q", str(self.origin), str(self.o))
        commit(self.o, "app.py", "a\nb\nc\n")
        git(self.o, "push", "-q", "origin", "HEAD:main")
        self.w = t / "w"
        git(t, "clone", "-q", str(self.origin), str(self.w))

    def main_log(self, fmt: str = "%s") -> list[str]:
        return git(self.origin, "log", f"--format={fmt}", "main").splitlines()

    def test_marks_and_pushes_one_commit(self) -> None:
        commit(self.w, "app.py", "a\nB\nc\n", "장애 고침")
        sha = hotfix.push(1316, cwd=self.w)
        self.assertEqual(git(self.origin, "rev-parse", "main"), sha)
        self.assertIn("Hotfix: #1316", git(self.origin, "log", "-1", "--format=%B", "main"))
        self.assertTrue(hotfix.marked("main", self.origin))

    def test_catches_up_when_main_moved(self) -> None:
        commit(self.w, "app.py", "a\nB\nc\n", "장애 고침")
        commit(self.o, "other.py", "x", "남의 병합 (#2)")
        git(self.o, "push", "-q", "origin", "HEAD:main")
        hotfix.push(1316, cwd=self.w)
        self.assertEqual(self.main_log()[:2], ["장애 고침", "남의 병합 (#2)"])

    def test_dry_run_does_not_push(self) -> None:
        before = git(self.origin, "rev-parse", "main")
        commit(self.w, "app.py", "a\nB\nc\n", "장애 고침")
        hotfix.push(1316, cwd=self.w, dry=True)
        self.assertEqual(git(self.origin, "rev-parse", "main"), before)

    def test_already_marked_needs_no_issue(self) -> None:
        commit(self.w, "app.py", "a\nB\nc\n", "장애 고침\n\nHotfix: #9")
        hotfix.push(None, cwd=self.w)
        self.assertEqual(git(self.origin, "log", "-1", "--format=%B", "main").count("Hotfix:"), 1)

    def test_refusals(self) -> None:
        with self.assertRaisesRegex(hotfix.Refused, "올릴 커밋이 없다"):
            hotfix.push(1, cwd=self.w)
        commit(self.w, "app.py", "1", "하나")
        with self.assertRaisesRegex(hotfix.Refused, "--issue"):
            hotfix.push(None, cwd=self.w)
        commit(self.w, "app.py", "2", "둘")
        with self.assertRaisesRegex(hotfix.Refused, "커밋이 2개"):
            hotfix.push(1, cwd=self.w)
        git(self.w, "reset", "-q", "--soft", "HEAD~1")
        with self.assertRaisesRegex(hotfix.Refused, "커밋하지 않은 변경"):
            hotfix.push(1, cwd=self.w)

    def test_conflict_is_undone_and_refused(self) -> None:
        commit(self.w, "app.py", "a\nB\nc\n", "장애 고침")
        commit(self.o, "app.py", "a\nX\nc\n", "남이 같은 줄")
        git(self.o, "push", "-q", "origin", "HEAD:main")
        with self.assertRaisesRegex(hotfix.Refused, "충돌"):
            hotfix.push(1, cwd=self.w)
        self.assertFalse((self.w / ".git" / "rebase-merge").exists())
        self.assertEqual(git(self.w, "status", "--porcelain"), "")

    def test_ruleset_rejection_points_at_owner_step(self) -> None:
        hook = self.origin / "hooks" / "pre-receive"
        _exe(hook, "#!/bin/sh\necho 'error: GH013: Repository rule violations found for refs/heads/main.' >&2\nexit 1\n")
        commit(self.w, "app.py", "a\nB\nc\n", "장애 고침")
        with self.assertRaisesRegex(hotfix.Refused, "대표 몫"):
            hotfix.push(1, cwd=self.w)

    def test_show_lists_release_check_and_deploy(self) -> None:
        runs = json.dumps([
            {"workflowName": "release", "status": "in_progress", "conclusion": "", "url": "u1"},
            {"workflowName": "main 뒤따른 검사", "status": "queued", "conclusion": "", "url": "u2"},
            {"workflowName": "e2e", "status": "queued", "conclusion": "", "url": "u3"},
        ])
        gh = fake_gh({"run list": runs, "/status": "pending https://ci/deploy/7"})
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hotfix.show(SHA_A, "o/r", gh, wait=0)
        out = buf.getvalue()
        self.assertIn("release: in_progress u1", out)
        self.assertIn("main 뒤따른 검사: queued u2", out)
        self.assertNotIn("u3", out)
        self.assertIn("pending https://ci/deploy/7", out)


if __name__ == "__main__":
    unittest.main()
