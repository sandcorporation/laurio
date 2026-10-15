"""요청 머리를 보내지 않는 빈 연결이 backend 워커를 묶지 않는다(#725).

sync 워커는 연결 하나를 받으면 요청 머리가 올 때까지 그 연결에 묶인다. BFF 의 undici 가
남긴 빈 연결이 워커 수만큼 쌓이면 그동안 아무도 응답을 못 받았다(prod 포함).
`config/gunicorn.conf.py` 가 gthread 로 바꿨다 — 배포 compose 셋이 읽는 그 파일을 그대로
읽어 **실제 gunicorn 프로세스**를 띄우고, 빈 연결을 워커 수만큼 쥔 채 다음 요청이 1초
안에 응답받는지 본다. 같은 시험에 `--worker-class sync` 만 덮어쓰면 묶이는 것도 남겨
둔다 — 그 시험이 초록이어야 위 시험이 무엇을 막는지가 증명된다.
"""

from __future__ import annotations

import os
import runpy
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONF = BACKEND_DIR / "config" / "gunicorn.conf.py"
WORKERS = 2
#: 응답을 기다리는 한도 — 묶이면 gunicorn 26 gthread 의 5초, sync 의 30초보다 훨씬 짧다.
REPLY_WITHIN = 1.0


def _connect(path: str) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(REPLY_WITHIN)
    s.connect(path)
    return s


def _get(path: str) -> bytes:
    s = _connect(path)
    try:
        s.sendall(b"GET / HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        return s.recv(64)
    finally:
        s.close()


def _serve(tmp_path: Path, *extra: str):
    sock = str(tmp_path / "g.sock")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)}
    env.pop("PROMETHEUS_MULTIPROC_DIR", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "-c", str(CONF), "--bind", f"unix:{sock}",
         "--workers", str(WORKERS), *extra, "gunicorn_probe_app:app"],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while True:
        try:
            if _get(sock).startswith(b"HTTP/1.1 200"):
                break
        except OSError:
            pass
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            raise AssertionError("gunicorn 이 뜨지 않았다")
        time.sleep(0.05)
    return proc, sock


def _reply_while_idle_connections_held(tmp_path: Path, *extra: str) -> bytes | None:
    proc, sock = _serve(tmp_path, *extra)
    idle = []
    try:
        # 워커 수만큼 연결만 맺고 아무것도 보내지 않는다 — undici 가 남기는 빈 연결.
        idle = [_connect(sock) for _ in range(WORKERS)]
        time.sleep(0.2)  # 워커가 그 연결들을 받아 들 시간
        try:
            return _get(sock)
        except TimeoutError:
            return None
    finally:
        for s in idle:
            s.close()
        proc.send_signal(signal.SIGINT)  # 빠른 종료 — TERM 은 graceful_timeout 을 기다린다
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_idle_connections_do_not_block_the_next_request(tmp_path):
    reply = _reply_while_idle_connections_held(tmp_path)

    assert reply is not None and reply.startswith(b"HTTP/1.1 200"), (
        f"빈 연결 {WORKERS}개를 쥔 동안 다음 요청이 {REPLY_WITHIN}초 안에 응답받지 못했다"
    )


def test_sync_workers_are_blocked_by_idle_connections(tmp_path):
    """gthread 를 되돌리면 생기는 일 — 위 시험이 무엇을 막는지의 증거."""
    # threads 가 1보다 크면 gunicorn 은 sync 를 gthread 로 바꿔 띄운다 — 1로 같이 덮는다.
    reply = _reply_while_idle_connections_held(
        tmp_path, "--worker-class", "sync", "--threads", "1"
    )

    assert reply is None


def test_server_keeps_idle_keepalive_longer_than_undici():
    """서버가 쉬는 연결을 클라이언트(BFF 의 undici, 4초)보다 먼저 닫으면 클라이언트가 막
    닫힌 연결에 요청을 실어 떨어진다 — gthread 는 sync 와 달리 연결을 살려 둔다."""
    conf = runpy.run_path(str(CONF))

    assert conf["worker_class"] == "gthread"
    assert conf["keepalive"] > 4
    assert conf["timeout"] == 30
