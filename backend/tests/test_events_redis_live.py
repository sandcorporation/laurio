"""`core.events_redis.RedisEventBus`가 실제 Redis를 치는 live 테스트 (#456,
ADR-0046).

`EVENT_BUS_REDIS_URL`이 있을 때만 돈다(dev 스택의 redis 컨테이너를 가리키는
값, 예: `redis://127.0.0.1:16679/2` — `docker compose -f
docker/compose.dev.yaml up -d redis`) — 없으면 `tests/live.py`의 원칙대로
skip이지 실패가 아니다. `@live_vendor`라 기본 스위트·CI에서 제외된다(#453
Testing Decisions).

스펙 #453이 요구하는 세 가지만 본다:
1. 발행한 신호가 구독자에게 오는가.
2. 구독을 닫으면 정리되는가(닫힌 뒤에는 그 pubsub으로 더 폴링할 수 없다).
3. 동시에 여럿을 구독해도 서로 섞이지 않는가.

**폴링 한 번은 구독 확인(subscribe ack) 자체를 받을 수도 있다** — Redis는
SUBSCRIBE에 대한 확인 메시지를 채널의 첫 메시지로 돌려주는데,
`ignore_subscribe_messages=True`인 `get_message()`는 그 확인 메시지 하나를
소비하면 (설령 그것이 subscribe ack라도) 그 호출에서는 빈 결과를 돌려주고
돌아온다 — 다음 호출이 실제 메시지를 받는다. 이건 이 테스트가 만든 성질이
아니라 redis-py의 sync·async 클라이언트 둘 다에 있는 기존 성질이고,
`classroom.api._stream_events_for`의 반복 폴링 루프가 원래 자연스럽게
흡수한다(빈 결과 → keep-alive 한 번 → 다음 poll). 그래서 이 테스트는 최대
두 번까지 폴링해 실제 메시지를 찾는다.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.live import live_vendor, require_live_credential


@pytest.fixture
def redis_url():
    return require_live_credential("EVENT_BUS_REDIS_URL")


@pytest.fixture
def bus(redis_url, settings):
    from core.events_redis import RedisEventBus

    settings.EVENT_BUS_REDIS_URL = redis_url
    return RedisEventBus()


async def _poll_past_subscribe_ack(subscription, *, timeout: float, attempts: int = 2) -> list:
    for _ in range(attempts):
        events = await subscription.poll(timeout=timeout)
        if events:
            return events
    return []


@live_vendor
def test_published_event_reaches_the_subscriber(bus):
    from core.events import Event

    async def scenario():
        async with bus.subscribe(90001) as subscription:
            bus.publish(Event(kind="attempt-scored", recipient_id=90001, payload={"submission_id": 1}))
            return await _poll_past_subscribe_ack(subscription, timeout=5.0)

    events = asyncio.run(scenario())
    assert len(events) == 1
    assert events[0].kind == "attempt-scored"
    assert events[0].recipient_id == 90001
    assert events[0].payload == {"submission_id": 1}


@live_vendor
def test_closing_the_subscription_cleans_it_up(bus):
    async def scenario():
        subscription = bus.subscribe(90002)
        async with subscription:
            pass
        # 정리됐다는 것은 이 pubsub으로 더 이상 폴링할 수 없다는 뜻이다
        # (AC "연결을 닫으면 구독이 정리된다") — `__aexit__`가
        # unsubscribe·close 하지 않았다면 이 호출은 조용히 계속 동작했을
        # 것이다.
        with pytest.raises(Exception):
            await subscription.poll(timeout=1.0)

    asyncio.run(scenario())


@live_vendor
def test_concurrent_subscribers_do_not_cross_contaminate(bus):
    from core.events import Event

    async def scenario():
        async with bus.subscribe(90003) as sub_a, bus.subscribe(90004) as sub_b:
            bus.publish(Event(kind="attempt-scored", recipient_id=90003, payload={"submission_id": 10}))
            bus.publish(Event(kind="notice-created", recipient_id=90004, payload={"notice_id": 20}))
            events_a = await _poll_past_subscribe_ack(sub_a, timeout=5.0)
            events_b = await _poll_past_subscribe_ack(sub_b, timeout=5.0)
            return events_a, events_b

    events_a, events_b = asyncio.run(scenario())
    assert [e.payload for e in events_a] == [{"submission_id": 10}]
    assert [e.payload for e in events_b] == [{"notice_id": 20}]
