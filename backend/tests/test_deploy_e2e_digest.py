"""`deploy.sh prod e2e-digest` — 떠 있는 앱·backend 가 열차의 e2e 가 본 이미지인지 견준다(#729). 진짜 스크립트를 돌린다.

열차는 e2e 가 받은 arm64 이미지에 `e2e-<묶음 트리>-arm64` 태그를 붙이고(`scripts/ci/images-e2e.sh`), prod 는
이 커밋의 트리로 그 태그를 받아 컨테이너의 이미지 ID 와 견준다. 여기서 고정하는 셋:
- 같으면 「같다」, 다르면 「다르다!」, 태그가 없거나 컨테이너가 없으면 「대조 못 함」으로 적는다.
- **관측만 한다** — 무엇이 나와도 0 으로 끝난다(배포를 붉히지 않는다).
- 태그는 이 커밋의 **트리**로 찾는다(쌓은 sha 와 main 의 sha 는 다르고, 같은 것은 트리다).

가짜 `docker` 의 상태: `running-<서비스>` 는 떠 있는 컨테이너의 이미지 ID, `e2e-<서비스>` 는 그 서비스의
e2e 태그가 가리키는 이미지 ID(없으면 태그가 없다). 받은 ref 는 `pulled` 에 적는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_deploy_plan_rolling import COMPOSE, REPO_ROOT, _git

FAKE_DOCKER = """#!/bin/sh
state="$FAKE_DOCKER_STATE"
case "$1" in
  inspect) cat "$state/running-${4#cid-}" 2>/dev/null; exit 0 ;;
  pull)
    echo "$3" >> "$state/pulled"
    svc=${3##*/codemit-}; svc=${svc%%:*}
    [ -e "$state/e2e-$svc" ]; exit $? ;;
  image)
    if [ "$2" = inspect ]; then svc=${5##*/codemit-}; svc=${svc%%:*}; cat "$state/e2e-$svc"; fi
    exit 0 ;;
  compose)
    shift
    while [ $# -gt 0 ]; do case "$1" in -f|--env-file) shift 2 ;; -*) shift ;; *) break ;; esac; done
    if [ "$1" = ps ] && [ -e "$state/running-$3" ]; then echo "cid-$3"; fi
    exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def prod(tmp_path):
    """커밋 하나짜리 저장소 + 가짜 docker. 준비는 픽스처에서 — 시험 본문의 CPU 한도 밖이다(#701)."""
    repo = tmp_path / "repo"
    (repo / "docker").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "deploy.sh", repo / "deploy.sh")
    shutil.copy(REPO_ROOT / COMPOSE, repo / COMPOSE)
    (repo / "docker/.env.prod").write_text("", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "배포")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_DOCKER_STATE": str(state)}
    return repo, env, state, tree


def _run(repo: Path, env: dict[str, str], target: str = "prod") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", "deploy.sh", target, "e2e-digest"], cwd=repo, env=env, capture_output=True, text=True)


def test_each_service_is_reported_and_the_run_stays_green(prod) -> None:
    repo, env, state, tree = prod
    (state / "running-backend").write_text("sha256:aaa\n")
    (state / "e2e-backend").write_text("sha256:aaa\n")
    (state / "running-frontend").write_text("sha256:bbb\n")
    (state / "e2e-frontend").write_text("sha256:ccc\n")
    (state / "running-operator").write_text("sha256:ddd\n")  # e2e 태그가 없다
    # classroom 은 떠 있지 않다

    done = _run(repo, env)

    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "e2e 대조: backend — 같다" in out
    assert "e2e 대조: frontend — 다르다!" in out
    assert "e2e 대조: operator — " in out and "열차가 이 트리를 e2e 로 보지 않았다" in out
    assert "e2e 대조: classroom — 떠 있는 컨테이너가 없다" in out
    assert "같다 1 · 다르다 1 · 대조 못 함 2" in out
    assert f"ghcr.io/sandcorporation/codemit-backend:e2e-{tree}-arm64" in (state / "pulled").read_text()


def test_staging_is_not_compared(prod) -> None:
    repo, env, state, _ = prod
    (repo / "docker/compose.staging.yaml").write_text("services: {}\n")
    (repo / "docker/.env.staging").write_text("")

    done = _run(repo, env, "staging")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "대조하지 않는다" in done.stdout
    assert not (state / "pulled").exists()
