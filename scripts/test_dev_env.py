#!/usr/bin/env python3
"""`docker/dev-env.sh` 의 CODEMIT_DEV_OFFSET 지정(#1106)과 해시 칸 고르기(#1409)를 고정한다.

`python3 scripts/test_dev_env.py` 하나로 돈다. 가짜 docker 를 PATH 앞에 둔다.
"""

from __future__ import annotations

import os
import re
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


    # ── 해시 분기(#1409) ──────────────────────────────────────────────────────────
    def stacks(self, owners: dict[str, str]) -> None:
        """`{프로젝트: working_dir}` 만큼의 컨테이너 라벨을 흉내 낸다 — 목록과 프로젝트별 주인 조회에 답한다."""
        state = Path(self._tmp.name) / "stacks"
        state.write_text("".join(f"{p}|{o}\n" for p, o in owners.items()))
        d = self.bin / "docker"
        d.write_text(
            "#!/bin/sh\n"
            '[ "$1" = ps ] || exit 0\n'
            'p=; for a in "$@"; do case "$a" in label=com.docker.compose.project=*) p=${a##*=} ;; esac; done\n'
            f"if [ -n \"$p\" ]; then awk -F'|' -v p=\"$p\" '$1==p{{print $2}}' '{state}'; else cut -d'|' -f1 '{state}'; fi\n"
        )
        d.chmod(d.stat().st_mode | stat.S_IEXEC)

    def linked_worktree(self) -> None:
        """self.script 를 주 워크트리가 아닌 체크아웃의 것으로 바꾼다 — 해시 분기를 탄다."""
        git = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        self.root = self.root.parent / "linked"
        subprocess.run([*git, "worktree", "add", "-q", "--detach", str(self.root)], check=True)
        (self.root / "docker").mkdir()
        self.script = self.root / "docker" / "dev-env.sh"
        self.script.write_text(SRC.read_text())
        (self.root / "docker" / "dev-stack-orphans.sh").write_text((SRC.parent / "dev-stack-orphans.sh").read_text())

    def offset_of(self, r: subprocess.CompletedProcess[str]) -> int:
        self.assertEqual(r.returncode, 0, r.stderr)
        found = re.search(r"^export COMPOSE_PROJECT_NAME=codemit-dev-([1-9])$", r.stdout, re.M)
        assert found, r.stdout
        return int(found.group(1))

    def hashed(self) -> int:
        self.linked_worktree()
        self.stacks({})
        return self.offset_of(self.run_env(None))

    def test_hash_slot_of_another_checkout_moves_to_next_free_slot(self) -> None:
        first = self.hashed()
        second = first % 9 + 1
        third = second % 9 + 1
        # dev 스택이든 `-e2e` 스택만 떠 있든(`test.sh e2e`) 남의 칸이다.
        for suffix in ("", "-e2e"):
            with self.subTest(suffix=suffix):
                self.stacks({f"codemit-dev-{first}{suffix}": self.other})
                r = self.run_env(None)
                self.assertEqual(self.offset_of(r), second)
                self.assertIn(self.other, r.stderr)
        self.stacks({f"codemit-dev-{first}": self.other, f"codemit-dev-{second}-e2e": self.other})
        self.assertEqual(self.offset_of(self.run_env(None)), third)

    def test_own_slot_is_kept_on_the_next_call(self) -> None:
        first = self.hashed()
        second = first % 9 + 1
        mine = str(self.root / "docker")
        for suffix in ("", "-e2e"):
            with self.subTest(suffix=suffix):
                # 밀려난 칸에 내 라벨이 붙은 뒤, 해시 칸의 남이 내려가 비어도 내 칸에 남는다.
                self.stacks({f"codemit-dev-{second}{suffix}": mine})
                self.assertEqual(self.offset_of(self.run_env(None)), second)
        self.stacks({f"codemit-dev-{first}": mine})
        self.assertEqual(self.offset_of(self.run_env(None)), first)

    def test_gone_checkout_does_not_hold_a_slot(self) -> None:
        first = self.hashed()
        self.stacks({f"codemit-dev-{first}-e2e": "/gone/worktree/docker"})
        self.assertEqual(self.offset_of(self.run_env(None)), first)

    def test_all_slots_taken_is_refused(self) -> None:
        self.linked_worktree()
        self.stacks({f"codemit-dev-{n}{'-e2e' if n % 2 else ''}": self.other for n in range(1, 10)})
        r = self.run_env(None)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("export ", r.stdout)
        self.assertIn("false", r.stdout.split())
        self.assertIn(self.other, r.stderr)
        self.assertIn("고칠 길", r.stderr)


if __name__ == "__main__":
    unittest.main()
