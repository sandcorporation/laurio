"""분 해시를 담는 저장소 — Redis(배포·dev) 와 프로세스 안 흉내(시험) 둘이 같은 다섯 동작을 한다.

- `add(key, increments, maxes)` — 필드마다 더하고(`HINCRBY`), `maxes` 는 더 클 때만 바꾼다. 키에 TTL 을
  다시 건다. **한 번의 왕복**이다(Lua 하나 — 더하기·최댓값·TTL 이 원자적으로 함께 간다).
- `keys(prefix)` — 그 접두어의 키들(`SCAN`, 이 용도만 쓰는 DB 인덱스라 다른 키를 보지 않는다).
- `take(key)` — 읽고 지우기를 **원자적으로**(`MULTI` 안의 `HGETALL`+`DEL`). flush 가 같은 분을 두 번
  옮겨도 두 번째는 빈 손이다 — 값이 두 배가 될 수 없다.
- `set_value`/`get_value` — 생존 신호 같은 낱값(TTL 있음).

비동기 쪽(`*_async`)은 grader(asyncio) 가 쓴다 — `redis.asyncio` 클라이언트는 이벤트 루프에 묶이므로
루프마다 하나를 둔다. 실패는 여기서 삼키지 않는다 — 삼키는 것은 `recorder` 의 일이다.
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from typing import Protocol

from django.conf import settings

#: 소켓 한도(초) — Redis 가 멈춰도 채점은 이만큼만 늦는다.
SOCKET_TIMEOUT_SECONDS = 0.25

_ADD_SCRIPT = """
local n = tonumber(ARGV[2])
local i = 3
for _ = 1, n do
  redis.call('HINCRBY', KEYS[1], ARGV[i], ARGV[i + 1])
  i = i + 2
end
while i <= #ARGV do
  local current = tonumber(redis.call('HGET', KEYS[1], ARGV[i]) or '-1')
  if tonumber(ARGV[i + 1]) > current then
    redis.call('HSET', KEYS[1], ARGV[i], ARGV[i + 1])
  end
  i = i + 2
end
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""


class MinuteStore(Protocol):
    def add(self, key: str, increments: dict[str, int], maxes: dict[str, int], ttl: int) -> None: ...
    async def add_async(self, key: str, increments: dict[str, int], maxes: dict[str, int], ttl: int) -> None: ...
    def keys(self, prefix: str) -> list[str]: ...
    def take(self, key: str) -> dict[str, int]: ...
    def set_value(self, key: str, value: str, ttl: int) -> None: ...
    async def set_value_async(self, key: str, value: str, ttl: int) -> None: ...
    def get_value(self, key: str) -> str | None: ...


def _script_args(increments: dict[str, int], maxes: dict[str, int], ttl: int) -> list:
    args: list = [ttl, len(increments)]
    for field, value in increments.items():
        args += [field, int(value)]
    for field, value in maxes.items():
        args += [field, int(value)]
    return args


class RedisMinuteStore:
    def __init__(self, url: str) -> None:
        self._url = url
        self._sync = None
        self._async: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()

    def _client(self):
        if self._sync is None:
            import redis

            with self._lock:
                if self._sync is None:
                    self._sync = redis.Redis.from_url(
                        self._url, socket_timeout=SOCKET_TIMEOUT_SECONDS, socket_connect_timeout=SOCKET_TIMEOUT_SECONDS
                    )
        return self._sync

    def _async_client(self):
        import redis.asyncio as redis_asyncio

        loop = asyncio.get_running_loop()
        client = self._async.get(loop)
        if client is None:
            client = redis_asyncio.Redis.from_url(
                self._url, socket_timeout=SOCKET_TIMEOUT_SECONDS, socket_connect_timeout=SOCKET_TIMEOUT_SECONDS
            )
            self._async[loop] = client
        return client

    def add(self, key, increments, maxes, ttl):
        self._client().eval(_ADD_SCRIPT, 1, key, *_script_args(increments, maxes, ttl))

    async def add_async(self, key, increments, maxes, ttl):
        await self._async_client().eval(_ADD_SCRIPT, 1, key, *_script_args(increments, maxes, ttl))

    def keys(self, prefix):
        return [k.decode() if isinstance(k, bytes) else k for k in self._client().scan_iter(match=f"{prefix}*", count=500)]

    def take(self, key):
        pipe = self._client().pipeline(transaction=True)
        pipe.hgetall(key)
        pipe.delete(key)
        values, _ = pipe.execute()
        return {(f.decode() if isinstance(f, bytes) else f): int(v) for f, v in values.items()}

    def set_value(self, key, value, ttl):
        self._client().set(key, value, ex=ttl)

    async def set_value_async(self, key, value, ttl):
        await self._async_client().set(key, value, ex=ttl)

    def get_value(self, key):
        value = self._client().get(key)
        return value.decode() if isinstance(value, bytes) else value


class MemoryMinuteStore:
    """시험용 — 같은 의미를 dict 로 낸다. TTL 은 기록만 하고 지우지 않는다(시험이 시각을 움직이지 않는다).
    `fail` 을 켜면 모든 동작이 Redis 연결 실패처럼 던진다."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, int]] = {}
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self.hashes.clear()
            self.values.clear()
            self.ttls.clear()
            self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("흉내 Redis: 연결 거부")

    def add(self, key, increments, maxes, ttl):
        self._check()
        with self._lock:
            row = self.hashes.setdefault(key, {})
            for field, value in increments.items():
                row[field] = row.get(field, 0) + int(value)
            for field, value in maxes.items():
                if int(value) > row.get(field, -1):
                    row[field] = int(value)
            self.ttls[key] = ttl

    async def add_async(self, key, increments, maxes, ttl):
        self.add(key, increments, maxes, ttl)

    def keys(self, prefix):
        self._check()
        with self._lock:
            return [k for k in self.hashes if k.startswith(prefix)]

    def take(self, key):
        self._check()
        with self._lock:
            return self.hashes.pop(key, {})

    def set_value(self, key, value, ttl):
        self._check()
        with self._lock:
            self.values[key] = value
            self.ttls[key] = ttl

    async def set_value_async(self, key, value, ttl):
        self.set_value(key, value, ttl)

    def get_value(self, key):
        self._check()
        return self.values.get(key)


_memory = MemoryMinuteStore()
_redis: RedisMinuteStore | None = None


def get_store() -> MinuteStore:
    global _redis
    if settings.OPS_METRICS_STORE == "memory":
        return _memory
    if _redis is None or _redis._url != settings.OPS_METRICS_REDIS_URL:
        _redis = RedisMinuteStore(settings.OPS_METRICS_REDIS_URL)
    return _redis


def memory_store() -> MemoryMinuteStore:
    """시험이 흉내 저장소를 비우고 장애를 켜는 손잡이."""

    return _memory
