#!/usr/bin/env python3
"""`dev-server.sh` 의 메모리 여유 검사를 가짜 cgroup 디렉터리로 고정한다(#976).

실제 서버를 띄우지 않는다 — `check` 하위 명령은 띄우지 않고 검사만 한다.
`python3 scripts/test_dev_server.py` 하나로 돈다.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "dev-server.sh"
MB = 1048576


class Fake:
    """`/sys/fs/cgroup` 흉내 — user.slice(한도 소유) 아래 세션 scope 에 이 프로세스가 있다."""

    def __init__(
        self, root: Path, high: str, current_mb: int, scope_high: str = "max", stat_mb: dict[str, int] | None = None
    ) -> None:
        slice_dir = root / "user.slice" / "user-1.slice"
        scope = slice_dir / "session-1.scope"
        scope.mkdir(parents=True)
        (slice_dir / "memory.high").write_text(high + "\n")
        (slice_dir / "memory.max").write_text("max\n")
        (slice_dir / "memory.current").write_text(f"{current_mb * MB}\n")
        if stat_mb is not None:
            (slice_dir / "memory.stat").write_text("".join(f"{k} {v * MB}\n" for k, v in stat_mb.items()))
        (scope / "memory.high").write_text(scope_high + "\n")
        (scope / "memory.max").write_text("max\n")
        (scope / "memory.current").write_text(f"{(current_mb // 10) * MB}\n")
        self.proc = root / "proc_cgroup"
        self.proc.write_text("0::/user.slice/user-1.slice/session-1.scope\n")
        self.root = root


def run(args: list[str], root: Path, proc: Path, run_dir: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full = {
        **os.environ,
        "CODEMIT_CGROUP_ROOT": str(root),
        "CODEMIT_PROC_CGROUP": str(proc),
        "CODEMIT_DEV_SERVER_DIR": str(run_dir),
        # `start` 는 포트를 고르려고 dev-env.sh 를 부른다 — 칸 예약(#1411)이 임시 폴더에 남게 한다.
        "XDG_STATE_HOME": str(run_dir / "xdg"),
        **env,
    }
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=full, timeout=60)


class MemoryGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def test_refuses_when_no_room(self) -> None:
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=12 * 1024)  # 12GB + 2GB > 85%
        r = run(["check", "classroom"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("메모리 묶음에 여유가 없다", r.stderr)
        self.assertIn("내릴 것", r.stderr)
        self.assertIn("stop-all", r.stderr)

    def test_inactive_file_cache_is_not_counted(self) -> None:
        # current 13GB 중 inactive_file 6GB — 쓰는 양 7GB 라 통과한다(#1230).
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=13 * 1024,
                 stat_mb={"anon": 5000, "shmem": 500, "active_file": 1000, "inactive_file": 6 * 1024})
        r = run(["check", "classroom"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_refuses_when_anon_is_big_and_prints_breakdown(self) -> None:
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=13 * 1024,
                 stat_mb={"anon": 11 * 1024, "shmem": 2600, "active_file": 700, "inactive_file": 500})
        r = run(["check", "classroom"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 1, r.stderr)
        for word in ("anon 11264MB", "shmem 2600MB", "active_file 700MB", "inactive_file 500MB", "tmpfs"):
            self.assertIn(word, r.stderr)

    def test_walks_up_to_the_ancestor_that_has_a_limit(self) -> None:
        # scope 는 한도가 max 지만 조상 slice 에 숫자가 있다 — 그쪽 current 로 판정한다.
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=1024)
        r = run(["check", "classroom"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("여유 있음", r.stdout)

    def test_backend_is_small_enough_to_fit_where_next_does_not(self) -> None:
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=int(11.5 * 1024))
        self.assertEqual(run(["check", "classroom"], f.root, f.proc, self.run_dir).returncode, 1)
        self.assertEqual(run(["check", "backend"], f.root, f.proc, self.run_dir).returncode, 0)

    def test_limit_max_everywhere_passes_with_a_note(self) -> None:
        f = Fake(self.tmp / "cg", high="max", current_mb=50 * 1024)
        r = run(["check", "classroom"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("검사 없음", r.stderr)

    def test_no_cgroup_files_passes_with_a_note(self) -> None:
        r = run(["check", "front"], self.tmp / "nope", self.tmp / "nope.proc", self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("검사 없음", r.stderr)

    def test_force_skips_the_gate(self) -> None:
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=13 * 1024)
        r = run(["check", "classroom"], f.root, f.proc, self.run_dir, CODEMIT_DEV_SERVER_FORCE="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("쓰지 말 것", r.stderr)

    def test_refusal_lists_recorded_servers_with_rss(self) -> None:
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=13 * 1024)
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        (self.run_dir / "wt-1.classroom.pid").write_text(f"{sleeper.pid}\n")
        (self.run_dir / "wt-1.classroom.port").write_text("53112\n")
        (self.run_dir / "wt-1.worktree").write_text("/somewhere/wt\n")
        r = run(["check", "front"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("/somewhere/wt", r.stderr)
        self.assertIn("RSS=", r.stderr)

    def test_start_refuses_before_spawning_anything(self) -> None:
        f = Fake(self.tmp / "cg", high=str(14 * 1024 * MB), current_mb=13 * 1024)
        r = run(["start", "classroom"], f.root, f.proc, self.run_dir)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(list(self.run_dir.glob("*.pid")), [])


if __name__ == "__main__":
    unittest.main()
