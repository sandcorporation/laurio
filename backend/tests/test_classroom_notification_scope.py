"""강의실 알림 화면이 클래스 알림만 거른다 (#304).

`/api/notifications/*`(#230)는 공개 앱과 강의실이 같은 엔드포인트를 나눠
쓴다 — 계정이 공유되기 때문이다(ADR-0038). `classroom_only` 쿼리 하나로
목록·안 읽은 개수·읽음 처리 셋 다 강의실 알림(`CLASSROOM_NOTIFICATION_TYPES`)
만 보게 거를 수 있다. 기본값(`classroom_only` 생략)은 공개 앱이 지금까지
써온 것과 한 글자도 다르지 않아야 한다 — 그건 `test_notifications.py`가
이미 고정하고 있으므로, 이 파일은 강의실 쪽 필터링만 본다.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

from notifications.models import Notification, NotificationType

ME_URL = "/api/notifications/me"
UNREAD_COUNT_URL = "/api/notifications/unread-count"
MARK_READ_URL = "/api/notifications/mark-read"
INTERNAL_CREATE_URL = "/api/internal/notifications"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _login(client, uid="participant-1"):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _create_notification(client, recipient_id: int, notification_type: str) -> int:
    response = client.post(
        INTERNAL_CREATE_URL,
        data={"recipient_id": recipient_id, "notification_type": notification_type},
        content_type="application/json",
        **_internal_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()["id"]


def _make_participant_with_two_kinds_of_notification(client):
    session = _login(client)
    user_id = get_user_model().objects.get(username="kakao:participant-1").id
    classroom_id = _create_notification(
        client, user_id, NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    contest_id = _create_notification(client, user_id, NotificationType.DEADLINE_REMINDER)
    return session, classroom_id, contest_id


def test_me_without_scope_lists_every_notification_type(client, db):
    """기본값은 공개 앱이 지금까지 보던 것과 같다 — 공모전 알림도 섞여 나온다."""

    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(ME_URL, **_auth_header(session["access"]))

    ids = {row["id"] for row in response.json()}
    assert ids == {classroom_id, contest_id}


def test_me_with_classroom_only_lists_only_classroom_notifications(client, db):
    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(f"{ME_URL}?classroom_only=true", **_auth_header(session["access"]))

    ids = {row["id"] for row in response.json()}
    assert ids == {classroom_id}
    assert contest_id not in ids


def test_unread_count_without_scope_counts_every_type(client, db):
    session, _classroom_id, _contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(UNREAD_COUNT_URL, **_auth_header(session["access"]))

    assert response.json()["count"] == 2


def test_unread_count_with_classroom_only_counts_only_classroom_notifications(client, db):
    session, _classroom_id, _contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(
        f"{UNREAD_COUNT_URL}?classroom_only=true", **_auth_header(session["access"])
    )

    assert response.json()["count"] == 1


def test_mark_read_with_classroom_only_leaves_other_types_unread(client, db):
    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.post(
        f"{MARK_READ_URL}?classroom_only=true",
        content_type="application/json",
        **_auth_header(session["access"]),
    )
    assert response.json()["marked_count"] == 1

    classroom_notification = Notification.objects.get(pk=classroom_id)
    contest_notification = Notification.objects.get(pk=contest_id)
    assert classroom_notification.read_at is not None
    assert contest_notification.read_at is None

    # 안 읽은 개수도 그 사실을 그대로 반영한다 — 강의실 카운트는 0, 전체
    # 카운트는 여전히 공모전 알림 하나를 센다.
    classroom_count = client.get(
        f"{UNREAD_COUNT_URL}?classroom_only=true", **_auth_header(session["access"])
    ).json()["count"]
    total_count = client.get(UNREAD_COUNT_URL, **_auth_header(session["access"])).json()["count"]
    assert classroom_count == 0
    assert total_count == 1


def test_mark_read_without_scope_still_marks_everything(client, db):
    """기본 동작이 그대로다 — 강의실 필터가 생겼다고 공개 앱의 "전부 읽음"이 좁아지지 않는다."""

    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.post(
        MARK_READ_URL, content_type="application/json", **_auth_header(session["access"])
    )

    assert response.json()["marked_count"] == 2
    assert Notification.objects.get(pk=classroom_id).read_at is not None
    assert Notification.objects.get(pk=contest_id).read_at is not None
