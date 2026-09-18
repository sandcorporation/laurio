"""`core.events.EventBus`의 실물 구현 — Redis pub/sub (ADR-0046).

dotted path로만 임포트된다(`EVENT_BUS_ADAPTER_MODE`) — dev·pytest 기본값은
fake라 이 모듈은 실제로 Redis에 붙는 경로(dev compose가 백엔드·이벤트
서비스 컨테이너에 이 값을 줄 때, 또는 배포 환경)에서만 로드된다. `redis`
패키지는 `celery[redis]`가 이미 끌어온다(pyproject.toml) — 새 의존성이
아니다.

**구독은 비동기 클라이언트, 발행은 동기 클라이언트다(#456).** 폴링(구독의
`get_message`)이 스레드를 쓰지 않아야 스트림 하나가 이벤트 서비스의 스레드
풀 한 자리를 붙잡지 않는다 — 그래서 `redis.asyncio`로 구독한다. 발행하는
자리(강의실 시도·채점, 알림 벨)는 여전히 요청·태스크 안의 동기 코드이므로
그대로 동기 클라이언트(`redis.Redis`)를 쓴다 — 바꿀 이유도 근거도 없다.
"""

from __future__ import annotations

import json

import redis
import redis.asyncio as redis_asyncio
from django.conf import settings

from .events import Event

_CHANNEL_PREFIX = "codemit-events:"


def _channel(recipient_id: int) -> str:
    return f"{_CHANNEL_PREFIX}{recipient_id}"


class RedisSubscription:
    """`pubsub.subscribe()`를 구독 하나의 수명 동안 딱 한 번만 부른다 —
    poll마다 다시 구독하면 그 사이에 온 메시지를 놓친다(pub/sub은 구독
    중인 리스너에게만 전달한다). 실제 SUBSCRIBE 명령은 `__aenter__`에서
    나간다 — 생성자는 아직 아무 I/O도 하지 않는다(생성자를 동기로 남겨
    `EventBus.subscribe()` 계약을 그대로 유지하기 위해서다, #456)."""

    def __init__(self, client: "redis_asyncio.Redis", recipient_id: int) -> None:
        self._pubsub = client.pubsub()
        self._recipient_id = recipient_id

    async def poll(self, *, timeout: float) -> list[Event]:
        message = await self._pubsub.get_message(timeout=timeout, ignore_subscribe_messages=True)
        if message is None or message.get("type") != "message":
            return []
        data = json.loads(message["data"])
        return [Event(kind=data["kind"], recipient_id=data["recipient_id"], payload=data["payload"])]

    async def __aenter__(self) -> "RedisSubscription":
        await self._pubsub.subscribe(_channel(self._recipient_id))
        return self

    async def __aexit__(self, *exc_info) -> None:
        # AC "연결을 닫으면 구독이 정리된다" — unsubscribe 없이 close()만 해도
        # 커넥션이 끊기지만, 명시적으로 구독을 풀어야 close() 도중 서버에
        # 남은 미확인 상태가 없다.
        await self._pubsub.unsubscribe()
        await self._pubsub.aclose()


class RedisEventBus:
    def __init__(self) -> None:
        # 발행은 동기(요청·태스크 안), 구독의 폴링은 비동기(SSE 이벤트 루프) —
        # 계약이 서로 달라 클라이언트도 둘이다(#456).
        self._client = redis.Redis.from_url(settings.EVENT_BUS_REDIS_URL)
        self._async_client = redis_asyncio.Redis.from_url(settings.EVENT_BUS_REDIS_URL)

    def publish(self, event: Event) -> None:
        self._client.publish(
            _channel(event.recipient_id),
            json.dumps({"kind": event.kind, "recipient_id": event.recipient_id, "payload": event.payload}),
        )

    def subscribe(self, recipient_id: int) -> RedisSubscription:
        return RedisSubscription(self._async_client, recipient_id)
