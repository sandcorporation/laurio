"""공모전과 강의실 알림이 서로 섞이지 않는다 (#304, #345).

`/api/notifications/*`(#230)는 공개 앱과 강의실이 같은 엔드포인트를 나눠
쓴다 — 계정이 공유되기 때문이다(ADR-0038). `classroom_only` 쿼리 하나로
목록·안 읽은 개수·읽음 처리 셋 다 강의실 알림(`CLASSROOM_NOTIFICATION_TYPES`)
만 보게 거를 수 있다. **기본값(`classroom_only` 생략, 공개 앱이 쓰는 값)은
강의실 알림을 뺀 나머지다**(#345) — 예전에는 "전부"였지만, 공개 앱 종 배지가
강의실 채점 결과까지 세는 것이 이 티켓이 고친 버그였다(CONTEXT.md
「강의실 알림」: "공모전 쪽 화면은 그것을 세지도 보이지도 않는다").
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


def test_me_without_scope_excludes_classroom_notifications(client, db):
    """기본값(공개 앱)은 강의실 알림을 뺀 나머지만 보여준다(#345)."""

    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(ME_URL, **_auth_header(session["access"]))

    ids = {row["id"] for row in response.json()["items"]}
    assert ids == {contest_id}
    assert classroom_id not in ids


def test_me_with_classroom_only_lists_only_classroom_notifications(client, db):
    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(f"{ME_URL}?classroom_only=true", **_auth_header(session["access"]))

    ids = {row["id"] for row in response.json()["items"]}
    assert ids == {classroom_id}
    assert contest_id not in ids


def test_unread_count_without_scope_excludes_classroom_notifications(client, db):
    """공개 앱 종 배지는 강의실 채점 결과로 울리지 않는다(#345)."""

    session, _classroom_id, _contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.get(UNREAD_COUNT_URL, **_auth_header(session["access"]))

    assert response.json()["count"] == 1


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


def test_mark_read_without_scope_leaves_classroom_notifications_unread(client, db):
    """공개 앱의 「모두 읽음」은 그 사람의 강의실 알림을 건드리지 않는다(#345,
    반대 방향은 위 `test_mark_read_with_classroom_only_leaves_other_types_unread`)."""

    session, classroom_id, contest_id = _make_participant_with_two_kinds_of_notification(client)

    response = client.post(
        MARK_READ_URL, content_type="application/json", **_auth_header(session["access"])
    )

    assert response.json()["marked_count"] == 1
    assert Notification.objects.get(pk=classroom_id).read_at is None
    assert Notification.objects.get(pk=contest_id).read_at is not None
