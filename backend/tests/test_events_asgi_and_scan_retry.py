"""이벤트 서비스 부팅과 스캔 재시도 — 오류 수집기가 잡아낸 둘(2026-09-16).

오류 수집기(GlitchTip)를 붙인 첫날 staging 백엔드에 오류가 둘 올라왔고, 둘 다
「서비스는 멀쩡한데 오류가 쌓인다」였다. 진짜 사고와 섞이면 그 자체가 소음이라
같은 일이 다시 쌓이지 않게 여기서 고정한다.
"""

from __future__ import annotations

import asyncio

import requests

from config.asgi import application
from core.tasks import run_scan


def test_asgi_entrypoint_answers_lifespan_instead_of_raising():
    """uvicorn 은 뜰 때 lifespan 메시지를 보낸다. Django 의 핸들러는 그것을 보면
    `ValueError: ... not lifespan.` 을 던지고, uvicorn 은 그 기능만 끄고 계속
    뜬다 — 서비스는 정상인데 부팅마다 오류 하나가 남았다(6건까지 쌓였다)."""

    sent: list[str] = []
    messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message["type"])

    asyncio.run(application({"type": "lifespan"}, receive, send))

    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert messages == []


def test_internal_http_tasks_retry_connection_failures():
    """배포 중 backend 컨테이너가 바뀌는 몇 초 동안 beat 의 tick 이 `Connection
    refused` 로 죽었다. 스캔은 두 번 쏴도 한 번만 통과하므로(ADR-0003) 다시 쏘는
    것이 안전하다 — 연결·타임아웃만 재시도하고, 끝까지 실패하면 예외를 낸다."""

    # 강의실 채점은 celery 태스크가 아니라 상주 grader 다(#584, ADR-0059) — 이 재시도의
    # 대상이 아니다.
    task = run_scan
    assert task.max_retries and task.max_retries > 0, task.name
    assert requests.ConnectionError in task.autoretry_for, task.name
    assert requests.Timeout in task.autoretry_for, task.name
    # 응답이 2xx 가 아닌 것(=서버가 대답은 했다)은 재시도하지 않는다 — 그건
    # 진짜 실패이고, 삼키지 않는다는 원칙이 그대로 적용된다.
    assert requests.HTTPError not in task.autoretry_for, task.name
