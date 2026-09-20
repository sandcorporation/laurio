"""알림 목록이 커서(keyset)로 끝까지 읽힌다 (#151, #466).

예전에는 `GET /api/notifications/me`가 `limit`/`offset`으로 최신
`NOTIFICATION_HISTORY_PAGE_SIZE`(50)건만 읽혔고 「더 보기」가 없어 그 뒤의
안 읽은 알림은 이 화면에 존재하지 않았다 — 헤더 배지(`/unread-count`, 전체를
센다)와 어긋나는 결함이었다(spec #461 문제 진술). 이 파일은 그 커서 계약을
HTTP로만 확인한다(CLAUDE.md "HTTP가 유일한 시임이다").
"""

from __future__ import annotations

import pytest
from django.conf import settings

from notifications.models import NotificationType

ME_URL = "/api/notifications/me"
UNREAD_COUNT_URL = "/api/notifications/unread-count"
MARK_READ_URL = "/api/notifications/mark-read"
CREATE_URL = "/api/internal/notifications"

# `notifications.api.NOTIFICATION_HISTORY_PAGE_SIZE`와 같은 값 — 이 파일이 그
# 상수를 직접 import하지 않는 이유는 "실제 배포 계약"(50건마다 페이지가
# 갈린다)을 이 테스트가 그대로 다시 확인해야 하기 때문이다(상수를 그대로
# 읽으면 상수가 잘못 바뀌어도 이 테스트가 따라가 버린다).
PAGE_SIZE = 50


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _login(client, uid: str) -> dict:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(pair: dict) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {pair['access']}"}


def _user_id_from_me(client, pair: dict) -> int:
    response = client.get("/api/accounts/me", **_auth_header(pair))
    assert response.status_code == 200
    return response.json()["id"]


def _create_notification(client, *, recipient_id: int) -> int:
    response = client.post(
        CREATE_URL,
        data={"recipient_id": recipient_id, "notification_type": NotificationType.RESULT_NOTICE},
        content_type="application/json",
        **_internal_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()["id"]


def _create_many(client, *, recipient_id: int, count: int) -> list[int]:
    return [_create_notification(client, recipient_id=recipient_id) for _ in range(count)]


@pytest.mark.django_db
def test_first_page_has_next_cursor_when_more_than_page_size(client):
    pair = _login(client, "cursor-more")
    user_id = _user_id_from_me(client, pair)
    _create_many(client, recipient_id=user_id, count=PAGE_SIZE + 5)

    response = client.get(ME_URL, **_auth_header(pair))

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == PAGE_SIZE
    assert body["count"] == PAGE_SIZE + 5
    assert body["next"] is not None


@pytest.mark.django_db
def test_more_button_reaches_the_end(client):
    """「더 보기」로 끝까지 읽을 수 있다(AC) — 커서를 따라가면 51번째 이후의
    알림도 존재한다."""

    pair = _login(client, "cursor-end")
    user_id = _user_id_from_me(client, pair)
    created_ids = set(_create_many(client, recipient_id=user_id, count=PAGE_SIZE + 5))

    first = client.get(ME_URL, **_auth_header(pair)).json()
    second = client.get(f"{ME_URL}?after={first['next']}", **_auth_header(pair)).json()

    assert len(second["items"]) == 5
    assert second["next"] is None

    seen_ids = {row["id"] for row in first["items"]} | {row["id"] for row in second["items"]}
    assert seen_ids == created_ids


@pytest.mark.django_db
def test_no_duplicate_or_missing_rows_when_list_grows_from_the_head_between_pages(client):
    """오프셋이 머리 쪽에서 자라는 목록에서 틀리던 바로 그 경우(core.keyset
    모듈 독스트링) — 1페이지를 읽은 뒤(그 커서를 손에 쥔 채로) 새 알림이
    머리에 하나 더 생겨도 2페이지가 1페이지의 행을 다시 주거나 원래
    2페이지에 있어야 할 행을 건너뛰지 않는다."""

    pair = _login(client, "cursor-grow")
    user_id = _user_id_from_me(client, pair)
    first_batch = _create_many(client, recipient_id=user_id, count=PAGE_SIZE + 5)

    first = client.get(ME_URL, **_auth_header(pair)).json()
    assert len(first["items"]) == PAGE_SIZE
    assert first["next"] is not None

    # 1페이지를 다 본 뒤(커서를 이미 받은 뒤)에 새 알림이 머리에 하나 더
    # 생긴다 — 오프셋이었다면 이 삽입 하나가 2페이지의 경계를 통째로 밀어
    # 1페이지의 마지막 행을 다시 주고 원래 2페이지 끝 행 하나를 지웠을
    # 것이다(core.keyset 모듈 독스트링).
    new_id = _create_notification(client, recipient_id=user_id)

    second = client.get(f"{ME_URL}?after={first['next']}", **_auth_header(pair)).json()

    first_page_ids = {row["id"] for row in first["items"]}
    second_page_ids = {row["id"] for row in second["items"]}
    assert first_page_ids.isdisjoint(second_page_ids)  # 중복 없음
    assert new_id not in second_page_ids  # 새 알림은 1페이지 몫이지 2페이지가 아니다.
    assert second_page_ids == set(first_batch) - first_page_ids  # 원래 남았어야 할 5건 그대로.


@pytest.mark.django_db
def test_unreadable_cursor_is_422_not_a_silent_restart(client):
    """읽을 수 없는 커서를 조용히 처음부터로 받으면 「더 보기」를 눌렀는데
    목록이 처음으로 되돌아간 화면이 된다(core.keyset 모듈 독스트링과 같은
    이유, `payouts.api.list_payouts_for_operator`의 선례)."""

    pair = _login(client, "cursor-garbage")

    response = client.get(f"{ME_URL}?after=not-a-real-cursor", **_auth_header(pair))

    assert response.status_code == 422


@pytest.mark.django_db
def test_mark_all_read_covers_notifications_beyond_the_first_page(client):
    """「모두 읽음」이 화면에 없는(51번째 이후) 알림까지 덮는다(AC) — 배지
    수와 목록이 같은 사실을 가리켜야 한다."""

    pair = _login(client, "cursor-mark-all")
    user_id = _user_id_from_me(client, pair)
    _create_many(client, recipient_id=user_id, count=PAGE_SIZE + 5)

    unread_before = client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"]
    assert unread_before == PAGE_SIZE + 5

    marked = client.post(MARK_READ_URL, content_type="application/json", **_auth_header(pair))
    assert marked.json()["marked_count"] == PAGE_SIZE + 5

    unread_after = client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"]
    assert unread_after == 0

    # 목록의 안 읽음 표시도 페이지 두 곳 모두에서 전부 사라진다.
    first = client.get(ME_URL, **_auth_header(pair)).json()
    second = client.get(f"{ME_URL}?after={first['next']}", **_auth_header(pair)).json()
    assert all(row["read_at"] is not None for row in first["items"])
    assert all(row["read_at"] is not None for row in second["items"])
