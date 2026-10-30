"""운영 지표 Celery 태스크(#827) — beat 가 `config.celery.SCHEDULED_JOBS` 로 부른다."""

from celery import shared_task


@shared_task(name="ops_metrics.flush_minutes", ignore_result=True)
def flush_minutes() -> dict:
    """1분마다 — 닫힌 분의 Redis 해시를 DB 집계 행으로 옮긴다(`ops_metrics.flush`)."""

    from ops_metrics.flush import flush_closed_minutes

    return flush_closed_minutes()


@shared_task(name="ops_metrics.purge_old_minutes", ignore_result=True)
def purge_old_minutes() -> int:
    """매일 03:40(서울) — 보관 기간보다 오래된 집계 행을 지운다."""

    from core.clock import Clock
    from ops_metrics.flush import purge_old_minutes as purge

    return purge(now=Clock.now())
