"""연결 풀러(pgbouncer) 뒤에서 Django 가 실제로 도는지 확인하는 live 테스트
(#453/#457).

`CODEMIT_PGBOUNCER_PORT`(dev `pgbouncer` 프로필의 호스트 포트,
`docker compose -f docker/compose.dev.yaml --profile pgbouncer up -d`)가 있을
때만 돈다 — 없으면 `tests/live.py`의 원칙대로 skip이지 실패가 아니다.
`@live_infra`라 기본 스위트·CI에서 제외된다.

풀러는 트랜잭션 모드다(#453 Implementation Decisions) — 매 트랜잭션이 끝날
때마다 실제 DB 연결이 다른 클라이언트에게 넘어갈 수 있다. 이미 마이그레이션이
끝난 dev DB(`codemit`)를 그대로 쓰면 `manage.py migrate`가 아무 DDL도 내지
않아 "쓰기가 되는가"를 증명하지 못하므로, 이 테스트는 자기 몫의 일회용 DB를
새로 만들어 처음부터 마이그레이션을 태운다. 풀러의 `[databases] * = ...`
와일드카드(docker/pgbouncer/docker-entrypoint.sh)가 그 이름을 그대로 실제
Postgres로 전달하는 덕분에, DB 이름을 풀러 설정에 미리 등록해 둘 필요가 없다.

CREATE/DROP DATABASE는 풀러를 거치지 않고 직접 접속으로 한다 — 그 자체가
트랜잭션 안에서 돌 수 없는 명령이고, DROP은 활성 연결이 있으면 거부되는데
풀러 뒤에 유휴 연결이 남아 있을 수 있어서다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

from tests.live import live_infra, require_live_credential

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _direct_dsn() -> str:
    """풀러가 아니라 실제 Postgres로 바로 붙는 DSN — 스캐폴딩(만들기/지우기) 전용."""

    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("CODEMIT_DB_PORT", "55432")
    user = os.environ.get("POSTGRES_USER", "codemit")
    password = os.environ.get("POSTGRES_PASSWORD", "codemit")
    return f"host={host} port={port} user={user} password={password} dbname=postgres"


def _make_scratch_database() -> str:
    name = f"pgbouncer_live_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_direct_dsn(), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return name


def _drop_scratch_database(name: str) -> None:
    with psycopg.connect(_direct_dsn(), autocommit=True) as conn:
        # 직접 접속으로 지운다 — 풀러 뒤에 유휴 연결이 남아 있으면 DROP DATABASE가
        # "being accessed by other users"로 거부된다.
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def _env_through_pooler(db_name: str, pgbouncer_port: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": pgbouncer_port,
            "POSTGRES_DB": db_name,
            # 트랜잭션 모드에서 서버측 커서가 깨지는 것을 막는 값(#457,
            # config/settings.py 주석) — 풀러 뒤에서는 항상 켠다.
            "CODEMIT_DB_DISABLE_SERVER_SIDE_CURSORS": "true",
            "DJANGO_SECRET_KEY": "pgbouncer-live-test-secret",
            "DJANGO_ALLOWED_HOSTS": "*",
        }
    )
    return env


@live_infra
def test_migrate_read_write_through_pgbouncer():
    pgbouncer_port = require_live_credential("CODEMIT_PGBOUNCER_PORT")

    db_name = _make_scratch_database()
    try:
        env = _env_through_pooler(db_name, pgbouncer_port)

        migrate = subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert migrate.returncode == 0, migrate.stdout + migrate.stderr

        write_then_read = subprocess.run(
            [
                sys.executable,
                "manage.py",
                "shell",
                "-c",
                (
                    "from django.contrib.auth import get_user_model\n"
                    "User = get_user_model()\n"
                    "User.objects.create_user(\n"
                    "    username='pgbouncer-live', email='pgbouncer-live@example.invalid'\n"
                    ")\n"
                    "print('COUNT=' + str(User.objects.filter(username='pgbouncer-live').count()))\n"
                ),
            ],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert write_then_read.returncode == 0, write_then_read.stdout + write_then_read.stderr
        assert "COUNT=1" in write_then_read.stdout, write_then_read.stdout
    finally:
        _drop_scratch_database(db_name)


@live_infra
def test_request_db_timeouts_hold_through_pgbouncer():
    # 요청 한도(#745)는 문마다 `SET LOCAL` 을 같은 메시지에 실어 보낸다 — 트랜잭션 모드
    # 풀러가 둘을 다른 서버 연결로 가르지 않고, 한도가 다음 클라이언트에게 남지 않는지를
    # 실제 풀러 뒤에서 본다. 시험용 뷰(`tests/test_request_db_timeouts.py`)는 테이블을 읽지
    # 않으므로 일회용 DB 를 마이그레이션하지 않는다.
    pgbouncer_port = require_live_credential("CODEMIT_PGBOUNCER_PORT")

    db_name = _make_scratch_database()
    try:
        run = subprocess.run(
            [
                sys.executable,
                "manage.py",
                "shell",
                "-c",
                (
                    "from django.db import connection\n"
                    "from django.test import Client, override_settings\n"
                    "with override_settings(ROOT_URLCONF='tests.test_request_db_timeouts'):\n"
                    "    print('BODY=' + Client().get('/settings/').content.decode())\n"
                    "with connection.cursor() as cursor:\n"
                    "    cursor.execute('SHOW statement_timeout')\n"
                    "    print('AFTER=' + cursor.fetchone()[0])\n"
                ),
            ],
            cwd=BACKEND_DIR,
            env=_env_through_pooler(db_name, pgbouncer_port),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        assert (
            'BODY={"statement": "25s", "lock": "5s", "autocommit": "25s", "is_autocommit": true}'
            in run.stdout
        ), run.stdout
        assert "AFTER=0" in run.stdout, run.stdout
    finally:
        _drop_scratch_database(db_name)
