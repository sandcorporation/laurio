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
            self.assertEqual(r.stdout, "")
            self.assertIn("0~9", r.stderr)

    def test_other_checkout_owns_offset(self) -> None:
        self.fake_docker("/somewhere/else/docker")
        r = self.run_env("4")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("/somewhere/else/docker", r.stderr)

    def test_own_checkout_owns_offset(self) -> None:
        self.fake_docker(str(self.root / "docker"))
        r = self.run_env("4")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
