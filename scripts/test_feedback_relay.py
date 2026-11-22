#!/usr/bin/env python3
"""`scripts/feedback.sh`(제보 → 대장 메일함, #1240)를 고정한다.

`python3 scripts/test_feedback_relay.py` 하나로 돈다. 가짜 ssh·switchboard 를 쓴다 — 운영에 닿지 않는다.
가짜 ssh 는 운영 backend 의 `manage.py feedback_report` 를 JSON 파일 하나로 흉내 낸다(집음·전달 표시).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "feedback.sh"

FAKE_SSH = r'''#!/usr/bin/env python3
import json, os, re, sys
fake = os.environ["FAKE"]
args = sys.argv[1:]
while args and args[0] == "-o":
    args = args[2:]
host, command = args[0], " ".join(args[1:])
with open(os.path.join(fake, "ssh.log"), "a") as log:
    log.write(json.dumps({"host": host, "command": command}, ensure_ascii=False) + "\n")
rcfile = os.path.join(fake, "ssh-rc")
if os.path.exists(rcfile):
    sys.exit(int(open(rcfile).read()))  # 배포 중 컨테이너 교체: 말없이 시그널 코드로 죽는다
if os.path.exists(os.path.join(fake, "ssh-down")):
    print("ssh: connect to host oracle: Connection timed out", file=sys.stderr)
    sys.exit(255)
assert "label=com.docker.compose.service=backend" in command, command
sub = command.split("manage.py feedback_report ", 1)[1].split()
path = os.path.join(fake, "db.json")
db = json.load(open(path))
rows = {r["id"]: r for r in db}
def out(r):
    print(json.dumps({k: r[k] for k in ("id", "kind", "app", "received_at")}, ensure_ascii=False))
action = sub[0]
if action in ("list", "take"):
    limit = int(sub[sub.index("--limit") + 1]) if "--limit" in sub else 20
    pending = [r for r in db if not r["forwarded"] and not r["taken"]][:limit]
    for r in pending:
        out(r)
        if action == "take":
            r["taken"] = True
elif action == "summary":
    out(rows[int(sub[1])])
elif action == "untake":
    r = rows[int(sub[1])]
    if r["forwarded"]:
        sys.exit(1)
    r["taken"] = False
elif action == "mark-forwarded":
    r = rows[int(sub[1])]
    if r["forwarded"]:
        print("표시할 제보가 없습니다", file=sys.stderr)
        sys.exit(1)
    r["forwarded"] = True
elif action == "show":
    print(f"제보 #{sub[1]}")
elif action == "status":
    rows[int(sub[1])]["status"] = sub[2]
    rows[int(sub[1])]["note"] = sys.stdin.read() if sub[3:] == ["--note", "-"] else ""
json.dump(db, open(path, "w"), ensure_ascii=False)
'''

FAKE_SWITCHBOARD = r'''#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
with open(os.path.join(fake, "switchboard.log"), "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "profile": os.environ.get("SWITCHBOARD_PROFILE")}, ensure_ascii=False) + "\n")
mode = open(os.path.join(fake, "switchboard-mode")).read().strip() if os.path.exists(os.path.join(fake, "switchboard-mode")) else "ok"
if mode == "fail":
    print("error: mailbox unreachable", file=sys.stderr)
    sys.exit(1)
if mode == "noid":
    print("queued")
    sys.exit(0)
print("#4400 " + sys.argv[sys.argv.index("--subject") + 1])
print("codemit/coordinator → sandcorp/boss · pending")
'''


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class FeedbackRelay(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fake = Path(tmp.name)
        _write_exec(self.fake / "ssh", FAKE_SSH)
        _write_exec(self.fake / "switchboard", FAKE_SWITCHBOARD)
        self.reports(
            {"id": 5, "kind": "bug", "app": "contest", "received_at": "2026-11-21T10:00:00+09:00",
             "body": "다른 학생 이름이 보이는 화면"},
            {"id": 6, "kind": "suggestion", "app": "classroom", "received_at": "2026-11-21T10:05:00+09:00",
             "body": "건의 내용"},
        )

    def reports(self, *rows: dict) -> None:
        db = [{**row, "taken": False, "forwarded": False, "status": "received", "note": ""} for row in rows]
        (self.fake / "db.json").write_text(json.dumps(db, ensure_ascii=False))

    def db(self) -> dict[int, dict]:
        return {r["id"]: r for r in json.loads((self.fake / "db.json").read_text())}

    def run_script(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "FAKE": str(self.fake),
            "CODEMIT_FEEDBACK_SSH": str(self.fake / "ssh"),
            "CODEMIT_SWITCHBOARD": str(self.fake / "switchboard"),
        }
        env.pop("SWITCHBOARD_PROFILE", None)
        return subprocess.run(
            ["bash", str(SCRIPT), *args], env=env, input=stdin, capture_output=True, text=True, timeout=30
        )

    def mails(self) -> list[dict]:
        log = self.fake / "switchboard.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def ssh_calls(self) -> list[dict]:
        log = self.fake / "ssh.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    # --- check ---------------------------------------------------------------

    def test_check_is_zero_only_when_something_waits(self) -> None:
        self.assertEqual(self.run_script("check").returncode, 0)
        self.reports()
        self.assertEqual(self.run_script("check").returncode, 1)

    def test_check_is_two_when_production_is_unreachable(self) -> None:
        (self.fake / "ssh-down").touch()
        self.assertEqual(self.run_script("check").returncode, 2)

    def test_check_keeps_remote_exit_code_and_reason_on_stderr(self) -> None:
        for rc, reason in ((143, "시그널(15)"), (137, "시그널(9)"), (255, "ssh"), (3, "컨테이너가 없다"), (1, "운영 명령")):
            (self.fake / "ssh-rc").write_text(str(rc))
            result = self.run_script("check")
            self.assertEqual(result.returncode, 2)  # precheck 꼴(0·1·2)은 그대로
            self.assertIn(f"원격 실패 rc={rc}", result.stderr)
            self.assertIn(reason, result.stderr)
        self.assertEqual(len(self.ssh_calls()), 5)  # check 마다 ssh 한 번 — 다시 시도하지 않는다

    def test_reads_go_through_oracle_backend_found_by_label(self) -> None:
        self.run_script("list")
        call = self.ssh_calls()[0]
        self.assertEqual(call["host"], "oracle")
        self.assertIn("label=com.docker.compose.project=codemit-prod", call["command"])
        self.assertIn("python manage.py feedback_report list", call["command"])

    # --- forward -------------------------------------------------------------

    def test_forward_sends_only_number_kind_app_time_and_marks(self) -> None:
        taken = self.run_script("take")
        self.assertEqual([json.loads(line)["id"] for line in taken.stdout.splitlines()], [5, 6])

        result = self.run_script("forward", "5")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.db()[5]["forwarded"])
        mail = self.mails()[0]
        argv = mail["argv"]
        self.assertEqual(mail["profile"], "codemit-coordinator")
        self.assertEqual(argv[argv.index("--to") + 1], "sandcorp/boss")
        self.assertEqual(argv[argv.index("--task") + 1], "codemit-feedback")
        self.assertEqual(argv[argv.index("--subject") + 1], "[제보] codemit #5 버그 · 공모전")
        body = argv[argv.index("--body") + 1]
        self.assertIn("2026-11-21T10:00:00+09:00", body)
        self.assertIn("scripts/feedback.sh show 5", body)
        self.assertNotIn("다른 학생", body)

    def test_forward_failure_puts_report_back(self) -> None:
        for mode in ("fail", "noid"):
            with self.subTest(mode=mode):
                (self.fake / "switchboard-mode").write_text(mode)
                self.run_script("take")
                result = self.run_script("forward", "5")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.db()[5]["forwarded"])
                self.assertFalse(self.db()[5]["taken"])
                self.assertEqual(self.run_script("check").returncode, 0)

    def test_forwarded_report_is_not_sent_twice(self) -> None:
        self.run_script("take")
        self.run_script("forward", "5")
        self.run_script("forward", "6")

        self.assertEqual(self.run_script("check").returncode, 1)
        self.assertEqual(self.run_script("take").stdout, "")
        again = self.run_script("forward", "5")
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual(len(self.mails()), 3)
        self.assertTrue(self.db()[5]["forwarded"])

    def test_mark_skips_without_mail(self) -> None:
        self.assertEqual(self.run_script("mark", "5", "6").returncode, 0)
        self.assertEqual(self.mails(), [])
        self.assertEqual(self.run_script("check").returncode, 1)

    # --- status·입력 -----------------------------------------------------------

    def test_status_passes_note_on_stdin(self) -> None:
        note = '반영했다 — "따옴표"; $(rm -rf /) 포함'
        result = self.run_script("status", "5", "deployed", note)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db()[5]["status"], "deployed")
        self.assertEqual(self.db()[5]["note"], note)
        self.assertNotIn("rm -rf", self.ssh_calls()[0]["command"])

    def test_bad_input_never_reaches_production(self) -> None:
        for args in (("forward", "5; reboot"), ("status", "5", "done"), ("show",), ("untake", "x"), ("take", "1;x")):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)
        self.assertEqual(self.ssh_calls(), [])


if __name__ == "__main__":
    unittest.main()
