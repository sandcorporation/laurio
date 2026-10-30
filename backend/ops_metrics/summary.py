"""집계 행을 기간 합계와 시간대 버킷으로 접는다(#827) — 운영자 API 가 이것을 그대로 낸다.

**기간.** 끝은 지금 분의 시작(그 분은 아직 flush 되지 않았다)이고 시작은 끝 − 길이다. 버킷은 UTC 기준
버킷 길이의 배수에 맞춘다(1h=1분 · 24h=15분 · 7d=1시간) — 첫 버킷은 시작을 품은 칸에서 시작한다. 행이 없는
칸도 0 으로 온다(차트가 빈 칸을 메우지 않아도 된다).

**쿼리는 종류마다 하나다** — LLM 은 기간 안의 행을 한 번에 읽어 파이썬에서 접는다. 7일이 1만 분이고 분마다 행이
몇 개라 메모리에 넉넉하다.

**요청 지표(#828)는 DB 가 접는다** — 분마다 메서드·패턴·상태코드 묶음이 수십 행이라 7일이면 수십만 행이다.
쿼리 둘: (시간대 버킷 × 상태코드)로 묶은 수와 지연 칸 합(`date_bin`, 지연 칸은 JSON 배열의 i 번째를 더한다),
그리고 (메서드 × 패턴)으로 묶어 수가 많은 순 10개. 초당 요청은 수 ÷ 그 칸의 길이(합계는 기간 길이)다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db.models import BigIntegerField, DateTimeField, F, Func, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from core.llm_metrics import DURATION_BOUNDS, QUEUE_WAIT_BOUNDS, RESULTS
from core.metrics import DURATION_BOUNDS as REQUEST_DURATION_BOUNDS

from .models import LlmMinute, LlmQueueMinute, RequestMinute
from .quantile import add_counts, histogram_quantile

#: 기간 이름 → (길이, 버킷 길이 초).
RANGES: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 60),
    "24h": (timedelta(hours=24), 15 * 60),
    "7d": (timedelta(days=7), 3600),
}


@dataclass
class _LlmAcc:
    calls: dict[str, int] = field(default_factory=lambda: {result: 0 for result in RESULTS})
    duration: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    queue: list[int] = field(default_factory=list)
    in_flight_max: int = 0

    def add_llm(self, row: LlmMinute) -> None:
        if row.result in self.calls:
            self.calls[row.result] += row.calls
        else:
            self.calls["other"] += row.calls
        self.duration = add_counts(self.duration, row.duration_buckets)
        self.input_tokens += row.input_tokens
        self.output_tokens += row.output_tokens

    def add_queue(self, row: LlmQueueMinute) -> None:
        self.queue = add_counts(self.queue, row.wait_buckets)
        self.in_flight_max = max(self.in_flight_max, row.in_flight_max)

    def out(self) -> dict:
        return {
            "calls": {**self.calls, "total": sum(self.calls.values())},
            "latency_p50_seconds": histogram_quantile(0.5, DURATION_BOUNDS, self.duration),
            "latency_p95_seconds": histogram_quantile(0.95, DURATION_BOUNDS, self.duration),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "queue_wait_p95_seconds": histogram_quantile(0.95, QUEUE_WAIT_BOUNDS, self.queue),
            "in_flight_max": self.in_flight_max,
        }


#: 경로별 상위 몇 개를 내나.
TOP_ROUTES = 10
_EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)


class _DateBin(Func):
    function = "date_bin"
    output_field = DateTimeField()


def _duration_sums() -> dict:
    return {
        f"b{i}": Sum(Cast(KeyTextTransform(str(i), "duration_buckets"), BigIntegerField()))
        for i in range(len(REQUEST_DURATION_BOUNDS) + 1)
    }


def _counts(row: dict) -> list[int]:
    return [int(row.get(f"b{i}") or 0) for i in range(len(REQUEST_DURATION_BOUNDS) + 1)]


@dataclass
class _RequestAcc:
    seconds: int
    statuses: dict[int, int] = field(default_factory=dict)
    duration: list[int] = field(default_factory=list)

    def add(self, status: int, requests: int, counts: list[int]) -> None:
        self.statuses[status] = self.statuses.get(status, 0) + requests
        self.duration = add_counts(self.duration, counts)

    def out(self) -> dict:
        total = sum(self.statuses.values())
        server_errors = sum(n for status, n in self.statuses.items() if 500 <= status <= 599)
        return {
            "requests": total,
            "per_second": total / self.seconds if self.seconds else 0.0,
            "statuses": [{"status": status, "count": n} for status, n in sorted(self.statuses.items())],
            "server_errors": server_errors,
            "server_error_ratio": server_errors / total if total else None,
            "latency_p50_seconds": histogram_quantile(0.5, REQUEST_DURATION_BOUNDS, self.duration),
            "latency_p95_seconds": histogram_quantile(0.95, REQUEST_DURATION_BOUNDS, self.duration),
        }


def _requests(start: datetime, end: datetime, bucket_seconds: int, starts: list[datetime]) -> dict:
    rows = RequestMinute.objects.filter(minute__gte=start, minute__lt=end)
    step = timedelta(seconds=bucket_seconds)
    buckets = {s: _RequestAcc(bucket_seconds) for s in starts}
    totals = _RequestAcc(int((end - start).total_seconds()))
    by_bucket = (
        rows.annotate(bucket=_DateBin(Value(step), F("minute"), Value(_EPOCH)))
        .values("bucket", "status")
        .annotate(n=Sum("requests"), **_duration_sums())
        .order_by()
    )
    for row in by_bucket:
        counts = _counts(row)
        totals.add(row["status"], row["n"], counts)
        buckets[_bucket_start(row["bucket"], bucket_seconds)].add(row["status"], row["n"], counts)
    top = (
        rows.values("method", "route")
        .annotate(n=Sum("requests"), **_duration_sums())
        .order_by("-n", "method", "route")[:TOP_ROUTES]
    )
    return {
        "totals": totals.out(),
        "buckets": [{"start": s, **buckets[s].out()} for s in starts],
        "top_routes": [
            {
                "method": row["method"],
                "route": row["route"],
                "requests": row["n"],
                "latency_p95_seconds": histogram_quantile(0.95, REQUEST_DURATION_BOUNDS, _counts(row)),
            }
            for row in top
        ],
    }


def window(range_key: str, now: datetime) -> tuple[datetime, datetime, int]:
    length, bucket_seconds = RANGES[range_key]
    end = now.replace(second=0, microsecond=0)
    return end - length, end, bucket_seconds


def _bucket_start(at: datetime, bucket_seconds: int) -> datetime:
    epoch = int(at.timestamp())
    return datetime.fromtimestamp(epoch - epoch % bucket_seconds, tz=at.tzinfo)


def summarize(range_key: str, *, now: datetime) -> dict:
    start, end, bucket_seconds = window(range_key, now)
    step = timedelta(seconds=bucket_seconds)
    starts: list[datetime] = []
    cursor = _bucket_start(start, bucket_seconds)
    while cursor < end:
        starts.append(cursor)
        cursor += step
    buckets = {s: _LlmAcc() for s in starts}
    totals = _LlmAcc()

    for row in LlmMinute.objects.filter(minute__gte=start, minute__lt=end):
        totals.add_llm(row)
        buckets[_bucket_start(row.minute, bucket_seconds)].add_llm(row)
    for row in LlmQueueMinute.objects.filter(minute__gte=start, minute__lt=end):
        totals.add_queue(row)
        buckets[_bucket_start(row.minute, bucket_seconds)].add_queue(row)

    return {
        "range": range_key,
        "start": start,
        "end": end,
        "bucket_seconds": bucket_seconds,
        "llm": {
            "totals": totals.out(),
            "buckets": [{"start": s, **buckets[s].out()} for s in starts],
        },
        "requests": _requests(start, end, bucket_seconds, starts),
    }
