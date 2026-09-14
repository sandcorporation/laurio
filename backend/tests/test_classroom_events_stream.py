"""이벤트 서비스의 SSE 엔드포인트 (#379, ADR-0046).

핵심 대상: 인증 없이는 거절되고, fake 버스에 쌓인 신호 중 요청한 사용자
자신의 것만 스트림에 나온다. **실제 요청**으로 연다(전체 미들웨어 스택을
거친다) — `HTTP가 유일한 시임이다`(CLAUDE.md). pytest에 Redis가 필요하지
않다: `EVENT_BUS_ADAPTER_MODE` 기본값이 fake라 이 테스트는 어떤 네트워크도
치지 않는다.
"""

from __future__ import annotations

import asyncio
import json

from core.events import Event, FakeEventBus

STREAM_URL = "/api/classroom/events/stream"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _login(client, uid: str, email: str | None = None) -> dict:
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _read_chunks(response, count: int) -> bytes:
    """`streaming_content`는 async 제너레이터다(`classroom.api._stream_events_for`
    — 반드시 async 여야 ASGI가 실제로 청크마다 흘려보낸다, 그 모듈의 docstring
    참고). Django 테스트 클라이언트는 WSGI 방식이라 이걸 자동으로 소비해 주지
    않으므로, 여기서 직접 이벤트 루프를 돌려 `count`개만 뽑는다 — 무한
    제너레이터라도 `break`로 멈추면 남은 부분은 마저 소비하지 않는다."""

    async def collect() -> list[bytes]:
        chunks: list[bytes] = []
        async for chunk in response.streaming_content:
            chunks.append(chunk)
            if len(chunks) >= count:
                break
        return chunks

    return b"".join(asyncio.run(collect()))


def test_unauthenticated_request_is_rejected(client, db):
    response = client.get(STREAM_URL)
    assert response.status_code == 401


def test_stream_carries_only_this_users_own_events(client, db):
    me = _login(client, uid="viewer")
    other = _login(client, uid="someone-else")

    from django.contrib.auth import get_user_model

    me_id = get_user_model().objects.get(username="kakao:viewer").id
    other_id = get_user_model().objects.get(username="kakao:someone-else").id

    FakeEventBus().publish(
        Event(kind="attempt-scored", recipient_id=me_id, payload={"submission_id": 1})
    )
    FakeEventBus().publish(
        Event(kind="attempt-scored", recipient_id=other_id, payload={"submission_id": 2})
    )

    response = client.get(STREAM_URL, **_auth_header(me["access"]))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"

    body = _read_chunks(response, 1)
    assert b"event: attempt-scored" in body
    assert json.dumps({"submission_id": 1}).encode() in body
    assert b"submission_id\": 2" not in body

    del other  # 다른 사용자의 토큰은 이 테스트에서 더 쓰지 않는다.


def test_stream_sends_keep_alive_comments_when_nothing_is_queued(client, db):
    me = _login(client, uid="quiet-viewer")

    response = client.get(STREAM_URL, **_auth_header(me["access"]))
    assert response.status_code == 200

    body = _read_chunks(response, 2)
    assert b"keep-alive" in body
    assert b"event:" not in body
