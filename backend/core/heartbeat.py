"""백그라운드 워커 생존 신호(#949) — `/api/health` 가 이 키를 본다.

- celery-worker(beat 포함)와 grader 프로세스 안의 **별도 스레드**가 15초마다 redis 키 `codemit:heartbeat:<역할>` 을
  갱신한다(TTL 90초). 채점 한 건이 LLM 을 오래 기다려도 신호가 멈추지 않도록 채점 루프(asyncio)나 celery 태스크와
  묶지 않는다. 키가 없으면 그 역할이 죽었거나 멈췄거나 redis 에 못 닿는 것이다.
- 같은 때에 파일 `/tmp/codemit-heartbeat` 의 mtime 을 만진다 — 컨테이너 healthcheck 가 redis 없이 이 파일만 본다.
- 스레드가 살아 있다는 신호지 태스크 소비를 증명하지는 않는다.

시험은 프로세스 안 흉내 저장소를 쓴다(`HEALTH_STORE=memory`, 세션·운영 지표와 같은 이유).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Protocol

from django.conf import settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "codemit:heartbeat:"
INTERVAL_SECONDS = 15.0
TTL_SECONDS = 90
SOCKET_TIMEOUT = 1.0
HEARTBEAT_FILE = Path("/tmp/codemit-heartbeat")  # noqa: S108 — 컨테이너 안 healthcheck 전용
ROLES = ("celery", "grader")


class HeartbeatStore(Protocol):
    def ping(self) -> bool: ...
    def set(self, key: str, value: str, ex: int) -> object: ...
    def exists(self, key: str) -> int: ...
    def ttl(self, key: str) -> int: ...


class MemoryStore:
    """프로세스 안 흉내 — redis 의 TTL 만료까지 같게 만든다."""

    def __init__(self) -> None:
        self.reachable = True
        self._expires: dict[str, float] = {}

    def _check(self) -> None:
        if not self.reachable:
            raise ConnectionError("memory store unreachable")

    def ping(self) -> bool:
        self._check()
        return True

    def set(self, key: str, value: str, ex: int) -> bool:
        self._check()
        self._expires[key] = time.monotonic() + ex
        return True

    def exists(self, key: str) -> int:
        self._check()
        return int(self._expires.get(key, 0.0) > time.monotonic())

    def ttl(self, key: str) -> int:
        self._check()
        return max(int(self._expires.get(key, 0.0) - time.monotonic()), -2)

    def expire_now(self, key: str) -> None:
        self._expires.pop(key, None)


_memory = MemoryStore()
_started: dict[str, threading.Thread] = {}
_stops: dict[str, threading.Event] = {}
_lock = threading.Lock()


def store() -> HeartbeatStore:
    if settings.HEALTH_STORE == "memory":
        return _memory
    import redis

    return redis.from_url(
        settings.HEALTH_REDIS_URL, socket_connect_timeout=SOCKET_TIMEOUT, socket_timeout=SOCKET_TIMEOUT
    )


def beat(role: str, *, client: HeartbeatStore | None = None, path: Path | None = None) -> None:
    """신호 한 번. 파일은 redis 가 끊겨도 만진다 — redis 장애는 health 의 redis 점검이 따로 잡는다."""

    (path or HEARTBEAT_FILE).touch()
    (client or store()).set(KEY_PREFIX + role, "1", ex=TTL_SECONDS)


def _run(role: str, interval: float, stop: threading.Event) -> None:
    while not stop.wait(interval):
        try:
            beat(role)
        except Exception:  # noqa: BLE001 — redis 일시 장애로 스레드가 죽으면 안 된다. 끊김은 TTL 이 드러낸다
            logger.warning("[heartbeat] %s 신호를 보내지 못했다", role, exc_info=True)


def start_heartbeat(role: str, *, interval: float = INTERVAL_SECONDS) -> None:
    """역할당 한 번만 띄운다(중복 호출 무시). 즉시 한 번 보내고 스레드로 주기 갱신한다."""

    with _lock:
        if role in _started:
            return
        try:
            beat(role)
        except Exception:  # noqa: BLE001 — 시작 때 redis 가 없어도 워커는 떠야 한다
            logger.warning("[heartbeat] %s 첫 신호를 보내지 못했다", role, exc_info=True)
        stop = threading.Event()
        thread = threading.Thread(target=_run, args=(role, interval, stop), name=f"heartbeat-{role}", daemon=True)
        _started[role] = thread
        _stops[role] = stop
        thread.start()


def stop_heartbeat(role: str) -> None:
    """띄운 스레드를 멈춘다. 운영 워커는 부르지 않는다(프로세스와 함께 끝난다) — 시험이 스레드를 남기지 않게 쓴다.
    남은 스레드는 시험이 `time.monotonic` 을 갈아 끼운 사이에도 깨어나 그 값을 먹는다(#1083)."""

    with _lock:
        thread = _started.pop(role, None)
        stop = _stops.pop(role, None)
    if stop is not None:
        stop.set()
    if thread is not None:
        thread.join(timeout=SOCKET_TIMEOUT * 2)


def missing_roles(required: list[str], *, client: HeartbeatStore | None = None) -> list[str]:
    c = client or store()
    return [role for role in required if not c.exists(KEY_PREFIX + role)]
