"""운영자 콘솔의 운영 지표(#827) — `GET /api/operator/ops-metrics?range=1h|24h|7d`.

**운영자 전원이 본다**(`OperatorAuth`, 사용 현황과 같은 등급) — 읽기 전용이고 라벨이 닫힌 집합이라 사람을
가리키는 값이 없다. 응답은 영역별(`llm`, 뒤 티켓이 `requests`·경보를 더한다)로 `totals` 와 `buckets` 를 낸다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ninja import Query, Router, Schema

from core.clock import Clock
from core.operator_auth import OperatorAuth

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


class OpsMetricsOut(Schema):
    range: RangeKey
    start: datetime
    end: datetime
    bucket_seconds: int
    llm: LlmMetricsOut


@ops_metrics_operator_router.get("/ops-metrics", response=OpsMetricsOut)
def ops_metrics(request, range_key: RangeKey = Query("1h", alias="range")):
    """기간의 LLM 채점 지표 — 결과별 호출 수·지연 p50/p95·토큰·큐 대기 p95·동시 채점 최댓값."""

    return summarize(range_key, now=Clock.now())
