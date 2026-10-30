"""prod 배포가 migrate 전에 DB 를 덤프하는지 — 진짜 `deploy.sh` 를 가짜 `docker` 로 돌린다(#839).

staging 이 없어져(우산 #836 §7) 마이그레이션이 데이터가 든 DB 위에서 처음 도는 자리가 prod
다. 그래서 적용할 마이그레이션이 있는 배포만 migrate 앞에서 `pg_dump` 를 한 번 뜬다. 판정은
새 backend 이미지의 `migrate --plan` 이 하고, 덤프는 db 컨테이너의 pg_dump 를 표준출력으로 받는다.

가짜 `docker` 는 받은 compose 하위 명령을 `calls` 에 적고, 환경변수로 답을 고른다:
`FAKE_PLAN`(migrate --plan 의 출력)·`FAKE_PLAN_FAIL`·`FAKE_DB_BYTES`·`FAKE_DUMP_FAIL`.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent

FAKE_DOCKER = r"""#!/bin/sh
[ "$1" = compose ] || exit 0
echo "$*" >> "$FAKE_CALLS"
case "$*" in
  *"migrate --plan"*)
    [ -n "${FAKE_PLAN_FAIL:-}" ] && { echo "could not connect to server"; exit 1; }
    printf '%s\n' "$FAKE_PLAN"; exit 0 ;;
  *pg_database_size*) echo "${FAKE_DB_BYTES:-1000}"; exit 0 ;;
  *pg_dump*)
    if [ -n "${FAKE_DUMP_FAIL:-}" ]; then printf 'PGDMP-반쯤'; echo "pg_dump: error: connection lost" >&2; exit 1; fi
    printf 'PGDMP-fake-dump'; exit 0 ;;
esac
exit 0
"""

PENDING = "Planned operations:\nclassroom.0042_add_hint\n    Add field hint to problem\n"
NOTHING = "Planned operations:\n  No planned migration operations.\n"


@pytest.fixture
def deploy(tmp_path):
    """`deploy.sh` 사본과 가짜 `docker` — 준비는 픽스처라 시험 본문의 CPU 한도 밖이다(#701)."""

    repo = tmp_path / "repo"
    (repo / "docker").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "deploy.sh", repo / "deploy.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_CALLS": str(calls)}

    def run(target="prod", **fake):
        result = subprocess.run(
            ["sh", "deploy.sh", target, "predeploy-dump"],
            cwd=repo, env={**env, **fake}, capture_output=True, text=True,
        )
        return result, calls.read_text(encoding="utf-8")

    return repo, run


def _dumps(repo: Path) -> list[Path]:
    return sorted((repo / ".jenkins-prod-dumps").glob("*"))


def test_no_pending_migration_takes_no_dump(deploy):
    repo, run = deploy
    result, calls = run(FAKE_PLAN=NOTHING)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pg_dump" not in calls
    assert "덤프를 건너뛴다" in result.stdout
    assert not (repo / ".jenkins-prod-dumps").exists()


def test_pending_migration_dumps_once_private_and_keeps_the_latest_three(deploy):
    repo, run = deploy
    dumps = repo / ".jenkins-prod-dumps"
    dumps.mkdir()
    for stamp in ("20261001-010101", "20261002-010101", "20261003-010101"):
        (dumps / f"codemit-predeploy-{stamp}-aaaaaaaaaaaa.dump").write_bytes(b"PGDMP-old")

    result, calls = run(FAKE_PLAN=PENDING)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.count("pg_dump") == 1
    assert "classroom.0042_add_hint" in result.stdout
    names = [p.name for p in _dumps(repo)]
    assert len(names) == 3 and "codemit-predeploy-20261001-010101-aaaaaaaaaaaa.dump" not in names
    new = [p for p in _dumps(repo) if "20261001" not in p.name and "20261002" not in p.name and "20261003" not in p.name]
    assert len(new) == 1 and new[0].read_bytes() == b"PGDMP-fake-dump"
    assert stat.S_IMODE(new[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(dumps.stat().st_mode) == 0o700
    # 로그에는 경로와 크기만.
    assert re.search(rf"{re.escape(new[0].name)} \(15 바이트\)", result.stdout)


def test_unanswered_plan_is_treated_as_pending(deploy):
    repo, run = deploy
    result, calls = run(FAKE_PLAN_FAIL="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.count("pg_dump") == 1
    assert len(_dumps(repo)) == 1


def test_failed_dump_stops_the_deploy_and_leaves_no_partial_file(deploy):
    repo, run = deploy
    result, _ = run(FAKE_PLAN=PENDING, FAKE_DUMP_FAIL="1")
    assert result.returncode != 0
    assert "배포를 멈춘다" in result.stdout
    assert _dumps(repo) == []


def test_too_little_disk_stops_before_dumping(deploy):
    repo, run = deploy
    result, calls = run(FAKE_PLAN=PENDING, FAKE_DB_BYTES=str(10**18))
    assert result.returncode != 0
    assert "pg_dump" not in calls
    assert "여유" in result.stdout


def test_staging_is_refused_before_anything_runs(deploy):
    _, run = deploy
    result, calls = run(target="staging", FAKE_PLAN=PENDING)
    assert result.returncode == 2, result.stdout + result.stderr
    assert calls == ""


def test_up_dumps_before_it_stops_or_migrates_anything():
    """`up` 은 교체·풀러 블록보다 먼저, backend 를 바꿀 때만 덤프한다 — 실패하면 그 자리에서 끝난다."""

    body = (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8").split("\ncmd_up() {\n", 1)[1].split("\n}\n", 1)[0]
    gate = body.index('if [ "$BUILD_BACKEND" = true ] && ! dump_before_migrate; then\n    exit 1')
    assert gate < body.index("$COMPOSE stop")
    assert gate < body.index("run_migrations")
    assert gate < body.index('if [ "$BUILD_PGBOUNCER" = true ]')
