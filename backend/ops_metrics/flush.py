"""닫힌 분의 해시를 DB 행으로 옮기고(`flush_closed_minutes`), 오래된 행을 지운다(`purge_old_minutes`).

**같은 분을 두 번 옮겨도 두 배가 되지 않는 이유.** 해시를 읽고 지우는 것이 원자적(`store.take`)이라,
두 번째 flush 는 빈 손이다. DB 에는 **더한다**(upsert-add) — 분이 닫힌 뒤 늦게 닿은 기록(호출이 분 끝에서
키를 정하고 몇 ms 뒤 썼다)은 새 해시로 생겨 다음 flush 가 같은 행에 더한다. 「덮어쓰기」였다면 그 늦은
기록이 이미 옮긴 값을 지웠을 것이다. DB 쓰기가 실패하면 읽은 값을 해시에 되돌려 놓고(같은 더하기·최댓값
규칙) 다음 분에 다시 옮긴다.

닫힌 분 = 지금 분보다 앞선 분. 지금 분은 아직 쓰는 중이라 건드리지 않는다.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Callable

from django.conf import settings
from django.db import transaction

from core.llm_metrics import DURATION_BOUNDS, QUEUE_WAIT_BOUNDS

from .models import LlmMinute, LlmQueueMinute
from .quantile import add_counts
from .recorder import KEY_PREFIX, LLM, LLM_QUEUE, MAX_PREFIX, minute_key, minute_of
from .store import get_store

logger = logging.getLogger("codemit.ops_metrics")


def _buckets(metrics: dict[str, int], size: int) -> list[int]:
    counts = [0] * size
    for name, value in metrics.items():
        if name.startswith("b") and name[1:].isdigit():
            index = int(name[1:])
            if index < size:
                counts[index] += value
    return counts


def _grouped(values: dict[str, int], labels: int) -> dict[tuple, dict[str, int]]:
    groups: dict[tuple, dict[str, int]] = defaultdict(dict)
    for field, value in values.items():
        parts = field.split("|")
        if len(parts) != labels + 1:
            continue
        groups[tuple(parts[:labels])][parts[-1]] = int(value)
    return groups


def _merge_llm(minute: datetime, values: dict[str, int]) -> None:
    groups = _grouped(values, 3)
    existing = {
        (row.product, row.model, row.result): row
        for row in LlmMinute.objects.select_for_update().filter(minute=minute)
    }
    size = len(DURATION_BOUNDS) + 1
    new, changed = [], []
    for (product, model, result), metrics in groups.items():
        row = existing.get((product, model, result))
        if row is None:
            row = LlmMinute(minute=minute, product=product, model=model[:64], result=result, duration_buckets=[0] * size)
            new.append(row)
        else:
            changed.append(row)
        row.calls += metrics.get("n", 0)
        row.duration_sum_ms += metrics.get("ms", 0)
        row.input_tokens += metrics.get("in", 0)
        row.output_tokens += metrics.get("out", 0)
        row.duration_buckets = add_counts(list(row.duration_buckets), _buckets(metrics, size))
    LlmMinute.objects.bulk_create(new)
    if changed:
        LlmMinute.objects.bulk_update(
            changed, ["calls", "duration_sum_ms", "input_tokens", "output_tokens", "duration_buckets"]
        )


def _merge_llm_queue(minute: datetime, values: dict[str, int]) -> None:
    groups = _grouped(values, 1)
    existing = {row.product: row for row in LlmQueueMinute.objects.select_for_update().filter(minute=minute)}
    size = len(QUEUE_WAIT_BOUNDS) + 1
    new, changed = [], []
    for (product,), metrics in groups.items():
        row = existing.get(product)
        if row is None:
            row = LlmQueueMinute(minute=minute, product=product, wait_buckets=[0] * size)
            new.append(row)
        else:
            changed.append(row)
        row.waits += metrics.get("n", 0)
        row.wait_sum_ms += metrics.get("ms", 0)
        row.wait_buckets = add_counts(list(row.wait_buckets), _buckets(metrics, size))
        row.in_flight_max = max(row.in_flight_max, metrics.get(f"{MAX_PREFIX}inflight", 0))
    LlmQueueMinute.objects.bulk_create(new)
    if changed:
        LlmQueueMinute.objects.bulk_update(changed, ["waits", "wait_sum_ms", "wait_buckets", "in_flight_max"])


#: 해시 종류 → 그 분의 값을 DB 에 더하는 함수. 새 지표(요청 지표 등)는 여기에 한 줄을 더한다.
KINDS: dict[str, Callable[[datetime, dict[str, int]], None]] = {
    LLM: _merge_llm,
    LLM_QUEUE: _merge_llm_queue,
}

#: 보관 정리가 지우는 모델들 — 모두 `minute` 칸을 가진다.
RETAINED_MODELS = (LlmMinute, LlmQueueMinute)


def _put_back(key: str, values: dict[str, int]) -> None:
    increments = {f: v for f, v in values.items() if not f.rsplit("|", 1)[-1].startswith(MAX_PREFIX)}
    maxes = {f: v for f, v in values.items() if f not in increments}
    get_store().add(key, increments, maxes, settings.OPS_METRICS_KEY_TTL_SECONDS)


def flush_closed_minutes(*, now: float | None = None) -> dict[str, int]:
    """닫힌 분들을 옮기고 종류마다 옮긴 분의 수를 돌려준다."""

    store = get_store()
    current = minute_of(time.time() if now is None else now)
    moved: dict[str, int] = {}
    for kind, merge in KINDS.items():
        prefix = f"{KEY_PREFIX}:{kind}:"
        minutes = sorted(int(key[len(prefix):]) for key in store.keys(prefix) if key[len(prefix):].isdigit())
        moved[kind] = 0
        for minute in minutes:
            if minute >= current:
                continue
            key = minute_key(kind, minute)
            values = store.take(key)
            if not values:
                continue
            try:
                with transaction.atomic():
                    merge(datetime.fromtimestamp(minute, tz=dt_timezone.utc), values)
            except Exception:
                _put_back(key, values)
                logger.exception("운영 지표 flush 실패 — 값을 되돌려 다음 분에 다시 옮긴다: %s", key)
                continue
            moved[kind] += 1
    return moved


def purge_old_minutes(*, now: datetime) -> int:
    """보관 기간(`OPS_METRICS_RETENTION_DAYS`)보다 오래된 행을 지우고 지운 수를 돌려준다."""

    cutoff = now - timedelta(days=settings.OPS_METRICS_RETENTION_DAYS)
    deleted = 0
    for model in RETAINED_MODELS:
        count, _ = model.objects.filter(minute__lt=cutoff).delete()
        deleted += count
    return deleted
