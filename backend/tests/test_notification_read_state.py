"""알림 읽음/안읽음 (#230) — 벨의 안 읽은 개수와 "목록을 열면 전부 읽음" 동작.

이 프로젝트의 유일한 테스트 시임은 HTTP다(CLAUDE.md). 로그인은 fake 소셜 어댑터로
`/api/auth/social/kakao/login`을 실제로 쳐서 JWT를 받는다(`tests/test_accounts_
profiles.py`와 같은 관용구) — User를 ORM으로 만들고 토큰 발급 함수를 직접 부르지
않는다. Notification 자체는 내부 엔드포인트(`/api/internal/notifications`)로 만든다
— 이 파일의 유일한 준비 수단이다(`tests/test_notifications.py`와 같은 관용구).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from notifications.models import Notification, NotificationType

KST = ZoneInfo("Asia/Seoul")

ME_URL = "/api/notifications/me"
UNREAD_COUNT_URL = "/api/notifications/unread-count"
MARK_READ_URL = "/api/notifications/mark-read"
CREATE_URL = "/api/internal/notifications"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _login(client, uid: str):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(pair: dict) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {pair['access']}"}


def _create_notification(client, *, recipient_id: int, notification_type=NotificationType.RESULT_NOTICE):
    response = client.post(
        CREATE_URL,
        data={"recipient_id": recipient_id, "notification_type": notification_type},
        content_type="application/json",
        **_internal_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _user_id_from_me(client, pair) -> int:
    response = client.get("/api/accounts/me", **_auth_header(pair))
    assert response.status_code == 200
    return response.json()["id"]


@pytest.mark.django_db
def test_unread_count_requires_auth(client):
    response = client.get(UNREAD_COUNT_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_mark_read_requires_auth(client):
    response = client.post(MARK_READ_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_unread_count_is_zero_with_no_notifications(client):
    pair = _login(client, "bell-empty")

    response = client.get(UNREAD_COUNT_URL, **_auth_header(pair))

    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.django_db
def test_new_notification_is_unread_and_counted(client):
    pair = _login(client, "bell-new")
    user_id = _user_id_from_me(client, pair)

    _create_notification(client, recipient_id=user_id)

    count = client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"]
    assert count == 1

    me = client.get(ME_URL, **_auth_header(pair)).json()
    assert len(me) == 1
    assert me[0]["read_at"] is None


@pytest.mark.django_db
def test_opening_the_list_marks_everything_unread_as_read_and_clears_the_badge(client):
    """AC: 목록을 열면 그 시점의 안 읽은 알림이 전부 읽음이 되고 배지가 사라진다."""

    pair = _login(client, "bell-mark-all")
    user_id = _user_id_from_me(client, pair)

    _create_notification(client, recipient_id=user_id, notification_type=NotificationType.RESULT_NOTICE)
    _create_notification(client, recipient_id=user_id, notification_type=NotificationType.SCORING_COMPLETE)
    assert client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"] == 2

    mark_response = client.post(MARK_READ_URL, **_auth_header(pair))
    assert mark_response.status_code == 200
    assert mark_response.json()["marked_count"] == 2

    assert client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"] == 0
    me = client.get(ME_URL, **_auth_header(pair)).json()
    assert all(row["read_at"] is not None for row in me)


@pytest.mark.django_db
def test_badge_reappears_when_a_new_notification_arrives_after_reading(client):
    """AC: 새 알림이 생기면 배지가 다시 나타난다."""

    pair = _login(client, "bell-reappear")
    user_id = _user_id_from_me(client, pair)

    _create_notification(client, recipient_id=user_id)
    client.post(MARK_READ_URL, **_auth_header(pair))
    assert client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"] == 0

    _create_notification(client, recipient_id=user_id)

    assert client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"] == 1


@pytest.mark.django_db
def test_mark_read_is_idempotent_and_only_counts_newly_marked_rows(client):
    pair = _login(client, "bell-idempotent")
    user_id = _user_id_from_me(client, pair)
    _create_notification(client, recipient_id=user_id)

    first = client.post(MARK_READ_URL, **_auth_header(pair)).json()
    second = client.post(MARK_READ_URL, **_auth_header(pair)).json()

    assert first["marked_count"] == 1
    assert second["marked_count"] == 0


@pytest.mark.django_db
def test_a_users_mark_read_never_touches_another_users_notifications(client):
    """AC: 남의 알림은 어떤 방법으로도 읽거나 읽음 처리할 수 없다."""

    victim = _login(client, "bell-victim")
    victim_id = _user_id_from_me(client, victim)
    _create_notification(client, recipient_id=victim_id)

    attacker = _login(client, "bell-attacker")
    attacker_marked = client.post(MARK_READ_URL, **_auth_header(attacker)).json()["marked_count"]

    assert attacker_marked == 0
    assert client.get(UNREAD_COUNT_URL, **_auth_header(victim)).json()["count"] == 1
    victim_me = client.get(ME_URL, **_auth_header(victim)).json()
    assert victim_me[0]["read_at"] is None


@pytest.mark.django_db
def test_a_users_me_list_never_includes_another_users_notifications(client):
    victim = _login(client, "bell-list-victim")
    victim_id = _user_id_from_me(client, victim)
    _create_notification(client, recipient_id=victim_id)

    attacker = _login(client, "bell-list-attacker")
    attacker_me = client.get(ME_URL, **_auth_header(attacker)).json()

    assert attacker_me == []


@pytest.mark.django_db
def test_read_state_is_independent_of_delivery_status(client):
    """AC: 읽음 여부가 발송 상태와 독립이다 — 읽었다고 발송 이력이 바뀌지 않는다.

    전 채널이 실패하도록 강제해 `FAILED` 상태의 Notification을 만들고, 그것도
    읽음 처리가 되며 그 처리로 `status`·`dispatches`가 전혀 바뀌지 않는지 본다."""

    from django.test import override_settings

    from core.models import ClockOverride

    pair = _login(client, "bell-failed-status")
    user_id = _user_id_from_me(client, pair)

    # **시각을 낮으로 고정한다.** 이 테스트는 전 채널이 실패해 `FAILED` 가 되는 것을
    # 보는데, 야간(21~08시, ADR-0010)에는 발송을 **시도하기도 전에** DEFERRED 로
    # 연기되므로 벽시계에 맡기면 밤에 도는 CI 에서만 깨진다 — 실제로 그렇게 깨졌다
    # (01:44 KST 실행에서 'deferred' != 'failed'). 바로 아래 테스트는 정반대를
    # 증명하려고 23시로 고정하고 있었는데, 이쪽만 고정이 빠져 있었다.
    # 시간은 시임이 아니라 주입 가능한 의존성이다(ADR-0003).
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": datetime(2026, 1, 10, 13, 0, tzinfo=KST)}
    )
    try:
        with override_settings(NOTIFICATION_FAKE_FAILING_CHANNELS=["alimtalk", "sms", "lms"]):
            created = _create_notification(client, recipient_id=user_id)
    finally:
        ClockOverride.objects.filter(pk=1).delete()
    assert created["status"] == Notification.Status.FAILED
    dispatches_before = created["dispatches"]

    mark_response = client.post(MARK_READ_URL, **_auth_header(pair))
    assert mark_response.json()["marked_count"] == 1

    me = client.get(ME_URL, **_auth_header(pair)).json()
    assert len(me) == 1
    assert me[0]["status"] == Notification.Status.FAILED
    assert me[0]["dispatches"] == dispatches_before
    assert me[0]["read_at"] is not None


@pytest.mark.django_db
def test_deferred_notification_is_still_visible_and_markable_as_read(client):
    """AC: 야간 연기 중인 알림이 아직 보내지 않은 상태임을 화면이 말한다 —
    백엔드 쪽에서는 `status`가 `deferred`로 그대로 노출되는지, 그리고 그것도
    읽음 처리가 막히지 않는지를 확인한다."""

    from core.models import ClockOverride

    pair = _login(client, "bell-deferred")
    user_id = _user_id_from_me(client, pair)

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": datetime(2026, 1, 10, 23, 0, tzinfo=KST)}
    )
    try:
        created = _create_notification(client, recipient_id=user_id)
    finally:
        ClockOverride.objects.filter(pk=1).delete()

    assert created["status"] == Notification.Status.DEFERRED

    assert client.get(UNREAD_COUNT_URL, **_auth_header(pair)).json()["count"] == 1
    mark_response = client.post(MARK_READ_URL, **_auth_header(pair))
    assert mark_response.json()["marked_count"] == 1

    me = client.get(ME_URL, **_auth_header(pair)).json()
    assert me[0]["status"] == Notification.Status.DEFERRED
    assert me[0]["read_at"] is not None
