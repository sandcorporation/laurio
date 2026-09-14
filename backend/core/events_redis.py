"""`core.events.EventBus`의 실물 구현 — Redis pub/sub (ADR-0046).

dotted path로만 임포트된다(`EVENT_BUS_ADAPTER_MODE`) — dev·pytest 기본값은
fake라 이 모듈은 실제로 Redis에 붙는 경로(dev compose가 백엔드·이벤트
서비스 컨테이너에 이 값을 줄 때, 또는 배포 환경)에서만 로드된다. `redis`
패키지는 `celery[redis]`가 이미 끌어온다(pyproject.toml) — 새 의존성이
아니다.
"""

from __future__ import annotations

import json

import redis
from django.conf import settings

from .events import Event

_CHANNEL_PREFIX = "codemit-events:"


def _channel(recipient_id: int) -> str:
    return f"{_CHANNEL_PREFIX}{recipient_id}"


class RedisSubscription:
    """`pubsub.subscribe()`를 구독 하나의 수명 동안 딱 한 번만 부른다 —
    poll마다 다시 구독하면 그 사이에 온 메시지를 놓친다(pub/sub은 구독
    중인 리스너에게만 전달한다)."""

    def __init__(self, client: "redis.Redis", recipient_id: int) -> None:
        self._pubsub = client.pubsub()
        self._pubsub.subscribe(_channel(recipient_id))

    def poll(self, *, timeout: float) -> list[Event]:
        message = self._pubsub.get_message(timeout=timeout, ignore_subscribe_messages=True)
        if message is None or message.get("type") != "message":
            return []
        data = json.loads(message["data"])
        return [Event(kind=data["kind"], recipient_id=data["recipient_id"], payload=data["payload"])]

    def __enter__(self) -> "RedisSubscription":
        return self

    def __exit__(self, *exc_info) -> None:
        # AC "연결을 닫으면 구독이 정리된다" — unsubscribe 없이 close()만 해도
        # 커넥션이 끊기지만, 명시적으로 구독을 풀어야 close() 도중 서버에
        # 남은 미확인 상태가 없다.
        self._pubsub.unsubscribe()
        self._pubsub.close()


class RedisEventBus:
    def __init__(self) -> None:
        self._client = redis.Redis.from_url(settings.EVENT_BUS_REDIS_URL)

    def publish(self, event: Event) -> None:
        self._client.publish(
            _channel(event.recipient_id),
            json.dumps({"kind": event.kind, "recipient_id": event.recipient_id, "payload": event.payload}),
        )

    def subscribe(self, recipient_id: int) -> RedisSubscription:
        return RedisSubscription(self._client, recipient_id)
