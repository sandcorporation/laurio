"""강의실 알림 생성·읽음 변경이 fake 이벤트 버스에 `notification-changed`를
발행한다 (#381, ADR-0046).

알림 벨이 새로고침 없이 곧바로 맞춰지는 것의 뒷받침이다 — 신호 자체에는 무엇이
바뀌었는지 싣지 않는다(`attempt-scored`와 같은 원칙, "스트림은 진실의 출처가
아니다"), 받는 사람만 정확히 지목한다. 공모전(공개 앱) 알림은 애초에 신호를
내지 않는다 — `CLASSROOM_NOTIFICATION_TYPES` 밖의 유형은 이 버스를 아예 모른다.

`notifications`는 공유층이고 `classroom`은 기능 앱이라(`tests/
test_app_boundaries.py` 규칙 B) `classroom.events`를 부르는 자리마다
APP-BOUNDARY-EXCEPTION 표시가 있다 — 이 파일은 그 결과(신호 발행)만 HTTP로
확인한다.
"""

from __future__ import annotations

from django.conf import settings

from core.events import FakeEventBus
from notifications.models import NotificationType

CREATE_URL = "/api/internal/notifications"
MARK_READ_URL = "/api/notifications/mark-read"
MARK_MANY_URL = "/api/notifications/mark-read-many"


def _mark_one_url(notification_id: int) -> str:
    return f"/api/notifications/{notification_id}/mark-read"


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


def _user_id_from_me(client, pair) -> int:
    response = client.get("/api/accounts/me", **_auth_header(pair))
    assert response.status_code == 200
    return response.json()["id"]


def _create_notification(client, capture, *, recipient_id: int, notification_type):
    with capture(execute=True):
        response = client.post(
            CREATE_URL,
            data={"recipient_id": recipient_id, "notification_type": notification_type},
            content_type="application/json",
            **_internal_headers(),
        )
    assert response.status_code == 200, response.content
    return response.json()


def test_classroom_notification_creation_publishes_to_the_recipient_only(
    client, db, django_capture_on_commit_callbacks
):
    pair = _login(client, "notif-create")
    other = _login(client, "notif-create-other")
    user_id = _user_id_from_me(client, pair)
    other_id = _user_id_from_me(client, other)

    _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
    )

    events = FakeEventBus._queues.get(user_id, [])
    assert len(events) == 1
    assert events[0].kind == "notification-changed"
    assert events[0].recipient_id == user_id
    assert FakeEventBus._queues.get(other_id, []) == []


def test_contest_notification_creation_does_not_publish(
    client, db, django_capture_on_commit_callbacks
):
    """AC: 공개 앱(공모전) 알림은 신호를 내지 않는다."""

    pair = _login(client, "notif-contest")
    user_id = _user_id_from_me(client, pair)

    _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.RESULT_NOTICE,
    )

    assert FakeEventBus._queues.get(user_id, []) == []


def test_mark_all_read_with_classroom_only_publishes(client, db, django_capture_on_commit_callbacks):
    pair = _login(client, "notif-mark-all")
    user_id = _user_id_from_me(client, pair)
    _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
    )
    FakeEventBus._queues.pop(user_id, None)  # 생성 신호를 걷어내고 읽음 신호만 본다

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{MARK_READ_URL}?classroom_only=true", **_auth_header(pair))
    assert response.status_code == 200
    assert response.json()["marked_count"] == 1

    events = FakeEventBus._queues.get(user_id, [])
    assert len(events) == 1
    assert events[0].kind == "notification-changed"
    assert events[0].recipient_id == user_id


def test_mark_all_read_without_classroom_only_does_not_publish(
    client, db, django_capture_on_commit_callbacks
):
    """공개 앱의 「모두 읽음」(classroom_only 생략)은 신호를 내지 않는다."""

    pair = _login(client, "notif-mark-all-public")
    user_id = _user_id_from_me(client, pair)
    _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.RESULT_NOTICE,
    )
    FakeEventBus._queues.pop(user_id, None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(MARK_READ_URL, **_auth_header(pair))
    assert response.status_code == 200
    assert response.json()["marked_count"] == 1

    assert FakeEventBus._queues.get(user_id, []) == []


def test_mark_all_read_with_classroom_only_and_nothing_to_mark_does_not_publish(
    client, db, django_capture_on_commit_callbacks
):
    """이미 다 읽은 상태에서 다시 눌러도(marked_count == 0) 신호가 나가지 않는다."""

    pair = _login(client, "notif-mark-all-empty")

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{MARK_READ_URL}?classroom_only=true", **_auth_header(pair))
    assert response.status_code == 200
    assert response.json()["marked_count"] == 0

    user_id = _user_id_from_me(client, pair)
    assert FakeEventBus._queues.get(user_id, []) == []


def test_mark_one_read_on_classroom_notification_publishes(
    client, db, django_capture_on_commit_callbacks
):
    pair = _login(client, "notif-mark-one")
    user_id = _user_id_from_me(client, pair)
    created = _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING,
    )
    FakeEventBus._queues.pop(user_id, None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_mark_one_url(created["id"]), **_auth_header(pair))
    assert response.status_code == 200

    events = FakeEventBus._queues.get(user_id, [])
    assert len(events) == 1
    assert events[0].kind == "notification-changed"


def test_mark_one_read_on_contest_notification_does_not_publish(
    client, db, django_capture_on_commit_callbacks
):
    pair = _login(client, "notif-mark-one-contest")
    user_id = _user_id_from_me(client, pair)
    created = _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.RESULT_NOTICE,
    )
    FakeEventBus._queues.pop(user_id, None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_mark_one_url(created["id"]), **_auth_header(pair))
    assert response.status_code == 200

    assert FakeEventBus._queues.get(user_id, []) == []


def test_mark_many_read_with_a_classroom_notification_publishes_once(
    client, db, django_capture_on_commit_callbacks
):
    pair = _login(client, "notif-mark-many")
    user_id = _user_id_from_me(client, pair)
    first = _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
    )
    second = _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
    )
    FakeEventBus._queues.pop(user_id, None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            MARK_MANY_URL,
            data={"notification_ids": [first["id"], second["id"]]},
            content_type="application/json",
            **_auth_header(pair),
        )
    assert response.status_code == 200
    assert response.json()["marked_count"] == 2

    events = FakeEventBus._queues.get(user_id, [])
    assert len(events) == 1
    assert events[0].kind == "notification-changed"


def test_mark_many_read_with_only_contest_notifications_does_not_publish(
    client, db, django_capture_on_commit_callbacks
):
    pair = _login(client, "notif-mark-many-contest")
    user_id = _user_id_from_me(client, pair)
    first = _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=user_id,
        notification_type=NotificationType.RESULT_NOTICE,
    )
    FakeEventBus._queues.pop(user_id, None)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            MARK_MANY_URL,
            data={"notification_ids": [first["id"]]},
            content_type="application/json",
            **_auth_header(pair),
        )
    assert response.status_code == 200

    assert FakeEventBus._queues.get(user_id, []) == []


def test_marking_someone_elses_notification_id_does_not_publish_to_the_attacker(
    client, db, django_capture_on_commit_callbacks
):
    """다른 사람의 알림 id를 넣어도(어차피 걸러진다) 그 시도를 한 사람에게는
    신호가 가지 않는다."""

    victim = _login(client, "notif-victim")
    victim_id = _user_id_from_me(client, victim)
    victim_notification = _create_notification(
        client,
        django_capture_on_commit_callbacks,
        recipient_id=victim_id,
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
    )
    FakeEventBus._queues.pop(victim_id, None)

    attacker = _login(client, "notif-attacker")
    attacker_id = _user_id_from_me(client, attacker)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(_mark_one_url(victim_notification["id"]), **_auth_header(attacker))
    assert response.status_code == 404

    assert FakeEventBus._queues.get(victim_id, []) == []
    assert FakeEventBus._queues.get(attacker_id, []) == []
