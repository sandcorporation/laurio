"""내보내진 참여자에게 알림이 닿는다 (#1441-8) — 처음 내보낼 때만, 강의실 알림으로."""

from __future__ import annotations

from notifications.models import NotificationType

from classroom.tests.test_classroom_joined_classes import (
    CLASSES_URL,
    _auth_header,
    _create_class,
    _join,
    _login,
)

ME_URL = "/api/notifications/me?classroom_only=true"


def _expel(client, instructor, class_id, member_id):
    return client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )


def test_expelled_participant_gets_one_notification_for_the_class(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"], name="알고리즘 1반")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자닉네임")
    members = client.get(f"{CLASSES_URL}/{created['id']}/members", **_auth_header(instructor["access"]))
    member_id = members.json()[0]["id"]

    assert _expel(client, instructor, created["id"], member_id).status_code == 200
    # 이미 내보낸 사람을 다시 내보내도(멱등) 알림은 한 번뿐이다.
    assert _expel(client, instructor, created["id"], member_id).status_code == 200

    items = client.get(ME_URL, **_auth_header(participant["access"])).json()["items"]
    expelled = [i for i in items if i["notification_type"] == NotificationType.CLASSROOM_MEMBER_EXPELLED]
    assert len(expelled) == 1
    assert expelled[0]["context"]["class_id"] == created["id"]
    assert expelled[0]["context"]["class_name"] == "알고리즘 1반"
    # 강사에게는 가지 않는다.
    mine = client.get(ME_URL, **_auth_header(instructor["access"])).json()["items"]
    assert all(i["notification_type"] != NotificationType.CLASSROOM_MEMBER_EXPELLED for i in mine)
