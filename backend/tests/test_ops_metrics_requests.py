"""백엔드 요청 지표 1분 집계(#828) — 요청(HTTP) → 프로세스 안 버퍼 → 분 해시 → flush → DB 행 → 운영자 API.

요청은 실제 미들웨어를 지나는 HTTP 로 만든다. 저장소는 프로세스 안 흉내(`MemoryMinuteStore`)이고, 시험은
버퍼 간격이 0 이라 요청마다 바로 더한다 — 버퍼가 켜진 경로는 간격을 바꿔 따로 본다. 요청이 닿는 시각은
`request_buffer._now` 를 고정해 정한다(미들웨어는 DB 시계를 읽지 않는다).
"""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.test import Client

from core.metrics import DURATION_BOUNDS
from ops_metrics import recorder, request_buffer
from ops_metrics.flush import flush_closed_minutes, purge_old_minutes
from ops_metrics.models import RequestMinute
from ops_metrics.store import memory_store
from tests.test_ops_metrics import OPS_URL, T0, _fields, _freeze, _operator_client

JOIN_ROUTE = "api/classroom/join/<join_code>"


@pytest.fixture(autouse=True)
def store(monkeypatch):
    memory_store().clear()
    request_buffer.request_buffer().flush()
    memory_store().clear()
    recorder._failing = False
    clock = {"at": T0 + 10.0}
    monkeypatch.setattr(request_buffer, "_now", lambda: clock["at"])
    yield memory_store(), clock
    request_buffer.request_buffer().flush()
    memory_store().clear()


def _req_fields(store) -> dict[str, int]:
    return _fields(store, "req")


def _visit(client: Client, clock: dict, at: float, path: str, n: int = 1) -> None:
    clock["at"] = at
    for _ in range(n):
        client.get(path)


# --- 기록 -------------------------------------------------------------------------------


def test_a_request_is_counted_under_its_url_pattern_not_its_path(client, db, store):
    mem, _ = store

    response = client.get("/api/classroom/join/NOPE-1234")

    assert response.status_code == 404
    fields = _req_fields(mem)
    assert fields[f"GET|{JOIN_ROUTE}|404|n"] == 1
    assert not any("NOPE-1234" in field for field in fields)
    assert {field.rsplit("|", 1)[1] for field in fields} <= {"n", "ms"} | {f"b{i}" for i in range(len(DURATION_BOUNDS) + 1)}


def test_an_unknown_path_is_unmatched_and_metrics_itself_is_not_counted(client, db, store):
    mem, _ = store

    client.get("/no/such/place/17")
    client.get("/metrics", HTTP_HOST="backend")

    fields = _req_fields(mem)
    assert fields["GET|unmatched|404|n"] == 1
    assert {field.split("|")[1] for field in fields} == {"unmatched"}


def test_a_redis_failure_leaves_the_response_unchanged_and_warns_once(client, db, store, caplog):
    mem, _ = store
    expected = client.get("/api/classroom/join/NOPE-1234")
    mem.fail = True

    with caplog.at_level(logging.WARNING, logger="codemit.ops_metrics"):
        responses = [client.get("/api/classroom/join/NOPE-1234") for _ in range(3)]

    assert {(r.status_code, r.content) for r in responses} == {(expected.status_code, expected.content)}
    assert len([r for r in caplog.records if r.name == "codemit.ops_metrics"]) == 1


def test_the_buffered_path_sends_one_batch_per_minute_and_drops_it_when_redis_is_down(client, db, store, settings):
    mem, clock = store
    settings.OPS_METRICS_REQUEST_FLUSH_SECONDS = 5

    _visit(client, clock, T0 + 1, "/no/such/place", n=3)
    _visit(client, clock, T0 + 61, "/no/such/place")

    assert _req_fields(mem) == {}  # 요청 경로는 저장소에 닿지 않는다
    request_buffer.flush_requests()
    assert mem.hashes[f"ops:req:{T0}"]["GET|unmatched|404|n"] == 3
    assert mem.hashes[f"ops:req:{T0 + 60}"]["GET|unmatched|404|n"] == 1

    mem.fail = True
    _visit(client, clock, T0 + 62, "/no/such/place")
    request_buffer.flush_requests()
    mem.fail = False
    request_buffer.flush_requests()
    assert mem.hashes[f"ops:req:{T0 + 60}"]["GET|unmatched|404|n"] == 1  # 실패한 묶음은 버렸다
    assert request_buffer.request_buffer().pending() == {}


def test_unknown_methods_share_one_label():
    fields = request_buffer.request_fields(method="BREW", route="api/x", status=418, seconds=0.03)
    assert set(fields) == {"OTHER|api/x|418|n", "OTHER|api/x|418|ms", "OTHER|api/x|418|b2"}


# --- flush ------------------------------------------------------------------------------


def test_flush_moves_closed_request_minutes_and_late_writes_add_up(client, db, store):
    mem, clock = store
    _visit(client, clock, T0 + 5, "/no/such/place", n=2)

    flush_closed_minutes(now=T0 + 61)
    _visit(client, clock, T0 + 59, "/no/such/place")  # 분이 닫힌 뒤 늦게 닿았다
    flush_closed_minutes(now=T0 + 62)

    row = RequestMinute.objects.get()
    assert (row.method, row.route, row.status, row.requests) == ("GET", "unmatched", 404, 3)
    assert sum(row.duration_buckets) == 3 and len(row.duration_buckets) == len(DURATION_BOUNDS) + 1
    assert f"ops:req:{T0}" not in mem.hashes


def test_purge_also_removes_old_request_rows(db):
    old = datetime.fromtimestamp(T0, tz=dt_timezone.utc)
    RequestMinute.objects.create(minute=old, method="GET", route="unmatched", status=404, requests=1)

    assert purge_old_minutes(now=datetime(2027, 3, 1, tzinfo=dt_timezone.utc)) == 1


# --- API --------------------------------------------------------------------------------


def _seed(clock: dict, calls: list[tuple[int, str, str, int, float, int]]) -> None:
    for at, method, route, status, seconds, n in calls:
        clock["at"] = at
        for _ in range(n):
            request_buffer.record_request(method=method, route=route, status=status, seconds=seconds)


def test_the_api_reports_rates_statuses_5xx_ratio_latency_and_top_routes(db, store, django_assert_max_num_queries):
    _, clock = store
    operator = _operator_client()
    routes = [(T0 - 120, "GET", f"api/r{i}", 200, 0.02, 20 - i) for i in range(12)]  # r0 20건 … r11 9건
    _seed(
        clock,
        routes
        + [
            (T0 - 120, "POST", "api/r0", 500, 3.0, 4),
            (T0 - 60, "GET", "api/r1", 503, 0.3, 1),
            (T0 - 60, "GET", "api/r1", 404, 0.004, 5),
            (T0 - 2 * 3600, "GET", "api/old", 200, 0.02, 7),  # 1시간 밖
        ]
    )
    flush_closed_minutes(now=T0)
    _freeze(T0 + 30)

    with django_assert_max_num_queries(14):
        body = operator.get(OPS_URL, {"range": "1h"}).json()

    totals = body["requests"]["totals"]
    total = sum(n for *_, n in routes) + 4 + 1 + 5
    assert totals["requests"] == total
    assert totals["per_second"] == pytest.approx(total / 3600)
    assert totals["statuses"] == [
        {"status": 200, "count": total - 10},
        {"status": 404, "count": 5},
        {"status": 500, "count": 4},
        {"status": 503, "count": 1},
    ]
    assert totals["server_errors"] == 5
    assert totals["server_error_ratio"] == pytest.approx(5 / total)
    assert totals["latency_p50_seconds"] == pytest.approx(0.01 + 0.015 * (total * 0.5 - 5) / (total - 10))

    top = body["requests"]["top_routes"]
    assert len(top) == 10
    assert [(t["method"], t["route"], t["requests"]) for t in top[:3]] == [
        ("GET", "api/r1", 25),
        ("GET", "api/r0", 20),
        ("GET", "api/r2", 18),
    ]
    assert top[0]["latency_p95_seconds"] is not None
    assert ("POST", "api/r0") not in {(t["method"], t["route"]) for t in top}  # 4건 — 10위(11건) 밖

    buckets = body["requests"]["buckets"]
    assert len(buckets) == 60
    assert buckets[-1]["requests"] == 6 and buckets[-1]["per_second"] == pytest.approx(6 / 60)
    assert buckets[-1]["server_error_ratio"] == pytest.approx(1 / 6)
    assert buckets[0]["requests"] == 0 and buckets[0]["server_error_ratio"] is None
    assert buckets[0]["latency_p95_seconds"] is None and buckets[0]["statuses"] == []


@pytest.mark.parametrize(("range_key", "count"), [("24h", 96), ("7d", 168)])
def test_wider_buckets_fold_request_minutes_in_the_database(db, store, range_key, count):
    _, clock = store
    operator = _operator_client()
    _seed(clock, [(T0 - 60, "GET", "api/x", 200, 0.02, 2), (T0 - 120, "GET", "api/x", 500, 0.02, 1)])
    flush_closed_minutes(now=T0)
    _freeze(T0)

    body = operator.get(OPS_URL, {"range": range_key}).json()["requests"]

    assert len(body["buckets"]) == count
    assert body["buckets"][-1]["requests"] == 3 and body["buckets"][-1]["server_errors"] == 1
    assert body["top_routes"] == [
        {"method": "GET", "route": "api/x", "requests": 3, "latency_p95_seconds": pytest.approx(0.01 + 0.015 * 2.85 / 3)}
    ]
