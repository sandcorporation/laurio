#!/usr/bin/env python3
"""`scripts/automation-run.sh`(Orca 자동화 진입, #1252)를 고정한다.

`python3 scripts/test_automation_run.py` 하나로 돈다. 진짜 git(임시 origin·체크아웃)과 가짜 switchboard 를 쓴다 —
운영·실제 메일함에 닿지 않는다. 본 명령은 종료 코드만 흉내 내는 작은 스크립트다.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "automation-run.sh"

FAKE_SWITCHBOARD = r'''#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
with open(os.path.join(fake, "switchboard.log"), "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "profile": os.environ.get("SWITCHBOARD_PROFILE")}, ensure_ascii=False) + "\n")
if os.path.exists(os.path.join(fake, "switchboard-down")):
    print("error: mailbox unreachable", file=sys.stderr)
    sys.exit(1)
print("#4400 " + sys.argv[sys.argv.index("--subject") + 1])
print("codemit/coordinator → sandcorp/boss · pending")
'''

# 본 명령: 종료 코드는 파일 `rc`(없으면 0). 돈 자리의 HEAD 를 `ran.log` 에 남긴다.
COMMAND = r'''#!/usr/bin/env bash
git rev-parse HEAD >> "$FAKE/ran.log"
echo "표준오류 한 줄" >&2
exit "$(cat "$FAKE/rc" 2>/dev/null || echo 0)"
'''


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class AutomationRun(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.fake = root / "fake"
        self.fake.mkdir()
        _write_exec(self.fake / "switchboard", FAKE_SWITCHBOARD)
        _write_exec(self.fake / "cmd.sh", COMMAND)
        self.origin = root / "origin.git"
        self.checkout = root / "checkout"
        self.pusher = root / "pusher"
        _git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        _git(root, "clone", "-q", str(self.origin), str(self.checkout))
        _git(self.checkout, "checkout", "-q", "-b", "main")
        (self.checkout / "a.txt").write_text("1")
        _git(self.checkout, "add", "a.txt")
        _git(self.checkout, "commit", "-q", "-m", "첫 커밋")
        _git(self.checkout, "push", "-q", "origin", "main")
        _git(root, "clone", "-q", str(self.origin), str(self.pusher))
        self.state = root / "state"

    def push_new_commit(self, name: str = "b.txt") -> str:
        (self.pusher / name).write_text("x")
        _git(self.pusher, "add", name)
        _git(self.pusher, "commit", "-q", "-m", f"원격 커밋 {name}")
        _git(self.pusher, "push", "-q", "origin", "main")
        return _git(self.pusher, "rev-parse", "HEAD")

    def run_script(self, *extra: str, repeat_secs: int = 3600) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "FAKE": str(self.fake),
            "CODEMIT_AUTOMATION_REPO": str(self.checkout),
            "CODEMIT_AUTOMATION_STATE_DIR": str(self.state),
            "CODEMIT_AUTOMATION_REPEAT_SECS": str(repeat_secs),
            "CODEMIT_SWITCHBOARD": str(self.fake / "switchboard"),
        }
        env.pop("SWITCHBOARD_PROFILE", None)
        return subprocess.run(
            ["bash", str(SCRIPT), "feedback-relay", *extra, "--", str(self.fake / "cmd.sh")],
            env=env, capture_output=True, text=True, timeout=30,
        )

    def set_rc(self, rc: int) -> None:
        (self.fake / "rc").write_text(str(rc))

    def mails(self) -> list[dict]:
        log = self.fake / "switchboard.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def subject(self, mail: dict) -> str:
        argv = mail["argv"]
        return argv[argv.index("--subject") + 1]

    def ran(self) -> list[str]:
        log = self.fake / "ran.log"
        return log.read_text().split() if log.exists() else []

    # --- 따라잡기 ---------------------------------------------------------------

    def test_stale_checkout_is_caught_up_before_running(self) -> None:
        new = self.push_new_commit()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [new])
        self.assertEqual(_git(self.checkout, "rev-parse", "HEAD"), new)
        self.assertEqual(self.mails(), [])

    def test_dirty_checkout_is_not_caught_up_and_one_mail_goes(self) -> None:
        self.push_new_commit()
        before = _git(self.checkout, "rev-parse", "HEAD")
        (self.checkout / "a.txt").write_text("손으로 고침")
        result = self.run_script()
        self.assertEqual(result.returncode, 70)
        self.assertEqual(_git(self.checkout, "rev-parse", "HEAD"), before)
        self.assertEqual((self.checkout / "a.txt").read_text(), "손으로 고침")
        self.assertEqual(self.ran(), [])  # 묵은 코드로 본 명령을 돌리지 않는다
        mails = self.mails()
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["profile"], "codemit-coordinator")
        argv = mails[0]["argv"]
        self.assertEqual(argv[argv.index("--to") + 1], "sandcorp/boss")
        self.assertIn("feedback-relay", self.subject(mails[0]))
        self.assertIn("커밋하지 않은 변경", argv[argv.index("--body") + 1])

    def test_checkout_ahead_of_origin_is_kept_and_reported(self) -> None:
        (self.checkout / "local.txt").write_text("다른 세션의 커밋")
        _git(self.checkout, "add", "local.txt")
        _git(self.checkout, "commit", "-q", "-m", "다른 세션이 main 에 커밋")
        head = _git(self.checkout, "rev-parse", "HEAD")
        result = self.run_script()
        self.assertEqual(result.returncode, 70)
        self.assertEqual(_git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(len(self.mails()), 1)
        self.assertIn("앞서", result.stderr)

    def test_diverged_checkout_is_reported(self) -> None:
        (self.checkout / "local.txt").write_text("로컬")
        _git(self.checkout, "add", "local.txt")
        _git(self.checkout, "commit", "-q", "-m", "로컬 커밋")
        self.push_new_commit()
        self.assertEqual(self.run_script().returncode, 70)
        self.assertEqual(len(self.mails()), 1)
        self.assertIn("갈라졌다", self.mails()[0]["argv"][self.mails()[0]["argv"].index("--body") + 1])

    def test_checkout_off_main_is_reported(self) -> None:
        _git(self.checkout, "checkout", "-q", "-b", "other")
        self.assertEqual(self.run_script().returncode, 70)
        self.assertEqual(len(self.mails()), 1)

    def test_fetch_failure_is_reported(self) -> None:
        _git(self.checkout, "remote", "set-url", "origin", str(self.fake / "없는 저장소"))
        self.assertEqual(self.run_script().returncode, 70)
        self.assertEqual(len(self.mails()), 1)

    def test_sync_failure_repeats_only_after_the_interval_and_recovers_with_one_mail(self) -> None:
        self.push_new_commit()
        (self.checkout / "a.txt").write_text("더러움")
        self.run_script()
        self.run_script()
        self.assertEqual(len(self.mails()), 1)
        # 간격이 지나면 한 번 더
        self.assertEqual(self.run_script(repeat_secs=0).returncode, 70)
        self.assertEqual(len(self.mails()), 2)
        # 회복
        _git(self.checkout, "checkout", "-q", "--", "a.txt")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(len(self.mails()), 3)
        self.assertIn("회복", self.subject(self.mails()[2]))
        self.run_script()
        self.assertEqual(len(self.mails()), 3)

    # --- 본 명령의 종료 코드 ------------------------------------------------------

    def test_no_report_means_exit_one_and_no_mail(self) -> None:
        self.set_rc(1)
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(self.mails(), [])

    def test_something_waiting_means_exit_zero_and_no_mail(self) -> None:
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.mails(), [])

    def test_unreachable_production_mails_once_then_silent_then_recovery_once(self) -> None:
        self.set_rc(2)
        self.assertEqual(self.run_script().returncode, 2)
        self.assertEqual(self.run_script().returncode, 2)
        self.assertEqual(self.run_script().returncode, 2)
        mails = self.mails()
        self.assertEqual(len(mails), 1)
        argv = mails[0]["argv"]
        self.assertIn("종료 코드 2", self.subject(mails[0]))
        self.assertIn("표준오류 한 줄", argv[argv.index("--body") + 1])

        self.set_rc(1)  # 회복 — 이제 제보 없음
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(len(self.mails()), 2)
        self.assertIn("회복", self.subject(self.mails()[1]))
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(len(self.mails()), 2)

    def test_a_different_code_is_a_new_cause_and_mails_again(self) -> None:
        self.set_rc(2)
        self.run_script()
        self.set_rc(3)
        self.assertEqual(self.run_script().returncode, 3)
        self.assertEqual(len(self.mails()), 2)

    def test_missing_command_127_is_reported(self) -> None:
        env = {**os.environ, "FAKE": str(self.fake), "CODEMIT_AUTOMATION_REPO": str(self.checkout),
               "CODEMIT_AUTOMATION_STATE_DIR": str(self.state),
               "CODEMIT_SWITCHBOARD": str(self.fake / "switchboard")}
        result = subprocess.run(["bash", str(SCRIPT), "x", "--", str(self.fake / "없음.sh")],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(len(self.mails()), 1)

    def test_ok_codes_are_configurable(self) -> None:
        self.set_rc(7)
        self.assertEqual(self.run_script("--ok", "0,7").returncode, 7)
        self.assertEqual(self.mails(), [])

    def test_mail_failure_is_retried_next_run(self) -> None:
        self.set_rc(2)
        (self.fake / "switchboard-down").touch()
        self.assertEqual(self.run_script().returncode, 2)
        (self.fake / "switchboard-down").unlink()
        self.run_script()
        ok_mails = [m for m in self.mails()]
        self.assertEqual(len(ok_mails), 2)  # 첫 시도(실패) + 다음 실행의 재시도
        self.run_script()
        self.assertEqual(len(self.mails()), 2)  # 보냈으니 더 안 보낸다

    def test_bad_arguments_exit_two(self) -> None:
        env = {**os.environ, "CODEMIT_AUTOMATION_REPO": str(self.checkout)}
        for args in ((), ("x",), ("x", "cmd"), ("bad name", "--", "true")):
            with self.subTest(args=args):
                r = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 2)

    def test_state_file_lives_under_state_dir_only(self) -> None:
        self.set_rc(2)
        self.run_script()
        self.assertEqual([p.name for p in self.state.iterdir()], ["feedback-relay.state"])
        cause, ts = (self.state / "feedback-relay.state").read_text().split()
        self.assertEqual(cause, "rc2")
        self.assertLess(abs(int(ts) - time.time()), 60)


if __name__ == "__main__":
    unittest.main()
