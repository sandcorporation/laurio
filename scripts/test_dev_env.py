#!/usr/bin/env python3
"""`docker/dev-env.sh` 의 CODEMIT_DEV_OFFSET 지정(#1106)·해시 칸 고르기(#1409)·칸 예약 파일(#1411)을 고정한다.

`python3 scripts/test_dev_env.py` 하나로 돈다. 가짜 docker 를 PATH 앞에 두고, HOME·XDG_STATE_HOME 은 임시 폴더다 —
이 머신의 실제 컨테이너·칸 예약에 닿지 않는다.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
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
        home = Path(self._tmp.name) / "home"
        home.mkdir()
        self.slots = home / "state" / "codemit" / "dev-slots"
        self.base_env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(home),
            "XDG_STATE_HOME": str(home / "state"),
        }
        self.base_env.pop("CODEMIT_DEV_OFFSET", None)
        # CI 의 검사 컨테이너에는 .git 이 없다 — 임시 저장소에 복사해 돌린다(주 워크트리 = 그 저장소).
        self.root = Path(self._tmp.name).resolve() / "repo"
        (self.root / "docker").mkdir(parents=True)
        self.script = self.root / "docker" / "dev-env.sh"
        self.script.write_text(SRC.read_text())
        self.copy_helpers(self.root)
        # 남의 체크아웃 — 디렉터리가 살아 있어야 「남의 스택」이다(사라졌으면 고아).
        self.other = str(Path(self._tmp.name) / "other" / "docker")
        Path(self.other).mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def copy_helpers(self, root: Path) -> None:
        for helper in SRC.parent.glob("dev-*.sh"):
            (root / "docker" / helper.name).write_text(helper.read_text())

    def fake_docker(self, owner: str) -> None:
        d = self.bin / "docker"
        d.write_text(f"#!/bin/sh\n[ -n '{owner}' ] && echo '{owner}'\nexit 0\n")
        d.chmod(d.stat().st_mode | stat.S_IEXEC)

    def run_env(self, offset: str | None, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {**self.base_env, **extra}
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
        env = {**self.base_env, "CODEMIT_DEV_OFFSET": offset}
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
            env={**self.base_env, "CODEMIT_DEV_OFFSET": "4"},
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
        self.root = self.add_worktree(self.root, "linked")
        self.script = self.root / "docker" / "dev-env.sh"

    def add_worktree(self, main: Path, name: str) -> Path:
        wt = main.parent / name
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "--detach", str(wt)], check=True)
        (wt / "docker").mkdir()
        (wt / "docker" / "dev-env.sh").write_text(SRC.read_text())
        self.copy_helpers(wt)
        return wt

    def offset_of(self, r: subprocess.CompletedProcess[str]) -> int:
        self.assertEqual(r.returncode, 0, r.stderr)
        found = re.search(r"^export COMPOSE_PROJECT_NAME=codemit-dev-([1-9])$", r.stdout, re.M)
        assert found, r.stdout
        return int(found.group(1))

    def forget_reservations(self) -> None:
        shutil.rmtree(self.slots, ignore_errors=True)

    def hashed(self) -> int:
        """링크 워크트리의 해시 칸. 알아내며 생긴 예약은 지운다."""
        self.linked_worktree()
        self.stacks({})
        offset = self.offset_of(self.run_env(None))
        self.forget_reservations()
        return offset

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
                self.forget_reservations()
                self.stacks({f"codemit-dev-{second}{suffix}": mine})
                self.assertEqual(self.offset_of(self.run_env(None)), second)
        self.forget_reservations()
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

    # ── 칸 예약 파일(#1411) ────────────────────────────────────────────────────────
    def reserve(self, slot: int, owner: str) -> None:
        self.slots.mkdir(parents=True, exist_ok=True)
        (self.slots / str(slot)).write_text(owner + "\n")

    def reservations(self) -> dict[int, str]:
        return {int(f.name): f.read_text().rstrip("\n") for f in self.slots.glob("[0-9]")}

    def path_without_flock(self) -> str:
        """macOS 흉내 — flock 이 없는 PATH. 스크립트가 쓰는 도구만 링크한다.

        `mkdir` 은 **이미 있어도 성공하는** 것으로 둔다. uutils coreutils 의 mkdir 은 동시에 부르면 둘 다 성공할 때가
        있다 — 잠금이 mkdir 의 실패에 기대면 두 호출이 같이 들어온다.
        """
        bare = Path(self._tmp.name) / "bare"
        bare.mkdir(exist_ok=True)
        tools = "sh git awk sort grep cut tr sed sha256sum dirname rm mv cat head sleep xargs"
        for tool in tools.split():
            found = shutil.which(tool)
            assert found, tool
            if not (bare / tool).exists():
                (bare / tool).symlink_to(found)
        mkdir = bare / "mkdir"
        mkdir.write_text(f'#!/bin/sh\n[ "$1" = -p ] && shift\nexec {shutil.which("mkdir")} -p "$@"\n')
        mkdir.chmod(0o755)
        return f"{self.bin}:{bare}"

    def lock_envs(self) -> dict[str, dict[str, str]]:
        envs = {"noflock": {"PATH": self.path_without_flock()}}
        if shutil.which("flock"):
            envs["flock"] = {}
        return envs

    def colliding_worktrees(self) -> tuple[Path, Path, int]:
        """해시 칸이 같은 링크 워크트리 둘 — 이름을 바꿔 가며 겹치는 것을 찾는다(스크립트와 같은 해시)."""
        self.linked_worktree()
        main = self.root.parent / "repo"

        def slot_of(path: Path) -> int:
            digits = re.sub(r"\D", "", hashlib.sha256(str(path).encode()).hexdigest())[:3]
            return int(digits or "0") % 9 + 1

        want = slot_of(self.root)
        name = next(f"w{i}" for i in range(500) if slot_of(main.parent / f"w{i}") == want)
        return self.root, self.add_worktree(main, name), want

    def test_concurrent_calls_before_any_container_get_different_slots(self) -> None:
        a, b, want = self.colliding_worktrees()
        # `ps` 를 늦춰 두 호출의 고르기가 확실히 겹치게 한다. 컨테이너는 아직 하나도 없다.
        d = self.bin / "docker"
        d.write_text("#!/bin/sh\nsleep 0.5\nexit 0\n")
        d.chmod(d.stat().st_mode | stat.S_IEXEC)
        for name, extra in self.lock_envs().items():
            with self.subTest(lock=name):
                shutil.rmtree(self.slots, ignore_errors=True)
                procs = [
                    subprocess.Popen(
                        ["sh", str(wt / "docker" / "dev-env.sh")], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, env={**self.base_env, **extra},
                    )
                    for wt in (a, b)
                ]
                offsets = []
                for p in procs:
                    out, err = p.communicate(timeout=60)
                    offsets.append(self.offset_of(subprocess.CompletedProcess(p.args, p.returncode, out, err)))
                self.assertEqual(sorted(offsets), sorted([want, want % 9 + 1]))
                self.assertEqual(self.reservations(), {offsets[0]: str(a), offsets[1]: str(b)})

    def test_slot_is_kept_after_every_container_is_down(self) -> None:
        first = self.hashed()
        second = first % 9 + 1
        self.stacks({f"codemit-dev-{first}": self.other})
        self.assertEqual(self.offset_of(self.run_env(None)), second)
        # 내 스택도 남의 스택도 모두 내려갔다 — 해시 칸이 비어도 내 칸은 그대로다.
        self.stacks({})
        self.assertEqual(self.offset_of(self.run_env(None)), second)

    def test_existing_stack_without_a_reservation_is_adopted(self) -> None:
        first = self.hashed()
        second = first % 9 + 1
        self.stacks({f"codemit-dev-{second}": str(self.root / "docker")})
        self.assertEqual(self.offset_of(self.run_env(None)), second)
        self.assertEqual(self.reservations(), {second: str(self.root)})

    def test_orphan_reservation_is_reclaimed(self) -> None:
        first = self.hashed()
        self.reserve(first, "/gone/worktree")
        self.assertEqual(self.offset_of(self.run_env(None)), first)
        self.assertEqual(self.reservations(), {first: str(self.root)})

    def test_live_foreign_reservation_is_skipped_and_left_alone(self) -> None:
        first = self.hashed()
        second = first % 9 + 1
        self.reserve(first, self.other)
        r = self.run_env(None)
        self.assertEqual(self.offset_of(r), second)
        self.assertIn(self.other, r.stderr)
        self.assertEqual(self.reservations(), {first: self.other, second: str(self.root)})

    def test_my_reservation_yields_to_a_live_foreign_stack(self) -> None:
        first = self.hashed()
        second = first % 9 + 1
        self.reserve(first, str(self.root))
        self.stacks({f"codemit-dev-{first}-e2e": self.other})
        r = self.run_env(None)
        self.assertEqual(self.offset_of(r), second)
        self.assertIn(self.other, r.stderr)
        self.assertIn("포트가 바뀐다", r.stderr)
        self.assertEqual(self.reservations(), {second: str(self.root)})

    def test_all_slots_reserved_is_refused(self) -> None:
        self.linked_worktree()
        self.stacks({})
        for n in range(1, 10):
            self.reserve(n, self.other)
        r = self.run_env(None)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("export ", r.stdout)
        self.assertIn(self.other, r.stderr)
        self.assertIn(str(self.slots), r.stderr)

    def test_explicit_offset_refuses_a_live_foreign_reservation(self) -> None:
        self.fake_docker("")
        self.reserve(4, self.other)
        r = self.run_env("4")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("export ", r.stdout)
        self.assertIn(self.other, r.stderr)
        self.assertIn(str(self.slots / "4"), r.stderr)
        self.assertEqual(self.reservations(), {4: self.other})

    def test_explicit_offset_reserves_one_slot_per_checkout(self) -> None:
        self.linked_worktree()
        self.stacks({})
        self.reserve(3, "/gone/worktree")
        for offset in ("3", "7"):
            self.assertEqual(self.run_env(offset).returncode, 0)
            self.assertEqual(self.reservations(), {int(offset): str(self.root)})
        # 비우고 다시 부르면 마지막에 고른 칸이다.
        self.assertEqual(self.offset_of(self.run_env(None)), 7)

    def test_refused_explicit_offset_does_not_reserve(self) -> None:
        self.fake_docker(self.other)
        self.assertEqual(self.run_env("4").returncode, 1)
        self.assertEqual(self.reservations(), {})

    def test_main_worktree_default_does_not_reserve(self) -> None:
        self.fake_docker("")
        for offset in (None, "0"):
            r = self.run_env(offset)
            self.assertIn("COMPOSE_PROJECT_NAME=codemit-dev\n", r.stdout, r.stderr)
        self.assertEqual(self.reservations(), {})

    def test_without_docker_the_reservation_still_applies(self) -> None:
        self.linked_worktree()
        bare = {"PATH": self.path_without_flock()}
        (self.bin / "docker").unlink(missing_ok=True)
        first = self.offset_of(self.run_env(None, **bare))
        second = first % 9 + 1
        self.reserve(first, self.other)
        self.assertEqual(self.offset_of(self.run_env(None, **bare)), second)

    def test_unwritable_state_directory_is_refused(self) -> None:
        self.linked_worktree()
        self.stacks({})
        blocker = Path(self._tmp.name) / "not-a-directory"
        blocker.write_text("")
        r = self.run_env(None, XDG_STATE_HOME=str(blocker))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("export ", r.stdout)
        self.assertIn("XDG_STATE_HOME", r.stderr)

    def test_held_lock_times_out_with_a_refusal(self) -> None:
        self.linked_worktree()
        self.stacks({})
        self.slots.mkdir(parents=True)
        for name, extra in self.lock_envs().items():
            with self.subTest(lock=name):
                if name == "flock":
                    holder = subprocess.Popen(
                        ["flock", str(self.slots / ".lock"), "sh", "-c", "echo held; exec sleep 30"],
                        stdout=subprocess.PIPE, text=True, start_new_session=True,
                    )
                    assert holder.stdout
                    self.assertEqual(holder.stdout.readline(), "held\n")
                else:
                    holder = subprocess.Popen(["sleep", "30"], start_new_session=True)
                    (self.slots / ".lock.pid").write_text(f"{holder.pid}\n")
                try:
                    r = self.run_env(None, CODEMIT_DEV_SLOT_LOCK_TIMEOUT="1", **extra)
                    self.assertEqual(r.returncode, 1, r.stdout)
                    self.assertNotIn("export ", r.stdout)
                    self.assertIn("false", r.stdout.split())
                    self.assertIn("잠금", r.stderr)
                    self.assertIn(str(self.slots / ".lock"), r.stderr)
                    self.assertEqual(self.reservations(), {})
                    if name == "noflock":  # 살아 있는 남의 잠금은 뺏지 않는다.
                        self.assertEqual((self.slots / ".lock.pid").read_text(), f"{holder.pid}\n")
                finally:
                    os.killpg(holder.pid, 9)
                    holder.wait()
                    if holder.stdout:
                        holder.stdout.close()

    def test_lock_of_a_dead_process_is_reclaimed_and_released(self) -> None:
        self.linked_worktree()
        self.stacks({})
        self.slots.mkdir(parents=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        (self.slots / ".lock.pid").write_text(f"{dead.pid}\n")
        r = self.run_env(None, CODEMIT_DEV_SLOT_LOCK_TIMEOUT="5", PATH=self.path_without_flock())
        self.offset_of(r)
        self.assertFalse((self.slots / ".lock.pid").exists())

    def test_refusal_releases_the_noflock_lock(self) -> None:
        self.linked_worktree()
        self.stacks({f"codemit-dev-{n}": self.other for n in range(1, 10)})
        r = self.run_env(None, PATH=self.path_without_flock())
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("1~9", r.stderr)
        self.assertFalse((self.slots / ".lock.pid").exists())


if __name__ == "__main__":
    unittest.main()
