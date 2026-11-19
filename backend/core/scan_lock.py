"""스캔 하나의 실행을 한 번에 하나로 (#986 보탬 4).

워커 안에서 도는 스캔(`ScanSpec.worker_time_limit_seconds`)은 한 실행이 주기보다 길 수 있다 — 공모전
채점은 벤더 한도가 180초다. 그 사이 beat 가 같은 스캔을 다시 보내면 워커의 다른 자식(`--concurrency 2`)이
같은 앞머리 제출을 집어 벤더를 겹쳐 부르고, 돈을 움직이는 다른 스캔이 쉴 자리가 없어진다. 그래서
실행마다 공용 Redis 에 `SET NX EX` 잠금을 잡고, 못 잡은 실행은 아무것도 하지 않고 끝난다.

잠금은 짧은 임대(`LEASE_SECONDS`)로 잡고, 잡은 실행이 살아 있는 동안 곁 스레드가 임대를 늘린다 — 늘리기는
그 스캔의 상한(`worker_time_limit_seconds`)까지다. 배포로 워커가 죽으면 늘리던 스레드도 같이 죽어 임대 한 번
안에 풀린다(#1699 — 상한 840초를 통째로 잡았더니 재기동 뒤 13분 동안 스캔이 「앞 실행이 아직 돈다」로 건너뛰었다). 저장소는 생존 신호(`core.heartbeat`)와 같은 Redis·같은 시험 흉내 스위치를 쓴다
(`HEALTH_REDIS_URL`·`HEALTH_STORE`).
"""

from __future__ import annotations

import contextlib
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Protocol

from django.conf import settings

SOCKET_TIMEOUT = 2.0
KEY_PREFIX = "codemit:scan-lock:"


class LockStore(Protocol):
    def set(self, name: str, value: str, *, nx: bool, ex: int) -> object: ...
    def get(self, name: str) -> bytes | str | None: ...
    def delete(self, name: str) -> object: ...


class MemoryLockStore:
    """프로세스 안 흉내 — redis 의 `SET NX EX` 와 만료를 같게 만든다."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float]] = {}
        self._mutex = threading.Lock()

    def set(self, name: str, value: str, *, nx: bool, ex: int) -> bool | None:
        with self._mutex:
            current = self._values.get(name)
            if nx and current is not None and current[1] > time.monotonic():
                return None
            self._values[name] = (value, time.monotonic() + ex)
            return True

    def get(self, name: str) -> str | None:
        current = self._values.get(name)
        if current is None or current[1] <= time.monotonic():
            return None
        return current[0]

    def delete(self, name: str) -> int:
        with self._mutex:
            return int(self._values.pop(name, None) is not None)


_memory = MemoryLockStore()


def store() -> LockStore:
    if settings.HEALTH_STORE == "memory":
        return _memory
    import redis

    return redis.from_url(
        settings.HEALTH_REDIS_URL, socket_connect_timeout=SOCKET_TIMEOUT, socket_timeout=SOCKET_TIMEOUT
    )


LEASE_SECONDS = 60


def _renew(client: LockStore, key: str, token: str, *, ttl: int, every: float, until: float, stop: threading.Event) -> None:
    while not stop.wait(every) and time.monotonic() < until:
        current = client.get(key)
        if isinstance(current, bytes):
            current = current.decode()
        if current != token:
            return  # 임대가 끊겨 남이 잡았다 — 남의 잠금은 늘리지 않는다.
        client.set(key, token, nx=False, ex=ttl)


@contextlib.contextmanager
def hold(
    scan_name: str,
    seconds: float,
    *,
    client: LockStore | None = None,
    lease_seconds: float = LEASE_SECONDS,
    renew_every: float | None = None,
) -> Iterator[bool]:
    """잠금을 잡았으면 True 를 낸다. 끝나면 **자기가 잡은 잠금만** 푼다(만료 뒤 남이 잡은 것은 두고)."""

    client = client if client is not None else store()
    key = f"{KEY_PREFIX}{scan_name}"
    token = uuid.uuid4().hex
    ttl = max(int(min(seconds, lease_seconds)), 1)
    acquired = bool(client.set(key, token, nx=True, ex=ttl))
    stop = threading.Event()
    renewer = None
    if acquired and seconds > ttl:
        renewer = threading.Thread(
            target=_renew,
            args=(client, key, token),
            kwargs={"ttl": ttl, "every": renew_every or ttl / 3, "until": time.monotonic() + seconds, "stop": stop},
            name=f"scan-lock-renew:{scan_name}",
            daemon=True,
        )
        renewer.start()
    try:
        yield acquired
    finally:
        stop.set()
        if renewer is not None:
            renewer.join(timeout=SOCKET_TIMEOUT * 2)
        if acquired:
            current = client.get(key)
            if isinstance(current, bytes):
                current = current.decode()
            if current == token:
                client.delete(key)
