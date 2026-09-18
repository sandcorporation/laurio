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

from django.db import connection

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


def test_stream_ends_when_its_maximum_lifetime_has_passed(client, db, monkeypatch):
    """스트림은 영원히 살지 않는다 — 수명을 넘기면 스스로 끝난다(2026-09-18).

    **왜 상한이 필요한가.** 이 요청은 끝나야 DB 연결을 놓는다(Django 는 요청
    단위로 연결을 연다). 그런데 브라우저가 떠나도 앞단(강의실 BFF)이 위쪽
    요청을 끊지 못하면 이 요청은 영원히 끝나지 않고 그 연결도 영원히 묶인다 —
    prod 에서 이벤트 서비스가 유휴 연결 100개를 쥐어 Postgres 가 `too many
    clients already`로 **모든** 요청을 거절했다(공개 앱 500, celery 포함).
    BFF 쪽은 따로 고쳤고(브라우저가 끊으면 위쪽도 끊는다), 이 상한은 그 길이
    또 새더라도 스스로 회복하게 하는 두 번째 문이다. 브라우저의 `EventSource`는
    끊기면 자동으로 다시 연결하므로 사용자에게는 보이지 않는다."""

    monkeypatch.setattr("classroom.api._SSE_MAX_LIFETIME_SECONDS", 0.0)
    user = _login(client, "stream-lifetime")

    response = client.get(STREAM_URL, **_auth_header(user["access"]))
    assert response.status_code == 200

    async def drain() -> int:
        chunks = 0
        async for _chunk in response.streaming_content:
            chunks += 1
            if chunks > 50:  # 상한이 없으면 여기서 멈춰 실패를 알린다
                break
        return chunks

    # 수명이 지난 스트림은 한 조각도 더 내보내지 않고 끝난다 — 끝난다는 것이
    # 이 테스트의 단언이고(무한 루프면 위 break 가 51 을 돌려준다), 0 은 그
    # 상한이 루프 **앞**에서 걸린다는 뜻이다.
    assert asyncio.run(drain()) == 0
