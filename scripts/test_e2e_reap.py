#!/usr/bin/env python3
"""`docker/dev-stack-orphans.sh` 의 e2e 고아 걷기와 워크트리 소유 스택 내리기를 고정한다(#1192).

`python3 scripts/test_e2e_reap.py` 하나로 돈다. 가짜 docker 를 PATH 앞에 둔다 — 실제 컨테이너를 건드리지 않는다.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "docker" / "dev-stack-orphans.sh"

# projects 파일의 줄: `<프로젝트>|<working_dir>|<RunningFor>`. compose down 은 log 에 한 줄로 남는다.
FAKE_DOCKER = r"""#!/bin/sh
case "$*" in
  *"--format {{.Label \"com.docker.compose.project\"}}"*) cut -d'|' -f1 "$FAKE/projects"; exit 0 ;;
esac
if [ "$1" = ps ]; then
  proj=$(echo "$*" | sed -n 's/.*project=\([^ ]*\).*/\1/p')
  case "$*" in
    *working_dir*) grep "^$proj|" "$FAKE/projects" | cut -d'|' -f2 ;;
    *RunningFor*)  grep "^$proj|" "$FAKE/projects" | cut -d'|' -f3 ;;
  esac
  exit 0
fi
if [ "$1" = compose ]; then echo "$*" >> "$FAKE/log"; fi
exit 0
"""


class E2eReap(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        self.state = self.tmp / "state"
        self.state.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        d = bin_dir / "docker"
        d.write_text(FAKE_DOCKER)
        d.chmod(d.stat().st_mode | stat.S_IEXEC)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE": str(self.fake),
            "CODEMIT_DEV_SERVER_DIR": str(self.state),
        }
        self.procs: list[subprocess.Popen[bytes]] = []
        self.addCleanup(lambda: [p.kill() for p in self.procs])

    def stacks(self, *lines: str) -> None:
        (self.fake / "projects").write_text("\n".join(lines) + "\n")

    def sh(self, body: str) -> str:
        r = subprocess.run(["sh", "-c", f". {LIB}; {body}"], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def downs(self) -> list[str]:
        log = self.fake / "log"
        return log.read_text().splitlines() if log.exists() else []

    def test_dead_owner_is_reaped_with_volumes(self) -> None:
        self.stacks("codemit-dev-6-e2e|/wt/t1|2 minutes ago")
        (self.state / "codemit-dev-6-e2e.owner").write_text("999999\n")
        out = self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED")
        self.assertIn("reaped=1", out)
        self.assertEqual(self.downs(), ["compose -p codemit-dev-6-e2e down -v --remove-orphans"])
        self.assertFalse((self.state / "codemit-dev-6-e2e.owner").exists())

    def test_live_test_sh_is_left_alone(self) -> None:
        fake_test_sh = self.tmp / "test.sh"
        fake_test_sh.write_text("sleep 30\n")
        p = subprocess.Popen(["sh", str(fake_test_sh)])
        self.procs.append(p)  # type: ignore[arg-type]
        time.sleep(0.2)
        self.stacks("codemit-dev-6-e2e|/wt/t1|3 hours ago")
        (self.state / "codemit-dev-6-e2e.owner").write_text(f"{p.pid}\n")
        self.assertIn("reaped=0", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))
        self.assertEqual(self.downs(), [])

    def test_pid_reused_by_other_program_is_dead(self) -> None:
        p = subprocess.Popen(["sleep", "30"])
        self.procs.append(p)  # type: ignore[arg-type]
        self.stacks("codemit-dev-6-e2e|/wt/t1|3 hours ago")
        (self.state / "codemit-dev-6-e2e.owner").write_text(f"{p.pid}\n")
        self.assertIn("reaped=1", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))

    def test_keep_survives_until_the_age_cap(self) -> None:
        self.stacks("codemit-dev-6-e2e|/wt/t1|5 hours ago")
        (self.state / "codemit-dev-6-e2e.owner").write_text("999999\n")
        (self.state / "codemit-dev-6-e2e.keep").write_text(f"{int(time.time()) - 60}\n")
        self.assertIn("reaped=0", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))
        (self.state / "codemit-dev-6-e2e.keep").write_text(f"{int(time.time()) - 13 * 3600}\n")
        self.assertIn("reaped=1", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))

    def test_unmarked_stack_waits_an_hour(self) -> None:
        self.stacks("codemit-dev-6-e2e|/wt/t1|20 minutes ago")
        self.assertIn("reaped=0", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))
        self.stacks("codemit-dev-6-e2e|/wt/t1|3 hours ago")
        self.assertIn("reaped=1", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))

    def test_non_e2e_and_other_names_are_not_touched(self) -> None:
        self.stacks("codemit-dev-6|/wt/t1|3 hours ago", "other-e2e|/wt/x|3 hours ago")
        self.assertIn("reaped=0", self.sh("e2e_stack_reap; echo reaped=$E2E_REAPED"))
        self.assertEqual(self.downs(), [])

    def test_down_owned_by_worktree(self) -> None:
        wt = self.tmp / "wt" / "t1"
        wt.mkdir(parents=True)
        other = self.tmp / "wt" / "t2"
        other.mkdir()
        self.stacks(f"codemit-dev-6|{wt}/docker|1 hour ago", f"codemit-dev-6-e2e|{wt}/docker|1 hour ago", f"codemit-dev-7|{other}/docker|1 hour ago")
        self.sh(f"dev_stack_down_owned_by {wt}")
        downs = self.downs()
        self.assertIn("compose -p codemit-dev-6-e2e down -v --remove-orphans", downs)  # e2e 는 볼륨까지
        self.assertIn("compose -p codemit-dev-6 down --remove-orphans", downs)  # dev 는 볼륨을 남긴다
        self.assertFalse(any("codemit-dev-7" in d for d in downs))  # 남의 스택은 그대로


if __name__ == "__main__":
    unittest.main()
