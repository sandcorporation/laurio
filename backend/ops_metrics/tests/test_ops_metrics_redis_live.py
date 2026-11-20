"""`ops_metrics.store.RedisMinuteStore` 가 실제 Redis 에서 흉내 저장소와 같은 뜻을 내는지 본다(#827).

`OPS_METRICS_REDIS_URL` 이 있을 때만 돈다(dev 스택의 redis 를 가리키는 값, 예: `redis://127.0.0.1:16379/3`)
— 없으면 skip(`tests/live.py`). `@live_infra` 라 기본 스위트·CI 에서 빠진다. 키는 시험마다 고유한 접두어를
쓰고 끝나면 지운다 — 같은 인덱스를 다른 체크아웃의 dev 서버가 쓰고 있을 수 있다.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from tests.live import live_infra, require_live_credential


@pytest.fixture
def redis_store():
    from ops_metrics.store import RedisMinuteStore

    store = RedisMinuteStore(require_live_credential("OPS_METRICS_REDIS_URL"))
    prefix = f"ops:livetest-{uuid.uuid4().hex[:8]}:"
    yield store, prefix
    client = store._client()
    for key in store.keys(prefix):
        client.delete(key)


@live_infra
def test_add_take_and_max_behave_like_the_memory_store(redis_store):
    store, prefix = redis_store
    key = f"{prefix}100"

    store.add(key, {"a|n": 2, "a|ms": 30}, {"a|max_inflight": 3}, 60)

    async def more() -> None:
        await store.add_async(key, {"a|n": 1}, {"a|max_inflight": 2}, 60)

    asyncio.run(more())

    assert store.keys(prefix) == [key]
    assert 0 < store._client().ttl(key) <= 60
    assert store.read(key) == {"a|n": 3, "a|ms": 30, "a|max_inflight": 3}
    assert store.take(key) == {"a|n": 3, "a|ms": 30, "a|max_inflight": 3}
    assert store.take(key) == {}
    assert store.read(key) == {}


@live_infra
def test_values_carry_a_ttl(redis_store):
    store, prefix = redis_store

    store.set_value(f"{prefix}beat", "123", 30)

    assert store.get_value(f"{prefix}beat") == "123"
    assert 0 < store._client().ttl(f"{prefix}beat") <= 30
