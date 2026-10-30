"""운영 지표 1분 집계(#827) — 기록 → 분 해시 → flush → DB 행 → 운영자 API.

저장소는 시험에서 프로세스 안 흉내(`ops_metrics.store.MemoryMinuteStore`)다 — 같은 Redis 를 여러 체크아웃이
나눠 쓰기 때문이다(세션 캐시와 같은 이유). 실물 Redis 의 같은 동작은 `test_ops_metrics_redis_live.py` 가 본다.
호출 기록은 실제 채점 경로(강의실 즉시 채점 HTTP, 비동기 어댑터, grader)로 만든다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.core.management import call_command
from django.test import Client

from classroom import grader as classroom_grader
from core.llm_metrics import DURATION_BOUNDS, QUEUE_WAIT_BOUNDS, RESULTS
from core.llm_scoring import OpenAIScoringAdapter
from core.models import ClockOverride
from core.safe_outbound import AsyncResponse
from ops_metrics import recorder
from ops_metrics.flush import flush_closed_minutes, purge_old_minutes
from ops_metrics.models import LlmMinute, LlmQueueMinute
from ops_metrics.quantile import histogram_quantile
from ops_metrics.store import memory_store
from tests.classroom_scenarios import auth_header, force_real_scoring_adapter, login, openai_verdicts_body, respond_with_verdict
from tests.test_classroom_grader import _class_with_open_problem, _submit, _submit_queued
from tests.test_llm_metrics import INPUT, VERDICTS

OPS_URL = "/api/operator/ops-metrics"
OPERATOR_ORIGIN = "http://testserver"
#: 시험이 쓰는 고정 분 — 2026-10-30 03:00 UTC.
T0 = int(datetime(2026, 10, 30, 3, 0, tzinfo=dt_timezone.utc).timestamp())


@pytest.fixture(autouse=True)
def store():
    memory_store().clear()
    recorder._failing = False
    yield memory_store()
    memory_store().clear()


def _respond(status: int, body):
    async def transport(method, url, *, headers, timeout, json=None):
        return AsyncResponse(status, __import__("json").dumps(body).encode())

    return transport


def _fields(store, kind: str) -> dict[str, int]:
    merged: dict[str, int] = {}
    for key, values in store.hashes.items():
        if key.startswith(f"ops:{kind}:"):
            for field, value in values.items():
                merged[field] = merged.get(field, 0) + value
    return merged


def _operator_client() -> Client:
    call_command("create_operator", "ops-operator", password="operator-pw-9134-xyz")
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": "ops-operator", "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _freeze(epoch: int) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": datetime.fromtimestamp(epoch, tz=dt_timezone.utc)})


# --- 기록 -------------------------------------------------------------------------------


def test_a_classroom_call_lands_in_the_minute_hash_with_closed_labels_only(
    client, db, monkeypatch, django_capture_on_commit_callbacks, store
):
    ctx = _class_with_open_problem(client)
    respond_with_verdict(monkeypatch, ctx["problem"].item_id, total_tokens=0)

    with force_real_scoring_adapter(), django_capture_on_commit_callbacks(execute=True):
        _submit(client, ctx)

    fields = _fields(store, "llm")
    labels = {tuple(field.split("|")[:3]) for field in fields}
    assert len(labels) == 1
    product, _model, result = labels.pop()
    assert (product, result) == ("classroom", "ok")
    metrics = {field.split("|")[3] for field in fields}
    assert metrics <= {"n", "ms", "in", "out"} | {f"b{i}" for i in range(len(DURATION_BOUNDS) + 1)}
    # 클래스·제출·강사 번호가 키에도 필드에도 없다.
    ids = {str(ctx["class_id"]), str(ctx["problem"].id)}
    for key, values in store.hashes.items():
        for part in [key, *values]:
            assert not ids & set(part.replace(":", "|").split("|"))


def test_sync_and_async_calls_add_into_the_same_minute_hash(store):
    recorder.record_llm_call(product="contest", model="gpt-4o-mini", result="ok", seconds=1.5, input_tokens=10, at=T0 + 5)
    asyncio.run(
        recorder.record_llm_call_async(product="contest", model="gpt-4o-mini", result="ok", seconds=3, output_tokens=7, at=T0 + 50)
    )

    assert list(store.hashes) == [f"ops:llm:{T0}"]
    row = store.hashes[f"ops:llm:{T0}"]
    assert row["contest|gpt-4o-mini|ok|n"] == 2
    assert row["contest|gpt-4o-mini|ok|ms"] == 4500
    assert row["contest|gpt-4o-mini|ok|in"] == 10
    assert row["contest|gpt-4o-mini|ok|out"] == 7
    assert row["contest|gpt-4o-mini|ok|b2"] == 1  # 1.5초 → 경계 2 이하
    assert row["contest|gpt-4o-mini|ok|b3"] == 1  # 3초 → 경계 5 이하


def test_the_async_adapter_path_records_through_the_real_adapter(store):
    adapter = OpenAIScoringAdapter(api_key="sk-x", model="gpt-4o-mini", async_transport=_respond(200, openai_verdicts_body(VERDICTS)))

    asyncio.run(adapter.score_async(INPUT))

    fields = _fields(store, "llm")
    assert fields["contest|gpt-4o-mini|ok|n"] == 1
    assert _fields(store, "llmq")["contest|max_inflight"] == 1


def test_a_redis_failure_does_not_stop_scoring_and_warns_once(
    client, db, monkeypatch, django_capture_on_commit_callbacks, store, caplog
):
    store.fail = True
    ctx = _class_with_open_problem(client)
    respond_with_verdict(monkeypatch, ctx["problem"].item_id)

    with caplog.at_level(logging.WARNING, logger="codemit.ops_metrics"):
        with force_real_scoring_adapter(), django_capture_on_commit_callbacks(execute=True):
            _submit(client, ctx)
        recorder.record_llm_call(product="contest", model="m", result="ok", seconds=1)
        asyncio.run(recorder.record_queue_wait_async(product="classroom", seconds=2))

    from classroom.models import ClassroomScore

    assert ClassroomScore.objects.count() == 1
    warnings = [r for r in caplog.records if r.name == "codemit.ops_metrics"]
    assert len(warnings) == 1


@pytest.mark.django_db(transaction=True)
def test_the_grader_records_queue_wait_and_a_heartbeat(settings, store):
    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    ctx = _class_with_open_problem(client)
    _submit_queued(client, ctx)

    async def main() -> None:
        stop = asyncio.Event()
        grader = classroom_grader.Grader(global_limit=1, per_connection_limit=1, poll_seconds=0.01)
        running = asyncio.create_task(grader.run_forever(stop))
        for _ in range(200):
            if _fields(store, "llmq").get("classroom|n"):
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(running, timeout=5)

    asyncio.run(main())

    queue = _fields(store, "llmq")
    assert queue["classroom|n"] == 1
    assert "classroom|max_inflight" in queue
    beat = recorder.last_beat("grader")
    assert beat is not None and abs(beat - time.time()) < 10
    assert store.ttls["ops:heartbeat:grader"] == settings.OPS_METRICS_HEARTBEAT_TTL_SECONDS


# --- flush ------------------------------------------------------------------------------


def _record_minute(at: int, *, calls: int = 1, result: str = "ok", seconds: float = 1.5) -> None:
    for _ in range(calls):
        recorder.record_llm_call(product="classroom", model="gpt-4o-mini", result=result, seconds=seconds, input_tokens=3, at=at)


def test_flush_moves_only_closed_minutes(db, store):
    _record_minute(T0)
    _record_minute(T0 + 60)

    moved = flush_closed_minutes(now=T0 + 61)

    assert moved["llm"] == 1
    assert list(LlmMinute.objects.values_list("calls", flat=True)) == [1]
    assert f"ops:llm:{T0 + 60}" in store.hashes


def test_flushing_twice_is_the_same_as_once_and_late_writes_add_up(db, store):
    _record_minute(T0, calls=2)
    asyncio.run(recorder.record_queue_wait_async(product="classroom", seconds=20, at=T0))
    asyncio.run(recorder.record_in_flight_async(product="classroom", count=4, at=T0))

    flush_closed_minutes(now=T0 + 120)
    flush_closed_minutes(now=T0 + 120)

    row = LlmMinute.objects.get()
    assert (row.calls, row.duration_sum_ms, row.input_tokens) == (2, 3000, 6)
    assert row.duration_buckets[2] == 2 and sum(row.duration_buckets) == 2
    queue = LlmQueueMinute.objects.get()
    assert (queue.waits, queue.in_flight_max, queue.wait_buckets[3]) == (1, 4, 1)

    # 닫힌 뒤에 늦게 닿은 기록은 같은 행에 더해진다. 최댓값은 더하지 않는다.
    _record_minute(T0)
    asyncio.run(recorder.record_in_flight_async(product="classroom", count=2, at=T0))
    flush_closed_minutes(now=T0 + 120)

    assert LlmMinute.objects.get().calls == 3
    assert LlmQueueMinute.objects.get().in_flight_max == 4


def test_a_failed_db_write_puts_the_values_back(db, store, monkeypatch):
    from ops_metrics import flush

    _record_minute(T0, calls=2)

    def broken(minute, values):
        raise RuntimeError("db down")

    monkeypatch.setitem(flush.KINDS, "llm", broken)
    flush_closed_minutes(now=T0 + 120)
    assert store.hashes[f"ops:llm:{T0}"]["classroom|gpt-4o-mini|ok|n"] == 2

    monkeypatch.undo()
    flush_closed_minutes(now=T0 + 120)
    assert LlmMinute.objects.get().calls == 2


def test_purge_removes_only_rows_older_than_90_days(db, store):
    now = datetime.fromtimestamp(T0, tz=dt_timezone.utc)
    old = T0 - 91 * 86400
    kept = T0 - 89 * 86400
    _record_minute(old)
    _record_minute(kept)
    asyncio.run(recorder.record_queue_wait_async(product="classroom", seconds=1, at=old))
    flush_closed_minutes(now=T0)

    deleted = purge_old_minutes(now=now)

    assert deleted == 2
    assert [m.timestamp() for m in LlmMinute.objects.values_list("minute", flat=True)] == [kept]
    assert not LlmQueueMinute.objects.exists()


def test_the_beat_schedule_runs_flush_every_minute_and_purge_daily():
    from config.celery import SCHEDULED_JOBS

    assert SCHEDULED_JOBS["ops-metrics:flush"]["task"] == "ops_metrics.flush_minutes"
    assert SCHEDULED_JOBS["ops-metrics:flush"]["schedule"].minute == set(range(60))
    assert SCHEDULED_JOBS["ops-metrics:purge"]["task"] == "ops_metrics.purge_old_minutes"


# --- 분위수 -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "counts", "expected"),
    [
        (0.5, [1, 1, 2, 0], 2.0),  # 순위 2 → 둘째 칸(1~2] 끝
        (0.95, [1, 1, 2, 0], 4.7),  # 순위 3.8 → 셋째 칸(2~5] 의 0.9
        (0.5, [4, 0, 0, 0], 0.5),  # 첫 칸은 0 에서 보간한다
        (0.95, [0, 0, 0, 3], 5.0),  # +Inf 칸은 가장 큰 유한 경계
        (0.5, [0, 0, 0, 0], None),
    ],
)
def test_quantiles_interpolate_like_prometheus(q, counts, expected):
    value = histogram_quantile(q, (1, 2, 5), counts)
    assert value == pytest.approx(expected) if expected is not None else value is None


# --- 운영자 API -------------------------------------------------------------------------


def test_only_operators_read_ops_metrics(client, db):
    participant = login(client, uid="participant-ops")

    assert Client().get(OPS_URL).status_code in (401, 403)
    assert client.get(OPS_URL, **auth_header(participant["access"])).status_code in (401, 403)
    assert _operator_client().get(OPS_URL).status_code == 200


def test_the_api_sums_closed_minutes_into_totals_and_buckets(db, store, django_assert_max_num_queries):
    operator = _operator_client()
    _record_minute(T0 - 120, calls=3, seconds=1.5)
    _record_minute(T0 - 120, result="timeout", seconds=200)
    _record_minute(T0 - 60, result="rate_limited", seconds=0.2)
    asyncio.run(recorder.record_queue_wait_async(product="classroom", seconds=20, at=T0 - 120))
    asyncio.run(recorder.record_in_flight_async(product="classroom", count=5, at=T0 - 60))
    _record_minute(T0 - 2 * 3600)  # 1시간 밖
    flush_closed_minutes(now=T0)
    _freeze(T0 + 30)

    with django_assert_max_num_queries(12):
        body = operator.get(OPS_URL, {"range": "1h"}).json()

    assert body["range"] == "1h" and body["bucket_seconds"] == 60
    assert body["end"].startswith("2026-10-30T03:00:00")
    totals = body["llm"]["totals"]
    assert totals["calls"] == {
        **{result: 0 for result in RESULTS},
        "ok": 3,
        "timeout": 1,
        "rate_limited": 1,
        "total": 5,
    }
    assert totals["input_tokens"] == 15
    assert totals["latency_p50_seconds"] == pytest.approx(1 + (2.5 - 1) / 3)
    assert totals["latency_p95_seconds"] == pytest.approx(180 + 60 * (4.75 - 4))
    assert totals["queue_wait_p95_seconds"] == pytest.approx(15 + 15 * 0.95)
    assert totals["in_flight_max"] == 5

    buckets = body["llm"]["buckets"]
    assert len(buckets) == 60
    assert buckets[-2]["calls"]["total"] == 4 and buckets[-1]["calls"]["rate_limited"] == 1
    assert buckets[0]["calls"]["total"] == 0 and buckets[0]["latency_p95_seconds"] is None


@pytest.mark.parametrize(("range_key", "bucket_seconds", "count"), [("24h", 900, 96), ("7d", 3600, 168)])
def test_longer_ranges_use_wider_buckets(db, range_key, bucket_seconds, count):
    operator = _operator_client()
    _record_minute(T0 - 60)
    flush_closed_minutes(now=T0)
    _freeze(T0)

    body = operator.get(OPS_URL, {"range": range_key}).json()

    assert body["bucket_seconds"] == bucket_seconds
    assert len(body["llm"]["buckets"]) == count
    assert body["llm"]["buckets"][-1]["calls"]["ok"] == 1


def test_an_unknown_range_is_rejected(db):
    assert _operator_client().get(OPS_URL, {"range": "30d"}).status_code == 422


def test_the_recorded_label_names_are_pinned():
    fields = recorder.llm_call_fields(product="classroom", model="m", result="ok", seconds=1, input_tokens=1, output_tokens=1)
    assert {f.count("|") for f in fields} == {3}
    assert set(recorder.queue_wait_fields(product="classroom", seconds=1)) == {"classroom|n", "classroom|ms", "classroom|b0"}
    assert len(QUEUE_WAIT_BOUNDS) + 1 == 11
    assert json.dumps(sorted(f.rsplit("|", 1)[1] for f in fields)) == '["b1", "in", "ms", "n", "out"]'
