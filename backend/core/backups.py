"""매일 새벽 2시, DB 를 오브젝트 스토리지로 백업한다.

**워커 안에서 직접 돈다** — 스캔처럼 내부 HTTP 엔드포인트를 거치지 않는다(`core.tasks`
머리말의 ADR-0003 규약과 다르다). 그 경로는 gunicorn·requests 의 30초 타임아웃에 묶이는데,
pg_dump 와 업로드는 DB 가 커지면 그 시간을 넘긴다. 이 작업에는 「두 번 쏴도 한 번만」을
HTTP 로 지킬 이유도 없다 — 같은 날 두 번째 실행은 `DatabaseBackup` 행을 보고 건너뛴다.

**형식은 `pg_dump --format=custom`** — 압축돼 있고 `pg_restore` 로 테이블 단위 복원이 된다.
비밀번호는 인자가 아니라 `PGPASSWORD` 환경변수로 넘긴다(프로세스 목록에 남지 않게).

**위치는 기존 비공개 버킷의 `db-backups/YYYY/MM/DD/`** — 이미 쓰는 스토리지 연결 그대로다.
보존 기간(`DB_BACKUP_RETENTION_DAYS`)이 지난 백업은 기록된 키로 지운다.

복원: `pg_restore --clean --if-exists --no-owner -d <db> laurio-YYYYMMDD-HHMMSS.dump`.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connections

from core.clock import Clock
from core.models import DatabaseBackup
from storage.adapters import get_storage_adapter
from storage.adapters.base import Bucket

_SEOUL = ZoneInfo("Asia/Seoul")
_PREFIX = "db-backups"


def run_database_backup() -> dict:
    now = Clock.now()
    local = now.astimezone(_SEOUL)
    if DatabaseBackup.objects.filter(
        backup_date=local.date(), status=DatabaseBackup.Status.SUCCEEDED
    ).exists():
        return {"status": "skipped", "reason": "already backed up today", "date": local.date().isoformat()}

    object_key = f"{_PREFIX}/{local:%Y/%m/%d}/laurio-{local:%Y%m%d-%H%M%S}.dump"
    backup = DatabaseBackup.objects.create(started_at=now, backup_date=local.date(), object_key=object_key)
    try:
        dump = _dump()
        get_storage_adapter().write_object(
            object_key, dump, content_type="application/octet-stream", bucket=Bucket.PRIVATE
        )
    except Exception as exc:
        backup.status = DatabaseBackup.Status.FAILED
        backup.error = str(exc)[:4000]
        backup.finished_at = Clock.now()
        backup.object_key = ""
        backup.save(update_fields=["status", "error", "finished_at", "object_key"])
        raise RuntimeError(f"DB 백업 실패: {exc}") from exc

    backup.status = DatabaseBackup.Status.SUCCEEDED
    backup.size_bytes = len(dump)
    backup.finished_at = Clock.now()
    backup.save(update_fields=["status", "size_bytes", "finished_at"])
    pruned = _prune(now)
    return {"status": "succeeded", "object_key": object_key, "size_bytes": len(dump), "pruned": pruned}


def _dump() -> bytes:
    db = connections["default"].settings_dict
    env = {**os.environ, "PGPASSWORD": str(db.get("PASSWORD") or "")}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "laurio.dump"
        cmd = [
            settings.DB_BACKUP_PG_DUMP_COMMAND,
            "--format=custom",
            "--no-owner",
            "--file",
            str(out),
            "--host",
            str(db.get("HOST") or "127.0.0.1"),
            "--port",
            str(db.get("PORT") or "5432"),
            "--username",
            str(db.get("USER") or ""),
            str(db["NAME"]),
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=settings.DB_BACKUP_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"pg_dump exit {proc.returncode}").strip())
        return out.read_bytes()


def _prune(now) -> int:
    cutoff = now - timedelta(days=settings.DB_BACKUP_RETENTION_DAYS)
    storage = get_storage_adapter()
    pruned = 0
    for backup in DatabaseBackup.objects.filter(status=DatabaseBackup.Status.SUCCEEDED, started_at__lt=cutoff):
        storage.delete_object(backup.object_key, bucket=Bucket.PRIVATE)
        backup.status = DatabaseBackup.Status.PRUNED
        backup.save(update_fields=["status"])
        pruned += 1
    return pruned
