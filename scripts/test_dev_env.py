#!/usr/bin/env python3
"""`docker/dev-env.sh` 의 CODEMIT_DEV_OFFSET 지정을 고정한다(#1106).

`python3 scripts/test_dev_env.py` 하나로 돈다. 가짜 docker 를 PATH 앞에 둔다.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "docker" / "dev-env.sh"


class DevOffset(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bin = Path(self._tmp.name) / "bin"
        self.bin.mkdir()
        # CI 의 검사 컨테이너에는 .git 이 없다 — 임시 저장소에 복사해 돌린다(주 워크트리 = 그 저장소).
        self.root = Path(self._tmp.name).resolve() / "repo"
        (self.root / "docker").mkdir(parents=True)
        self.script = self.root / "docker" / "dev-env.sh"
        self.script.write_text(SRC.read_text())
        (self.root / "docker" / "dev-stack-orphans.sh").write_text((SRC.parent / "dev-stack-orphans.sh").read_text())
        # 남의 체크아웃 — 디렉터리가 살아 있어야 「남의 스택」이다(사라졌으면 고아).
        self.other = str(Path(self._tmp.name) / "other" / "docker")
        Path(self.other).mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def fake_docker(self, owner: str) -> None:
        d = self.bin / "docker"
        d.write_text(f"#!/bin/sh\n[ -n '{owner}' ] && echo '{owner}'\nexit 0\n")
        d.chmod(d.stat().st_mode | stat.S_IEXEC)

    def run_env(self, offset: str | None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        env.pop("CODEMIT_DEV_OFFSET", None)
        if offset is not None:
            env["CODEMIT_DEV_OFFSET"] = offset
        return subprocess.run(["sh", str(self.script)], capture_output=True, text=True, env=env, timeout=60)

    def test_explicit_offset(self) -> None:
        self.fake_docker("")
        r = self.run_env("3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COMPOSE_PROJECT_NAME=codemit-dev-3\n", r.stdout)
        self.assertIn("CODEMIT_DB_PORT=55732\n", r.stdout)

    def test_explicit_zero(self) -> None:
        self.fake_docker("")
        r = self.run_env("0")
        self.assertIn("COMPOSE_PROJECT_NAME=codemit-dev\n", r.stdout)
        self.assertIn("CODEMIT_DB_PORT=55432\n", r.stdout)

    def test_unset_keeps_derived(self) -> None:
        self.fake_docker("")
        r = self.run_env(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COMPOSE_PROJECT_NAME=codemit-dev", r.stdout)

    def test_out_of_range(self) -> None:
        self.fake_docker("")
        for bad in ("10", "-1", "a", "03"):
            r = self.run_env(bad)
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("0~9", r.stderr)
            self.assertIn("고칠 길", r.stderr)
            self.assertNotIn("export ", r.stdout)

    def test_other_checkout_owns_offset(self) -> None:
        self.fake_docker(self.other)
        r = self.run_env("4")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("export ", r.stdout)
        self.assertIn(self.other, r.stderr)
        self.assertIn("고칠 길", r.stderr)

    def chain(self, offset: str, owner: str, tail: str) -> subprocess.CompletedProcess[str]:
        """실제 호출 꼴(`eval "$(…)"` 뒤에 compose)을 흉내 낸다 — compose 대신 표식을 남기는 가짜 docker."""
        d = self.bin / "docker"
        d.write_text(f"#!/bin/sh\n[ \"$1\" = ps ] && {{ echo '{owner}'; exit 0; }}\necho COMPOSE_RAN\n")
        d.chmod(d.stat().st_mode | stat.S_IEXEC)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "CODEMIT_DEV_OFFSET": offset}
        cmd = f'eval "$(sh {self.script})"{tail}'
        return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env, timeout=60)

    def test_rejected_offset_stops_compose(self) -> None:
        for tail in (" && docker compose up", "; docker compose up", "\ndocker compose up"):
            r = self.chain("4", self.other, tail)
            self.assertNotIn("COMPOSE_RAN", r.stdout, repr(tail))
            self.assertIn(self.other, r.stderr)
        r = self.chain("4", self.other, "\ndocker compose up\n")
        self.assertNotIn("COMPOSE_RAN", r.stdout)
        # set -e 로 도는 스크립트(scripts/test.sh)는 eval 에서 멈춘다.
        r2 = subprocess.run(
            ["bash", "-c", f'set -e\neval "$(sh {self.script})"\necho AFTER'],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "CODEMIT_DEV_OFFSET": "4"},
        )
        self.assertNotIn("AFTER", r2.stdout)
        self.assertNotEqual(r2.returncode, 0)

    def test_accepted_offset_runs_compose(self) -> None:
        r = self.chain("4", "", " && docker compose up")
        self.assertIn("COMPOSE_RAN", r.stdout, r.stderr)

    def test_own_checkout_owns_offset(self) -> None:
        self.fake_docker(str(self.root / "docker"))
        r = self.run_env("4")
        self.assertEqual(r.returncode, 0, r.stderr)

    def logging_docker(self, owner: str) -> Path:
        """ps 에는 owner 를 답하고, 그 밖의 호출은 로그에 남기는 가짜 docker."""
        log = Path(self._tmp.name) / "docker.log"
        d = self.bin / "docker"
        d.write_text(f"#!/bin/sh\n[ \"$1\" = ps ] && {{ echo '{owner}'; exit 0; }}\necho \"$@\" >> '{log}'\nexit 0\n")
        d.chmod(d.stat().st_mode | stat.S_IEXEC)
        return log

    def test_orphan_stack_is_taken_down_and_offset_used(self) -> None:
        log = self.logging_docker("/gone/worktree/t1077/docker")
        r = self.run_env("4")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("export COMPOSE_PROJECT_NAME=codemit-dev-4", r.stdout)
        self.assertIn("고아", r.stderr)
        calls = log.read_text()
        self.assertIn("compose -p codemit-dev-4 down", calls)
        self.assertNotIn("-v", calls.split())
        self.assertNotIn("volume", calls)

    def test_live_owner_is_still_refused_and_not_taken_down(self) -> None:
        live = Path(self.other)
        log = self.logging_docker(str(live))
        r = self.run_env("4")
        self.assertEqual(r.returncode, 1)
        self.assertIn(str(live), r.stderr)
        self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
