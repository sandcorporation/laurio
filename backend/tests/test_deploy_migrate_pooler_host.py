"""배포의 일회성 migrate 컨테이너가 받는 DB 주소가 compose 의 진행 로그로 더럽혀지지 않는지(GlitchTip 106).

`deploy.sh` 의 `run_migrations` 는 풀러(pgbouncer)가 붙는 실제 DB 주소를 `compose run … printenv
pgbouncer POSTGRES_HOST` 로 읽어 `-e POSTGRES_HOST=…` 로 넘긴다. 그 이미지 태그(`<sha>-arm64`)가 호스트에
없고 받지도 못하면(ghcr 자격이 없는 root 로 돈 경우) compose 는 `build:` 로 굽기 시작하고, **그 빌드 진행
로그는 표준출력으로 나온다** — `2>/dev/null` 로는 걸러지지 않는다. 예전에는 그 출력 전체를 `tr -d '\\r\\n'`
으로 한 줄로 이어 붙여 호스트 이름으로 썼고, prod migrate 가 `UnicodeEncodeError: 'idna' codec can't
encode … label empty` 로 죽었다(2026-11-05, release e182e5c, 오류 106).

가짜 `docker` 는 printenv 앞에 빌드 로그를 표준출력으로 쏟고 값은 마지막 줄에 둔다 — 실제 compose 가
그렇게 한다(로컬에서 이미지를 지우고 같은 명령을 돌려 13,099자를 받았다).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent

BUILD_LOG = (
    "#1 [internal] load local bake definitions\n"
    "#1 reading from stdin 653B done\n"
    "#2 [internal] load build definition from pgbouncer.Dockerfile\n"
    "#3 [internal] load .dockerignore\n"
    "#5 [2/4] RUN apt-get update ...\n"
    "#9 exporting to image\n"
)

FAKE_DOCKER = r"""#!/bin/sh
[ "$1" = compose ] || exit 0
echo "$*" >> "$FAKE_CALLS"
case "$*" in
  *"printenv pgbouncer POSTGRES_HOST"*)
    printf '%s' "${FAKE_BUILD_LOG:-}"; printf '%s\r\n' "$FAKE_HOST"; exit 0 ;;
  *"printenv pgbouncer POSTGRES_PORT"*)
    printf '%s' "${FAKE_BUILD_LOG:-}"; printf '%s\n' "${FAKE_PORT:-5432}"; exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def migrate(tmp_path):
    """`deploy.sh` 의 `run_migrations` 를 그대로 떼어 가짜 `docker` 위에서 부른다."""

    body = (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8")
    func = "run_migrations() {\n" + body.split("\nrun_migrations() {\n", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -eu\nlog() { echo \"[deploy] $*\"; }\nCOMPOSE='docker compose'\nCODEMIT_IMAGE_TAG=abcdef123456\n"
        + func
        + "run_migrations\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_CALLS": str(calls)}

    def run(**fake):
        result = subprocess.run(["sh", str(harness)], env={**env, **fake}, capture_output=True, text=True)
        lines = calls.read_text(encoding="utf-8").splitlines()
        migrate_calls = [line for line in lines if "manage.py migrate" in line]
        return result, migrate_calls

    return run


def test_build_progress_on_stdout_does_not_become_the_db_host(migrate):
    result, calls = migrate(FAKE_BUILD_LOG=BUILD_LOG, FAKE_HOST="db")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 1
    assert "-e POSTGRES_HOST=db -e POSTGRES_PORT=5432 " in calls[0]
    assert "#1" not in calls[0]


def test_clean_answer_is_used_as_is(migrate):
    result, calls = migrate(FAKE_HOST="codemit.cluster-x.ap-seoul-1.rds.example.com", FAKE_PORT="6543")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-e POSTGRES_HOST=codemit.cluster-x.ap-seoul-1.rds.example.com -e POSTGRES_PORT=6543 " in calls[0]
    assert "lock_timeout" in calls[0]


def test_unusable_answer_falls_back_to_the_pooler_path(migrate):
    """마지막 줄마저 호스트 이름이 아니면 덮어쓰지 않는다 — 풀러를 거치는 예전 경로로 돈다."""

    result, calls = migrate(FAKE_BUILD_LOG=BUILD_LOG, FAKE_HOST="#9 DONE 0.4s")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "POSTGRES_HOST" not in calls[0]
    assert "PGOPTIONS" not in calls[0]
    assert "풀러를 거쳐" in result.stdout
