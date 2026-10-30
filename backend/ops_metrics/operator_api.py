"""운영자 콘솔의 운영 지표(#827) — `GET /api/operator/ops-metrics?range=1h|24h|7d`.

**운영자 전원이 본다**(`OperatorAuth`, 사용 현황과 같은 등급) — 읽기 전용이고 라벨이 닫힌 집합이라 사람을
가리키는 값이 없다. 응답은 영역별(`llm`·`requests`(#828))로 `totals` 와 `buckets` 를 내고, 같은 층의 `alerts`(#830)가
지금 울리는 경보다(기간과 무관하다 — 마지막 검사의 상태).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ninja import Query, Router, Schema

from core.clock import Clock
from core.operator_auth import OperatorAuth

from .alerts import firing
from .summary import summarize

ops_metrics_operator_router = Router(tags=["operator", "ops-metrics"], auth=OperatorAuth())

RangeKey = Literal["1h", "24h", "7d"]


class LlmCallsOut(Schema):
    ok: int
    timeout: int
    rate_limited: int
    quota_exhausted: int
    auth: int
    server_error: int
    other: int
    total: int


class LlmStatsOut(Schema):
    calls: LlmCallsOut
    latency_p50_seconds: float | None
    latency_p95_seconds: float | None
    input_tokens: int
    output_tokens: int
    queue_wait_p95_seconds: float | None
    in_flight_max: int


class LlmBucketOut(LlmStatsOut):
    start: datetime


class LlmMetricsOut(Schema):
    totals: LlmStatsOut
    buckets: list[LlmBucketOut]


class StatusCountOut(Schema):
    status: int
    count: int


class RequestStatsOut(Schema):
    requests: int
    per_second: float
    statuses: list[StatusCountOut]
    server_errors: int
    #: 5xx ÷ 전체 — 요청이 없으면 null.
    server_error_ratio: float | None
    latency_p50_seconds: float | None
    latency_p95_seconds: float | None


class RequestBucketOut(RequestStatsOut):
    start: datetime


class TopRouteOut(Schema):
    method: str
    route: str
    requests: int
    latency_p95_seconds: float | None


class RequestMetricsOut(Schema):
    totals: RequestStatsOut
    buckets: list[RequestBucketOut]
    #: 기간 합계에서 요청 수가 많은 (메서드 · 패턴) 10개.
    top_routes: list[TopRouteOut]


class OpsAlertOut(Schema):
    #: 규칙 이름, 예 `LLMTimeoutRatioHigh`.
    rule: str
    #: 울리기 시작한 시각.
    since: datetime
    #: 마지막 검사의 값과 기준 — 단위까지 붙은 문자열.
    value: str
    threshold: str


class OpsMetricsOut(Schema):
    range: RangeKey
    start: datetime
    end: datetime
    bucket_seconds: int
    llm: LlmMetricsOut
    requests: RequestMetricsOut
    #: 지금 울리는 경보 — 오래 울린 것부터.
    alerts: list[OpsAlertOut]


@ops_metrics_operator_router.get("/ops-metrics", response=OpsMetricsOut)
def ops_metrics(request, range_key: RangeKey = Query("1h", alias="range")):
    """기간의 LLM 채점 지표(결과별 호출 수·지연 p50/p95·토큰·큐 대기 p95·동시 채점 최댓값)와 백엔드 요청 지표
    (초당 요청·상태코드별 수·5xx 비율·지연 p50/p95·경로별 상위 10), 그리고 지금 울리는 경보."""

    alerts = [
        {"rule": a.rule, "since": a.started_at, "value": a.value, "threshold": a.threshold} for a in firing()
    ]
    return {**summarize(range_key, now=Clock.now()), "alerts": alerts}
