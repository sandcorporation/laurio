"""`deploy.sh plan` 이 compose 파일만 바뀐 배포를 겹쳐 바꾸는지 — 진짜 스크립트를 돌린다.

2026-10-06 prod(GlitchTip 64 재발, 강의실 알림 수 `TypeError: fetch failed`): #582 가
`docker/compose.prod.yaml` 에 채점 워커 `celery-scoring` 을 더했다. `plan` 은 compose 파일이
바뀌면 「어느 서비스의 환경이 바뀌었는지 모른다」며 **풀러까지** 바꿀 것으로 표시했고, 풀러를
바꾸는 배포는 겹쳐 바꾸지 않는다 — backend·events 를 내리고 올렸다. 그 창(이벤트 서비스 이름이
16초 넘게 안 풀렸다)이 BFF 재시도 예산(약 15.8초)보다 길어 강의실 BFF 가 500 을 냈다.

풀러의 정의가 그대로면 풀러를 바꿀 까닭이 없다. 이 시험은 임시 git 저장소에 직전 배포와
지금 커밋을 만들고 진짜 `deploy.sh prod plan` 을 돌린다. `docker` 는 PATH 의 가짜다 — 컨테이너는
다 떠 있다고 답하고, `compose -f <파일> config <서비스>` 에는 그 파일의 그 서비스 정의를
내놓는다(compose 가 렌더한 정의를 비교하는 자리를 그대로 흉내 낸다).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
COMPOSE = "docker/compose.prod.yaml"

# 가짜 `docker` 는 `sh` 다 — `plan` 은 서비스마다 `compose ps -q` 를 부르는데(열두 번 남짓),
# 그때마다 파이썬을 띄우면 그것만으로 CPU 0.4초가 든다(#701). 정의를 렌더해야 하는
# `config` 만 파이썬(`docker-config`)에 넘긴다.
FAKE_DOCKER = """#!/bin/sh
[ "$1" = compose ] || exit 0  # docker inspect 등 — 이 시험에서는 볼 것이 없다
shift
compose_file=
while [ $# -gt 0 ]; do
  case "$1" in
    -f) compose_file=$2; shift 2 ;;
    --env-file) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
case "$1" in
  ps) [ "$2" = -q ] && echo "cid-$3" ;;
  config) shift; exec "$(dirname "$0")/docker-config" "$compose_file" "$@" ;;
esac
exit 0
"""

FAKE_DOCKER_CONFIG = f"""#!{sys.executable}
import json, sys
import yaml

compose_file, *names = sys.argv[1:]
with open(compose_file, encoding="utf-8") as f:
    services = yaml.safe_load(f)["services"]
print(json.dumps({{s: services[s] for s in names}}, sort_keys=True))
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _prepare(tmp_path: Path, change) -> tuple[Path, dict[str, str]]:
    """직전 배포·이번 배포 커밋이 든 임시 저장소와 가짜 `docker` 를 PATH 에 둔 환경.

    준비(git 서브프로세스 여럿)라 픽스처에서 부른다 — 시험 본문의 CPU 한도 밖이다(#701).
    본문에는 `plan` 호출과 단언만 남는다."""

    repo = tmp_path / "repo"
    (repo / "docker").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "deploy.sh", repo / "deploy.sh")
    compose = (REPO_ROOT / COMPOSE).read_text(encoding="utf-8")
    (repo / COMPOSE).write_text(compose, encoding="utf-8")
    (repo / ".gitignore").write_text(".jenkins-*\ndocker/.env.prod\n", encoding="utf-8")
    (repo / "docker/.env.prod").write_text("", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "직전 배포")
    (repo / ".jenkins-prod-deployed").write_text(_git(repo, "rev-parse", "HEAD") + "\n")

    (repo / COMPOSE).write_text(change(compose), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "이번 배포")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("docker-config", FAKE_DOCKER_CONFIG)):
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return repo, env


def _plan(prepared: tuple[Path, dict[str, str]]) -> dict[str, str]:
    repo, env = prepared
    result = subprocess.run(
        ["sh", "deploy.sh", "prod", "plan"], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = (repo / ".jenkins-prod-plan").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in plan.splitlines() if "=" in line)


@pytest.fixture
def other_service_changed(tmp_path):
    # #582 의 모양 — 다른 서비스의 command 만 바꾼다.
    def change(compose: str) -> str:
        changed = compose.replace(
            "command: celery -A config worker -Q celery --loglevel info",
            "command: celery -A config worker -Q celery --loglevel debug",
        )
        assert changed != compose
        return changed

    return _prepare(tmp_path, change)


def test_compose_change_that_leaves_the_pooler_alone_still_rolls_the_backend(other_service_changed):
    plan = _plan(other_service_changed)

    assert plan["BUILD_BACKEND"] == "true"
    assert plan["BUILD_PGBOUNCER"] == "false"
    assert plan["ROLLING_BACKEND"] == "true"


@pytest.fixture
def pooler_changed(tmp_path):
    def change(compose: str) -> str:
        changed = compose.replace(
            "      PGBOUNCER_POOL_MODE: transaction\n",
            "      PGBOUNCER_POOL_MODE: transaction\n      PGBOUNCER_DEFAULT_POOL_SIZE: 30\n",
        )
        assert changed != compose
        return changed

    return _prepare(tmp_path, change)


def test_compose_change_to_the_pooler_itself_still_replaces_the_pooler(pooler_changed):
    plan = _plan(pooler_changed)

    assert plan["BUILD_PGBOUNCER"] == "true"
    assert plan["ROLLING_BACKEND"] == "false"
