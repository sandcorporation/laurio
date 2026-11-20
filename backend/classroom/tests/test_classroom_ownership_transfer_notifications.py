"""소유권 이전의 요청·수락·거절이 당사자에게 알림으로 닿는다 (#575, spec #558, #564 후속).

- **요청** → 받는 공동 강사에게 — 넘기려는 사람의 강사 이름, 만료 시각.
- **수락·거절** → 요청한(넘긴) 사람에게 — 받는 사람의 강사 이름.
- 취소·만료는 알리지 않는다 — 취소는 요청한 사람이 스스로 한 일이고, 만료는 거절과 같은
  결과라 클래스 화면의 카드가 사라지는 것으로 충분하다.
- 알림이 실패해도 요청·수락·거절은 그대로 성공한다(`notify_safely`).

준비는 마운트된 HTTP API 로(`tests.classroom_scenarios`), 알림은 각자의 강의실 알림 목록
(`/api/notifications/me?classroom_only=true`)으로 본다 — `test_classroom_co_instructor_signals.py`
와 같은 결.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from core.models import ClockOverride
from notifications.models import NotificationType
from tests.classroom_scenarios import (
    accept_ownership_transfer,
    add_co_instructor,
    auth_header,
    cancel_ownership_transfer,
    co_instructor_id_of,
    create_class,
    decline_ownership_transfer,
    get_class,
    login,
    patch_class,
    pending_ownership_transfer,
    request_ownership_transfer,
)

ME_URL = "/api/notifications/me"
REQUESTED = NotificationType.CLASSROOM_OWNERSHIP_TRANSFER_REQUESTED
ACCEPTED = NotificationType.CLASSROOM_OWNERSHIP_TRANSFER_ACCEPTED
DECLINED = NotificationType.CLASSROOM_OWNERSHIP_TRANSFER_DECLINED


def _notifications(client, access: str) -> list[dict]:
    response = client.get(f"{ME_URL}?classroom_only=true", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()["items"]


def _types(client, access: str) -> list[str]:
    return [row["notification_type"] for row in _notifications(client, access)]


def _three_instructors(client):
    """소유자 「주강사」, 받을 공동 강사 「보조 강사」, 지켜보는 공동 강사 「다른 강사」."""

    owner = login(client, "owner")
    co = login(client, "co")
    other = login(client, "other")
    class_id = create_class(client, owner["access"], name="알고리즘 1반")
    patch_class(client, owner["access"], class_id, {"instructor_display_name": "주강사"})
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, other["access"], display_name="다른 강사")
    return owner, co, other, class_id


def _request(client, owner, class_id) -> dict:
    response = request_ownership_transfer(
        client, owner["access"], class_id, co_instructor_id_of(client, owner["access"], class_id, "보조 강사")
    )
    assert response.status_code == 201, response.content
    return response.json()


def test_a_request_reaches_only_the_recipient(client, db):
    owner, co, other, class_id = _three_instructors(client)

    transfer = _request(client, owner, class_id)

    rows = _notifications(client, co["access"])
    assert [row["notification_type"] for row in rows] == [REQUESTED]
    context = rows[0]["context"]
    assert context["class_id"] == class_id
    assert context["class_name"] == "알고리즘 1반"
    assert context["requester_display_name"] == "주강사"
    # 응답은 밀리초까지 싣는다 — 같은 만료 시각인지만 본다.
    gap = datetime.fromisoformat(context["expires_at"]) - datetime.fromisoformat(transfer["expires_at"])
    assert abs(gap) < timedelta(milliseconds=1)
    assert _types(client, owner["access"]) == []
    assert _types(client, other["access"]) == []


def test_accepting_tells_the_requester_who_took_it(client, db):
    owner, co, other, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)

    assert accept_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 200

    rows = _notifications(client, owner["access"])
    assert [row["notification_type"] for row in rows] == [ACCEPTED]
    assert rows[0]["context"]["class_id"] == class_id
    assert rows[0]["context"]["class_name"] == "알고리즘 1반"
    assert rows[0]["context"]["recipient_display_name"] == "보조 강사"
    assert _types(client, co["access"]) == [REQUESTED]
    assert _types(client, other["access"]) == []


def test_declining_tells_the_requester(client, db):
    owner, co, other, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)

    assert decline_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 204

    rows = _notifications(client, owner["access"])
    assert [row["notification_type"] for row in rows] == [DECLINED]
    assert rows[0]["context"]["class_name"] == "알고리즘 1반"
    assert rows[0]["context"]["recipient_display_name"] == "보조 강사"
    assert _types(client, co["access"]) == [REQUESTED]
    assert _types(client, other["access"]) == []


def test_cancelling_tells_no_one(client, db):
    owner, co, other, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)

    assert cancel_ownership_transfer(client, owner["access"], class_id, transfer["id"]).status_code == 204

    assert _types(client, owner["access"]) == []
    assert _types(client, co["access"]) == [REQUESTED]
    assert _types(client, other["access"]) == []


def test_expiry_tells_no_one(client, db):
    start = timezone.now()
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": start})
    owner, co, _, class_id = _three_instructors(client)
    _request(client, owner, class_id)

    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": start + timedelta(days=8)})

    assert pending_ownership_transfer(client, owner["access"], class_id) is None
    assert _types(client, owner["access"]) == []
    assert _types(client, co["access"]) == [REQUESTED]


@pytest.fixture
def broken_notifications(monkeypatch):
    def explode(**_kwargs):
        raise RuntimeError("알림 저장소가 죽었다")

    monkeypatch.setattr("notifications.services.create_notification", explode)


def test_a_failing_notification_does_not_stop_request_and_accept(client, db, broken_notifications):
    owner, co, _, class_id = _three_instructors(client)

    transfer = _request(client, owner, class_id)
    assert pending_ownership_transfer(client, co["access"], class_id)["id"] == transfer["id"]

    assert accept_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 200
    assert get_class(client, co["access"], class_id)["role"] == "owner"


def test_a_failing_notification_does_not_stop_a_decline(client, db, broken_notifications):
    owner, co, _, class_id = _three_instructors(client)
    transfer = _request(client, owner, class_id)

    assert decline_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 204
    assert pending_ownership_transfer(client, owner["access"], class_id) is None
