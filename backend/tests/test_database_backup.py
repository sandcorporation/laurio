"""매일 새벽 2시 DB 를 오브젝트 스토리지로 백업한다.

HTTP 표면이 없는 운영 작업이다 — 스캔처럼 내부 엔드포인트를 거치지 않고 워커 안에서 직접
돈다(pg_dump·업로드가 내부 HTTP 의 30초 타임아웃을 넘길 수 있다). 그래서 이 파일은 Celery
작업 함수를 직접 부른다. 스토리지는 fake, `pg_dump` 는 받은 인자를 기록하고 덤프 파일을
쓰는 가짜 실행 파일로 바꾼다 — 호스트에 pg_dump 17 이 없어도 돈다. 실물 pg_dump 는 이미지
빌드 뒤 dev 스택에서 한 번 걸어 확인한다.
"""

from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from celery.schedules import crontab

from config.celery import app as celery_app
from core import tasks as core_tasks
from core.models import ClockOverride, DatabaseBackup
from storage.adapters.base import Bucket
from storage.adapters.fake import FakeStorageAdapter

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def fake_pg_dump(tmp_path, settings):
    calls = tmp_path / "calls.jsonl"
    script = tmp_path / "pg_dump"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        f"open({str(calls)!r}, 'a').write(json.dumps({{'args': args, 'has_password': bool(os.environ.get('PGPASSWORD'))}}) + '\\n')\n"
        "if os.environ.get('FAKE_PG_DUMP_FAIL'):\n"
        "    sys.stderr.write('pg_dump: error: connection refused\\n'); sys.exit(1)\n"
        "out = args[args.index('--file') + 1]\n"
        "open(out, 'wb').write(b'PGDMP-fake-dump')\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    settings.DB_BACKUP_PG_DUMP_COMMAND = str(script)
    return calls


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _private_keys(prefix="db-backups/"):
    return sorted(k for (bucket, k) in FakeStorageAdapter._store if bucket == Bucket.PRIVATE and k.startswith(prefix))


def test_beat_runs_the_backup_every_day_at_2am_seoul_time():
    entry = celery_app.conf.beat_schedule["backup:database"]
    assert entry["task"] == "core.backup_database"
    assert isinstance(entry["schedule"], crontab)
    assert entry["schedule"].hour == {2} and entry["schedule"].minute == {0}
    assert str(celery_app.conf.timezone) == "Asia/Seoul"


def test_backup_uploads_a_custom_format_dump_to_the_private_bucket_and_records_it(db, fake_pg_dump):
    _freeze(datetime(2026, 9, 15, 2, 0, 5, tzinfo=KST))

    result = core_tasks.backup_database()

    assert result["status"] == "succeeded"
    assert _private_keys() == ["db-backups/2026/09/15/laurio-20260915-020005.dump"]
    assert FakeStorageAdapter._store[(Bucket.PRIVATE, _private_keys()[0])] == b"PGDMP-fake-dump"
    call = json.loads(fake_pg_dump.read_text().splitlines()[0])
    assert "--format=custom" in call["args"]
    assert call["has_password"] is True  # 비밀번호는 인자가 아니라 환경변수로 넘긴다
    assert not any("password" in a.lower() for a in call["args"])
    backup = DatabaseBackup.objects.get()
    assert backup.status == DatabaseBackup.Status.SUCCEEDED
    assert backup.object_key == _private_keys()[0]
    assert backup.size_bytes == len(b"PGDMP-fake-dump")


def test_a_second_run_on_the_same_day_does_not_back_up_again(db, fake_pg_dump):
    _freeze(datetime(2026, 9, 15, 2, 0, 5, tzinfo=KST))
    core_tasks.backup_database()
    _freeze(datetime(2026, 9, 15, 2, 7, 0, tzinfo=KST))

    result = core_tasks.backup_database()

    assert result["status"] == "skipped"
    assert len(_private_keys()) == 1
    assert len(fake_pg_dump.read_text().splitlines()) == 1


def test_backups_older_than_the_retention_are_deleted(db, fake_pg_dump, settings):
    settings.DB_BACKUP_RETENTION_DAYS = 14
    _freeze(datetime(2026, 9, 1, 2, 0, 0, tzinfo=KST))
    core_tasks.backup_database()
    _freeze(datetime(2026, 9, 10, 2, 0, 0, tzinfo=KST))
    core_tasks.backup_database()
    _freeze(datetime(2026, 9, 16, 2, 0, 0, tzinfo=KST))  # 9/1 은 15일 전 — 보존 기간 밖

    core_tasks.backup_database()

    assert _private_keys() == [
        "db-backups/2026/09/10/laurio-20260910-020000.dump",
        "db-backups/2026/09/16/laurio-20260916-020000.dump",
    ]
    old = DatabaseBackup.objects.get(object_key__contains="20260901")
    assert old.status == DatabaseBackup.Status.PRUNED


def test_a_failed_dump_is_recorded_uploads_nothing_and_fails_the_task(db, fake_pg_dump, monkeypatch):
    monkeypatch.setenv("FAKE_PG_DUMP_FAIL", "1")
    _freeze(datetime(2026, 9, 15, 2, 0, 0, tzinfo=KST))

    with pytest.raises(RuntimeError):
        core_tasks.backup_database()

    assert _private_keys() == []
    backup = DatabaseBackup.objects.get()
    assert backup.status == DatabaseBackup.Status.FAILED
    assert "connection refused" in backup.error
    # 실패한 날은 「오늘 이미 했다」로 치지 않는다 — 다음 실행이 다시 시도한다
    monkeypatch.delenv("FAKE_PG_DUMP_FAIL")
    assert core_tasks.backup_database()["status"] == "succeeded"
