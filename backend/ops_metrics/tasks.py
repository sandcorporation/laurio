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


@shared_task(name="ops_metrics.check_alerts", ignore_result=True)
def check_alerts() -> dict | None:
    """1분마다 — 운영 경보 규칙을 검사하고 울림·해소를 디스코드로 보낸다(`ops_metrics.alerts`, #830).

    시각은 벽시계다(`Clock` 이 아니다) — 지표를 쓰는 쪽(`recorder`·grader 생존 신호)이 벽시계로 분을 정한다."""

    from datetime import datetime
    from datetime import timezone as dt_timezone

    from ops_metrics.alerts import check_alerts as check

    return check(now=datetime.now(dt_timezone.utc))
