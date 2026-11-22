"""push 전 확인(`scripts/local_tests_gate.py` + `.githooks/pre-push`, #1331) — 고른 시험을 돌리지 않고 push 하면 드러난다.

#1328 은 계약 시험 `test_agent_ports` 를 로컬에서 돌리지 않고 올려 PR 검사에서야 빨갰다(작업자 #5791). 임시 저장소와
맨 원격을 만들고 진짜 훅으로 `git push` 한다 — 기록이 없거나·실패했거나·시험 뒤 고쳤으면 거절, 시험한 그대로면
보낸다. 남의 변경을 merge 로 받은 뒤(`spec.py push`)·문서만·우회 꼬리말은 보낸다.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("local_tests_gate", REPO / "scripts" / "local_tests_gate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True, env=ENV)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    sh("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    sh("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    (work / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "local_tests_gate.py", work / "scripts")
    (work / ".githooks").mkdir()
    shutil.copy(REPO / ".githooks" / "pre-push", work / ".githooks")
    (work / "app.py").write_text("x = 1\n")
    sh("add", "-A", cwd=work)
    sh("commit", "-qm", "init", cwd=work)
    sh("remote", "add", "origin", str(origin), cwd=work)
    sh("push", "-q", "origin", "main", cwd=work)  # 훅을 걸기 전 — 원격의 출발점
    sh("config", "core.hooksPath", ".githooks", cwd=work)
    sh("switch", "-qc", "t1", cwd=work)
    return work


def commit(work: Path, name: str, text: str, message: str = "change") -> None:
    (work / name).parent.mkdir(parents=True, exist_ok=True)
    (work / name).write_text(text)
    sh("add", "-A", cwd=work)
    sh("commit", "-qm", message, cwd=work)


def record_run(work: Path, passed: bool = True, ran: tuple[str, ...] = ("backend", "vitest", "e2e")) -> None:
    gate.write(work, base="origin/main", picked={"backend": 1, "vitest": 0, "e2e": 1}, ran=ran, passed=passed)


def push(work: Path) -> subprocess.CompletedProcess[str]:
    return sh("push", "origin", "HEAD:refs/heads/t1", cwd=work, check=False)


def test_pushing_without_running_the_picked_tests_is_refused(repo: Path) -> None:
    commit(repo, "app.py", "x = 2\n")
    out = push(repo)
    assert out.returncode != 0
    assert "scripts/test.sh affected" in out.stderr


def test_pushing_what_was_tested_goes_through(repo: Path) -> None:
    (repo / "app.py").write_text("x = 2\n")
    record_run(repo)  # 커밋 전에 돌린 TDD — 작업 트리를 잰다
    sh("commit", "-qam", "change", cwd=repo)
    assert push(repo).returncode == 0


def test_a_change_after_the_run_is_refused_and_named(repo: Path) -> None:
    commit(repo, "app.py", "x = 2\n")
    record_run(repo)
    commit(repo, "app.py", "x = 3\n")
    out = push(repo)
    assert out.returncode != 0
    assert "app.py" in out.stderr


def test_a_failed_run_is_refused(repo: Path) -> None:
    commit(repo, "app.py", "x = 2\n")
    record_run(repo, passed=False)
    assert push(repo).returncode != 0


def test_skipping_a_picked_kind_is_refused(repo: Path) -> None:
    commit(repo, "app.py", "x = 2\n")
    record_run(repo, ran=("backend",))
    out = push(repo)
    assert out.returncode != 0 and "e2e" in out.stderr


def test_merging_someone_elses_work_after_the_run_still_goes_through(repo: Path) -> None:
    # 다른 사슬이 먼저 올린 것을 받아 합친다 — spec.py push 의 merge
    other = repo.parent / "other"
    sh("clone", "-q", str(repo.parent / "origin.git"), str(other), cwd=repo.parent)
    commit(other, "lib.py", "y = 1\n")
    sh("push", "-q", "origin", "HEAD:refs/heads/t1", cwd=other)
    commit(repo, "app.py", "x = 2\n")
    record_run(repo)
    sh("fetch", "-q", "origin", cwd=repo)
    sh("merge", "-q", "--no-edit", "origin/t1", cwd=repo)
    assert push(repo).returncode == 0


def test_docs_only_goes_through_without_a_run(repo: Path) -> None:
    commit(repo, "docs/ops/x.md", "글\n")
    assert push(repo).returncode == 0


def test_the_skip_trailer_goes_through_and_says_so(repo: Path) -> None:
    commit(repo, "app.py", "x = 2\n", message="급한 고침\n\nLocal-Tests-Skipped: 운영 장애, 시험은 PR 검사로")
    out = push(repo)
    assert out.returncode == 0
    assert "Local-Tests-Skipped" in out.stderr
