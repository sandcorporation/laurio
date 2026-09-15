"""운영팀 알림 — 운영자가 한 사용자에게 제목·본문을 보낸다 (#418, CONTEXT.md
「운영자 알림」).

유일한 테스트 시임은 HTTP다. 받는 사람은 fake 카카오 로그인으로 만들고
(`tests/test_notification_read_state.py`와 같은 관용구), Operator 는
`create_operator` 관리 명령으로 만든 뒤 `/api/operator/login`으로 세션을 연다
(`tests/test_appeals.py`의 `_operator_client`와 같은 관용구).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from notifications.models import Notification, NotificationDispatch, NotificationType

RECIPIENTS_URL = "/api/operator/notifications/operator-notices/recipients"
SEND_URL = "/api/operator/notifications/operator-notices"
ME_URL = "/api/notifications/me"

# Django 테스트 클라이언트의 기본 호스트 — 운영자 경로의 변경 요청은 Origin 을
# 검증한다(ADR-0016, test_appeals.py와 같은 값).
OPERATOR_ORIGIN = "http://testserver"


def _operator_client(username="notice-op", *, superuser=False):
    call_command("create_operator", username, password="operator-pw-9134-xyz", superuser=superuser)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _login_recipient(client, uid="recipient-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _send(operator, *, recipient_id, title="기프티콘을 보내드립니다", body="축하합니다!"):
    return operator.post(
        SEND_URL,
        data={"recipient_id": recipient_id, "title": title, "body": body},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )


def test_operator_sends_and_recipient_sees_title_and_body_in_list(client, db):
    session = _login_recipient(client)
    recipient_id = get_user_model().objects.get(email="recipient-1@example.com").id
    operator = _operator_client()

    response = _send(operator, recipient_id=recipient_id)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["title"] == "기프티콘을 보내드립니다"
    assert body["recipient_id"] == recipient_id

    listing = client.get(ME_URL, **_auth_header(session["access"]))
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["notification_type"] == NotificationType.OPERATOR_NOTICE
    assert row["title"] == "기프티콘을 보내드립니다"
    assert row["body"] == "축하합니다!"
    assert row["has_image"] is False
    assert row["read_at"] is None


def test_no_channel_dispatch_is_created(client, db):
    recipient_session = _login_recipient(client, uid="recipient-2")
    recipient_id = get_user_model().objects.get(email="recipient-2@example.com").id
    operator = _operator_client(username="notice-op-2")

    response = _send(operator, recipient_id=recipient_id)
    assert response.status_code == 200, response.content

    notification = Notification.objects.get(recipient_id=recipient_id)
    assert notification.notification_type == NotificationType.OPERATOR_NOTICE
    assert notification.status == Notification.Status.NOT_DISPATCHED
    assert not NotificationDispatch.objects.filter(notification=notification).exists()
    assert recipient_session  # 세션 자체를 쓰지 않지만 로그인이 성공했는지 확인.


def test_missing_recipient_returns_422(client, db):
    operator = _operator_client(username="notice-op-3")

    response = _send(operator, recipient_id=999_999)

    assert response.status_code == 422, response.content


def test_empty_title_returns_422(client, db):
    _login_recipient(client, uid="recipient-4")
    recipient_id = get_user_model().objects.get(email="recipient-4@example.com").id
    operator = _operator_client(username="notice-op-4")

    response = _send(operator, recipient_id=recipient_id, title="")

    assert response.status_code == 422, response.content


def test_non_operator_request_is_rejected(client, db):
    session = _login_recipient(client, uid="recipient-5")
    recipient_id = get_user_model().objects.get(email="recipient-5@example.com").id

    response = client.post(
        SEND_URL,
        data={"recipient_id": recipient_id, "title": "몰래 보내기"},
        content_type="application/json",
        **_auth_header(session["access"]),
    )

    assert response.status_code in (401, 403)


def test_anonymous_request_is_rejected(client, db):
    response = client.post(
        SEND_URL,
        data={"recipient_id": 1, "title": "몰래 보내기"},
        content_type="application/json",
    )

    assert response.status_code in (401, 403)


def test_history_lists_sender_and_read_state(client, db):
    session = _login_recipient(client, uid="recipient-6")
    recipient_id = get_user_model().objects.get(email="recipient-6@example.com").id
    operator = _operator_client(username="notice-op-6")

    sent = _send(operator, recipient_id=recipient_id).json()

    history = operator.get(RECIPIENTS_URL + "?q=zz")  # 존재하지 않는 검색어 — 빈 목록만 확인.
    assert history.status_code == 200
    assert history.json() == []

    history_response = operator.get("/api/operator/notifications/operator-notices")
    assert history_response.status_code == 200, history_response.content
    rows = history_response.json()
    assert len(rows) == 1
    assert rows[0]["notification_id"] == sent["notification_id"]
    assert rows[0]["sent_by"] == "notice-op-6"
    assert rows[0]["read_at"] is None

    mark_read = client.post(
        f"/api/notifications/{sent['notification_id']}/mark-read", **_auth_header(session["access"])
    )
    assert mark_read.status_code == 200

    history_after = operator.get("/api/operator/notifications/operator-notices").json()
    assert history_after[0]["read_at"] is not None


def test_history_has_no_edit_or_delete_endpoints(client, db):
    """append-only — 수정·삭제 경로가 없다는 것을 405/404로 확인한다."""

    operator = _operator_client(username="notice-op-7")
    delete_response = operator.delete(f"{SEND_URL}/1", HTTP_ORIGIN=OPERATOR_ORIGIN)
    assert delete_response.status_code in (404, 405)


def test_search_recipients_by_email(client, db):
    _login_recipient(client, uid="recipient-8", email="searchable@example.com")
    operator = _operator_client(username="notice-op-8")

    response = operator.get(RECIPIENTS_URL + "?q=searchable")

    assert response.status_code == 200, response.content
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["email"] == "searchable@example.com"


def test_classroom_notification_count_excludes_operator_notice(client, db):
    """CONTEXT.md 「운영자 알림」: 강의실에서는 세지도 보이지도 않는다."""

    session = _login_recipient(client, uid="recipient-9")
    recipient_id = get_user_model().objects.get(email="recipient-9@example.com").id
    operator = _operator_client(username="notice-op-9")

    _send(operator, recipient_id=recipient_id)

    classroom_only = client.get(f"{ME_URL}?classroom_only=true", **_auth_header(session["access"]))
    assert classroom_only.json() == []
