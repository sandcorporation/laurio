"""DB 연결 사용률 경고 스캔 (#455, 부모 #453).

2026-09-18, prod 의 모든 요청이 `too many clients already` 로 500 이 됐다 — Postgres
`max_connections` 한도에 다 찼는데도 아무도 먼저 알지 못했다. 사람이 500 을 보고서야
알았다. 이 스캔은 그 간격을 없앤다: 사용 중 연결이 상한에 가까워지면(기본 80%) 사람이
보기 전에 오류 수집기(GlitchTip, `core.observability.capture_handled_exception`)로
먼저 보낸다.

**무엇을 재는가.** `settings.DB_CONNECTION_MONITOR_ALIAS`(기본 "default")가 가리키는
Django DB 별칭에 `SELECT count(*) FROM pg_stat_activity`(서버 전체 연결 수 — Postgres
`max_connections` 자체가 서버 단위 한도라 특정 DB로 좁히지 않는다)와
`SHOW max_connections`를 그대로 물어본다. **이 스캔이 아는 것은 그 별칭이 지금
가리키는 DB 뿐이다** — 연결 풀러(pgbouncer, #458)가 앞에 서면 앱이 쓰는 "default"
연결은 풀러가 흡수한 뒤의 것이라 실제 서버 연결 수를 보여주지 못한다. 그건 이 파일이
아니라 `settings.DB_CONNECTION_MONITOR_ALIAS` 값의 문제이므로, 풀러를 놓는 쪽(#458)은
풀러를 건너뛰는 DATABASES 별칭을 하나 더 추가하고 그 설정값만 바꾸면 된다 — 이 모듈은
바뀌지 않는다.

**같은 경고를 반복해 쏟지 않는다.** `DbConnectionAlertState`(단일 행, pk=1)가
마지막으로 보낸 시각을 기억한다 — `contests.models.ContestSearchReindexState`와 같은
"실제 벽시계로 조건부 UPDATE 찜하기" 모양이다(그 모델 docstring 참고). 다른 점은 기본값:
재색인 상태는 새 행을 "방금 찜됐다"로 보지만, 여기서는 `last_alerted_at`이 비어 있는
것이 "한 번도 보낸 적 없다"는 뜻이라 첫 임계 초과는 간격을 기다리지 않고 곧바로 보낸다.

**임계값 자체는 실제 벽시계를 쓴다** — `ContestSearchReindexState`와 같은 이유로
주입된 `core.clock.Clock`을 보지 않는다. 이 경고의 "간격"은 시뮬레이션된 시간이 아니라
실제 운영자가 알림 사이에서 겪는 진짜 경과 시간에 매여 있다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, NamedTuple

from django.conf import settings
from django.db import connections
from django.db.models import Q
from django.utils import timezone

from core.scans import ScanSpec

#: 항상 pk=1인 단일 행 — 없으면 만들어서 쓴다.
_STATE_PK = 1


class ConnectionUsage(NamedTuple):
    """한 번 잰 DB 연결 사용량."""

    current: int
    limit: int

    @property
    def ratio(self) -> float:
        if self.limit <= 0:
            return 0.0
        return self.current / self.limit


class DbConnectionUsageHigh(Exception):
    """DB 연결 사용률이 임계를 넘었다 — 오류 수집기로 보내는 표시용 예외.

    실제로 무언가 고장 난 것은 아니다(그래서 5xx로 튀지 않는다) — 아직은 처리된
    상태이지만 운영자가 미리 알아야 하는 경고라 `capture_handled_exception`을 쓴다
    (`contests.search.ContestSearchUnavailable`과 같은 자리).
    """

    def __init__(self, usage: ConnectionUsage, *, threshold: float) -> None:
        super().__init__(
            f"DB 연결 사용률이 임계를 넘었다: {usage.current}/{usage.limit} "
            f"({usage.ratio:.0%} >= {threshold:.0%})"
        )
        self.usage = usage
        self.threshold = threshold


def measure_connection_usage() -> ConnectionUsage:
    """지금 DB 가 스스로 보고하는 연결 사용량. 어느 DB(별칭)를 볼지는
    `settings.DB_CONNECTION_MONITOR_ALIAS`가 정한다 — 모듈 docstring 참고."""

    alias = getattr(settings, "DB_CONNECTION_MONITOR_ALIAS", "default")
    with connections[alias].cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_stat_activity")
        (current,) = cursor.fetchone()
        cursor.execute("SHOW max_connections")
        (limit,) = cursor.fetchone()
    return ConnectionUsage(current=int(current), limit=int(limit))


def _threshold() -> float:
    return float(getattr(settings, "DB_CONNECTION_ALERT_THRESHOLD", 0.8))


def _interval() -> timedelta:
    seconds = int(getattr(settings, "DB_CONNECTION_ALERT_INTERVAL_SECONDS", 900))
    return timedelta(seconds=seconds)


def _is_due(state, now) -> bool:
    return state.last_alerted_at is None or now - state.last_alerted_at >= _interval()


def _candidates(as_of: Any, ctx: dict) -> list[ConnectionUsage]:
    from .models import DbConnectionAlertState

    usage = measure_connection_usage()
    if usage.ratio < _threshold():
        return []

    state, _created = DbConnectionAlertState.objects.get_or_create(pk=_STATE_PK)
    if not _is_due(state, timezone.now()):
        return []
    return [usage]


def _handle_row(usage: ConnectionUsage, as_of: Any, ctx: dict) -> dict | None:
    from .models import DbConnectionAlertState

    now = timezone.now()
    # claim_transition·contests.search_scan 과 같은 조건부 UPDATE — 이 조건에 아직도
    # 걸리는 행만 찜한다. 동시에 두 실행이 들어와도 한쪽만 이겨 경고를 한 번만 보낸다.
    claimed = (
        DbConnectionAlertState.objects.filter(pk=_STATE_PK)
        .filter(_due_filter(now))
        .update(last_alerted_at=now)
    )
    if claimed == 0:
        return None

    threshold = _threshold()
    try:
        raise DbConnectionUsageHigh(usage, threshold=threshold)
    except DbConnectionUsageHigh as exc:
        from core.observability import capture_handled_exception

        capture_handled_exception(
            exc,
            component="db_connection_usage",
            current=str(usage.current),
            limit=str(usage.limit),
            threshold=f"{threshold:.2f}",
        )

    return {"current": usage.current, "limit": usage.limit, "ratio": round(usage.ratio, 4)}


def _due_filter(now):
    return Q(last_alerted_at__isnull=True) | Q(last_alerted_at__lt=now - _interval())


DB_CONNECTION_USAGE_ALERT_SCAN = ScanSpec(
    name="db-connection-usage",
    candidates=_candidates,
    handle_row=_handle_row,
    batch_size=1,
)
