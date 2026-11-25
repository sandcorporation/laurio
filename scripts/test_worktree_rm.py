#!/usr/bin/env python3
"""`scripts/worktree-rm.sh` 와 `dev-env.sh` 의 고아 dev 스택 걷기를 고정한다(#1275).

`python3 scripts/test_worktree_rm.py` 하나로 돈다. 가짜 docker 를 PATH 앞에 둔다 — 실제 컨테이너를 건드리지 않는다.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

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


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        d = bin_dir / "docker"
        d.write_text(FAKE_DOCKER)
        d.chmod(d.stat().st_mode | stat.S_IEXEC)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE": str(self.fake),
            "CODEMIT_DEV_SERVER_DIR": str(self.tmp / "state"),
            # dev-env.sh 의 칸 예약(#1411)이 이 머신의 실제 예약에 닿지 않게 한다.
            "HOME": str(self.tmp / "home"),
            "XDG_STATE_HOME": str(self.tmp / "xdg"),
            "TMPDIR": str(self.tmp),
        }
        self.env.pop("CODEMIT_DEV_OFFSET", None)
        # 묵은 main 체크아웃 — 스크립트도 헬퍼도 없는 저장소(주 워크트리).
        self.main = self.tmp / "main"
        self.main.mkdir()
        git("init", "-q", "-b", "main", cwd=self.main)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "old", cwd=self.main)

    def stacks(self, *lines: str) -> None:
        (self.fake / "projects").write_text("\n".join(lines) + "\n")

    def downs(self) -> list[str]:
        log = self.fake / "log"
        return log.read_text().splitlines() if log.exists() else []

    def copy_tree(self, root: Path) -> None:
        helpers = [f"docker/{p.name}" for p in (REPO / "docker").glob("dev-*.sh")]
        for rel in ("scripts/worktree-rm.sh", "scripts/dev-server.sh", *helpers):
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text((REPO / rel).read_text())
            dst.chmod(0o755)


class WorktreeRm(Base):
    def make_worktree(self, name: str) -> Path:
        wt = self.tmp / "wt" / name
        git("worktree", "add", "-q", "-b", name, str(wt), cwd=self.main)
        self.copy_tree(wt)  # 지울 워크트리가 스크립트의 사본을 들고 있다. main 에는 없다.
        return wt

    def test_run_from_inside_the_worktree_copy(self) -> None:
        wt = self.make_worktree("t1")
        other = self.make_worktree("t2")
        self.stacks(f"codemit-dev-6|{wt}/docker|1 hour ago", f"codemit-dev-6-e2e|{wt}/docker|1 hour ago", f"codemit-dev-7|{other}/docker|1 hour ago")
        r = subprocess.run(["bash", str(wt / "scripts" / "worktree-rm.sh"), str(wt), "t1"], cwd=wt, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertTrue(other.exists())  # 남의 워크트리는 그대로
        branches = subprocess.run(["git", "branch", "--list", "t1"], cwd=self.main, capture_output=True, text=True).stdout
        self.assertEqual(branches.strip(), "")
        downs = self.downs()
        self.assertIn("compose -p codemit-dev-6-e2e down -v --remove-orphans", downs)
        self.assertIn("compose -p codemit-dev-6 down --remove-orphans", downs)
        self.assertFalse(any("codemit-dev-7" in d for d in downs))
        self.assertEqual(list((self.tmp).glob("worktree-rm.*")), [])  # 임시 사본은 치운다

    def test_releases_only_the_slot_reservations_of_that_worktree(self) -> None:
        wt = self.make_worktree("t1")
        other = self.make_worktree("t2")
        self.stacks()
        slots = self.tmp / "xdg" / "codemit" / "dev-slots"
        slots.mkdir(parents=True)
        (slots / "3").write_text(f"{wt}\n")
        (slots / "4").write_text(f"{other}\n")
        r = subprocess.run(["bash", str(wt / "scripts" / "worktree-rm.sh"), str(wt), "t1"], cwd=wt, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((slots / "3").exists())
        self.assertEqual((slots / "4").read_text(), f"{other}\n")

    def test_refuses_the_main_worktree(self) -> None:
        wt = self.make_worktree("t1")
        r = subprocess.run(["bash", str(wt / "scripts" / "worktree-rm.sh"), str(self.main)], cwd=wt, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.main.exists())


class DevEnvReapsOrphans(Base):
    def run_env(self, root: Path, offset: str | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if offset is not None:
            env["CODEMIT_DEV_OFFSET"] = offset
        return subprocess.run(["sh", str(root / "docker" / "dev-env.sh")], cwd=root, capture_output=True, text=True, env=env, timeout=60)

    def test_orphan_dev_stack_is_downed_on_start_even_on_the_hash_path(self) -> None:
        wt = self.tmp / "wt" / "t1"
        git("worktree", "add", "-q", "-b", "t1", str(wt), cwd=self.main)
        self.copy_tree(wt)
        gone = self.tmp / "wt" / "gone"  # 디렉터리가 없다 → 고아
        alive = self.tmp / "wt" / "alive"
        (alive / "docker").mkdir(parents=True)
        self.stacks(f"codemit-dev-2|{gone}/docker|9 hours ago", f"codemit-dev-3|{alive}/docker|9 hours ago", f"codemit-dev-4-e2e|{gone}/docker|9 hours ago")
        r = self.run_env(wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COMPOSE_PROJECT_NAME=codemit-dev", r.stdout)
        self.assertEqual(self.downs(), ["compose -p codemit-dev-2 down --remove-orphans"])  # 주인 있는 스택·-e2e 는 그대로
        self.assertIn("codemit-dev-2", r.stderr)
        self.assertNotIn("내렸다", r.stdout)  # stdout 은 eval 이 실행한다 — 알림이 섞이면 안 된다

    def test_explicit_offset_path_still_reuses_the_orphaned_offset(self) -> None:
        gone = self.tmp / "wt" / "gone"
        self.copy_tree(self.main)
        self.stacks(f"codemit-dev-2|{gone}/docker|9 hours ago")
        r = self.run_env(self.main, "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COMPOSE_PROJECT_NAME=codemit-dev-2\n", r.stdout)


if __name__ == "__main__":
    unittest.main()
