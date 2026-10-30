"""백엔드 요청 지표를 프로세스 안에 모았다가 몇 초마다 그 분의 Redis 해시로 보낸다(#828).

`core.metrics.MetricsMiddleware` 가 요청마다 `record_request` 를 부른다. 해시는 `ops:req:<분>`, 필드는
`<method>|<route>|<status>|<지표>` 이고 지표는 `n` 수 · `ms` 지연 합(밀리초) · `b<i>` 지연 칸(경계
`core.metrics.DURATION_BOUNDS`, 마지막 칸이 +Inf)이다. route 는 URL 패턴(`resolver_match.route`)이고 맞는 것이
없으면 `unmatched` 다 — prometheus 라벨과 같다.

**왜 요청마다 보내지 않나(잰 값, dev Redis·루프백).** 요청마다 Lua 한 번이면 왕복이 116µs, 한 워커의 스레드
넷이 함께 쓰면 300µs 다. Redis 가 패킷을 삼키면(블랙홀) 소켓 한도 0.25초가 **요청마다** 붙는다. 버퍼에
더하기는 0.5µs 다. 그래서 요청 경로는 잠금 아래 dict 더하기만 하고, 배경 스레드가 `OPS_METRICS_REQUEST_FLUSH_SECONDS`
(5초)마다 분 하나에 Lua 한 번으로 보낸다. Redis 가 죽어도 기다리는 것은 그 스레드 하나다.

**잃는 범위.** gunicorn 이 워커를 정상으로 내리면 `worker_exit` 훅(`config/gunicorn.conf.py`)과 `atexit` 가 남은
버퍼를 보낸다. SIGKILL·OOM 으로 죽은 워커는 마지막 5초 이하를 잃는다. 보내기가 실패하면 그 묶음을 버린다
(Redis 장애가 길어도 버퍼가 자라지 않는다) — 경고는 `recorder` 규칙대로 실패가 이어지는 동안 한 번이다.

분 끝에 모은 몇 초는 beat 가 그 분을 옮긴 뒤에 닿을 수 있다 — 새 해시로 생겨 다음 flush 가 같은 행에 더한다
(`flush` 머리말).

`OPS_METRICS_REQUEST_FLUSH_SECONDS` 가 0 이면(시험) 버퍼 없이 요청마다 저장소에 바로 더한다. 흉내 저장소
(`OPS_METRICS_STORE=memory`)에서는 배경 스레드를 띄우지 않는다 — 시험이 `flush_requests()` 를 직접 부른다.
"""

from __future__ import annotations

import atexit
import os
import threading
import time

from django.conf import settings

from core.metrics import DURATION_BOUNDS

from . import recorder
from .recorder import REQUEST, _label, bucket_index, minute_of

#: 모르는 메서드는 한 칸으로 모은다 — 아무 문자열이나 보내는 요청이 행을 늘리지 못하게.
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
ROUTE_MAX = 200

_now = time.time


def request_fields(*, method: str, route: str, status: int, seconds: float) -> dict[str, int]:
    method = method if method in METHODS else "OTHER"
    prefix = f"{method}|{_label(route)[:ROUTE_MAX]}|{int(status)}"
    return {
        f"{prefix}|n": 1,
        f"{prefix}|ms": int(round(max(seconds, 0.0) * 1000)),
        f"{prefix}|b{bucket_index(DURATION_BOUNDS, seconds)}": 1,
    }


class RequestBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._minutes: dict[int, dict[str, int]] = {}
        self._thread: threading.Thread | None = None
        self._exit_hooked = False

    def add(self, minute: int, fields: dict[str, int]) -> None:
        with self._lock:
            row = self._minutes.get(minute)
            if row is None:
                row = self._minutes[minute] = {}
            for field, value in fields.items():
                row[field] = row.get(field, 0) + value
        if self._thread is None and settings.OPS_METRICS_STORE != "memory":
            self._start()

    def flush(self) -> None:
        with self._lock:
            minutes, self._minutes = self._minutes, {}
        for minute, fields in sorted(minutes.items()):
            recorder._add(REQUEST, fields, {}, minute)

    def pending(self) -> dict[int, dict[str, int]]:
        with self._lock:
            return {minute: dict(fields) for minute, fields in self._minutes.items()}

    def _start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="ops-metrics-requests", daemon=True)
            self._thread.start()
            if not self._exit_hooked:
                atexit.register(self.flush)
                self._exit_hooked = True

    def _run(self) -> None:
        while True:
            time.sleep(max(settings.OPS_METRICS_REQUEST_FLUSH_SECONDS, 1))
            try:
                self.flush()
            except Exception:  # noqa: BLE001 - 배경 스레드가 죽으면 그 뒤 기록이 모두 사라진다
                pass

    def _after_fork(self) -> None:
        # 부모가 모은 값은 부모가 보낸다. 자식은 빈 버퍼와 스레드 없음에서 시작한다(스레드는 fork 를 건너지 않는다).
        self._lock = threading.Lock()
        self._minutes = {}
        self._thread = None


_buffer = RequestBuffer()
os.register_at_fork(after_in_child=_buffer._after_fork)


def record_request(*, method: str, route: str, status: int, seconds: float) -> None:
    """요청 하나를 그 분에 더한다. 예외를 내지 않는다 — 지표가 응답을 바꾸면 안 된다."""

    try:
        at = _now()
        fields = request_fields(method=method, route=route, status=status, seconds=seconds)
        if settings.OPS_METRICS_REQUEST_FLUSH_SECONDS <= 0:
            recorder._add(REQUEST, fields, {}, at)
        else:
            _buffer.add(minute_of(at), fields)
    except Exception as exc:  # noqa: BLE001
        recorder._failed(exc)


def flush_requests() -> None:
    """버퍼를 지금 보낸다 — 배경 스레드·워커 종료 훅·시험이 부른다."""

    try:
        _buffer.flush()
    except Exception as exc:  # noqa: BLE001
        recorder._failed(exc)


def request_buffer() -> RequestBuffer:
    return _buffer
