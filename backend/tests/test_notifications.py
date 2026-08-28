"""Notification 기반 — 어댑터 · 거래성/광고성 · 야간 연기 · 대체발송 (티켓 17, #18).

이 프로젝트의 유일한 테스트 시임은 HTTP다. User·NotificationOptIn·ClockOverride를
ORM으로 직접 만드는 것은 픽스처 준비일 뿐이고(test_admin.py가 유저를
create_superuser로 만드는 것과 같은 성격), 실제 동작 — 발송되는지, 야간이면
연기되는지, 대체발송이 되는지 — 은 전부 `/api/internal/notifications*` HTTP
엔드포인트를 통해서만 확인한다.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings

from core.models import ClockOverride
from notifications.models import Notification, NotificationOptIn, NotificationType

KST = ZoneInfo("Asia/Seoul")
CREATE_URL = "/api/internal/notifications"
DISPATCH_DUE_URL = "/api/internal/notifications/dispatch-due"
TYPES_URL = "/api/internal/notifications/types/"


def _auth_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _make_user(username="dev1"):
    return get_user_model().objects.create_user(username=username, password="pw-12345678")


@pytest.mark.django_db
def test_create_notification_requires_internal_auth(client):
    user = _make_user()

    response = client.post(
        CREATE_URL,
        data={
            "recipient_id": user.id,
            "notification_type": NotificationType.DEADLINE_REMINDER,
        },
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_list_types_exposes_transactional_and_promotional_flags(client):
    response = client.get(TYPES_URL, **_auth_headers())

    assert response.status_code == 200
    by_value = {row["value"]: row for row in response.json()}
    assert by_value[NotificationType.DEADLINE_REMINDER]["is_transactional"] is True
    assert by_value[NotificationType.DEADLINE_REMINDER]["is_promotional"] is False
    assert by_value[NotificationType.NEW_CONTEST_IN_CATEGORY]["is_promotional"] is True
    assert by_value[NotificationType.NEW_CONTEST_IN_CATEGORY]["is_transactional"] is False


@pytest.mark.django_db
def test_transactional_notification_is_sent_immediately_outside_quiet_hours(client):
    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    response = client.post(
        CREATE_URL,
        data={"recipient_id": user.id, "notification_type": NotificationType.DEADLINE_REMINDER},
        content_type="application/json",
        **_auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == Notification.Status.SENT
    assert body["is_transactional"] is True
    assert [d["channel"] for d in body["dispatches"]] == ["alimtalk"]
    assert body["dispatches"][0]["status"] == "sent"


@pytest.mark.django_db
def test_promotional_notification_is_blocked_without_opt_in(client):
    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    response = client.post(
        CREATE_URL,
        data={
            "recipient_id": user.id,
            "notification_type": NotificationType.NEW_CONTEST_IN_CATEGORY,
        },
        content_type="application/json",
        **_auth_headers(),
    )

    body = response.json()
    assert body["status"] == Notification.Status.BLOCKED_NO_OPT_IN
    assert body["dispatches"] == []


@pytest.mark.django_db
def test_promotional_notification_is_sent_when_opted_in(client):
    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()
    NotificationOptIn.objects.create(
        user=user, notification_type=NotificationType.NEW_CONTEST_IN_CATEGORY, opted_in=True
    )

    response = client.post(
        CREATE_URL,
        data={
            "recipient_id": user.id,
            "notification_type": NotificationType.NEW_CONTEST_IN_CATEGORY,
        },
        content_type="application/json",
        **_auth_headers(),
    )

    body = response.json()
    assert body["status"] == Notification.Status.SENT


@pytest.mark.parametrize(
    "at,expect_quiet",
    [
        (datetime(2026, 1, 10, 21, 0, tzinfo=KST), True),  # 21:00 포함
        (datetime(2026, 1, 10, 23, 30, tzinfo=KST), True),
        (datetime(2026, 1, 11, 3, 0, tzinfo=KST), True),
        (datetime(2026, 1, 11, 7, 59, tzinfo=KST), True),
        (datetime(2026, 1, 11, 8, 0, tzinfo=KST), False),  # 08:00 은 제외
        (datetime(2026, 1, 10, 20, 59, tzinfo=KST), False),
    ],
)
@pytest.mark.django_db
def test_quiet_hours_boundary_defers_or_sends(client, at, expect_quiet):
    _freeze(at)
    user = _make_user()

    response = client.post(
        CREATE_URL,
        data={"recipient_id": user.id, "notification_type": NotificationType.DEADLINE_REMINDER},
        content_type="application/json",
        **_auth_headers(),
    )

    body = response.json()
    if expect_quiet:
        assert body["status"] == Notification.Status.DEFERRED
        assert body["dispatches"] == []
        assert body["scheduled_for"] is not None
    else:
        assert body["status"] == Notification.Status.SENT


@pytest.mark.django_db
def test_notification_created_at_night_is_deferred_not_dropped_and_sent_next_8am(client):
    _freeze(datetime(2026, 1, 10, 23, 0, tzinfo=KST))
    user = _make_user()

    created = client.post(
        CREATE_URL,
        data={"recipient_id": user.id, "notification_type": NotificationType.DEADLINE_REMINDER},
        content_type="application/json",
        **_auth_headers(),
    ).json()
    assert created["status"] == Notification.Status.DEFERRED
    notification_id = created["id"]

    # 아직 다음 날 08시가 되지 않았다 — dispatch-due 를 불러도 폐기되지도, 발송되지도 않는다.
    _freeze(datetime(2026, 1, 11, 7, 0, tzinfo=KST))
    early = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert early.json()["count"] == 0

    still_deferred = client.get(f"{CREATE_URL}/{notification_id}", **_auth_headers()).json()
    assert still_deferred["status"] == Notification.Status.DEFERRED

    # 다음 날 08시가 되면 큐가 비워지고 실제로 발송된다.
    _freeze(datetime(2026, 1, 11, 8, 0, tzinfo=KST))
    due = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert due.json()["count"] == 1
    assert due.json()["dispatched_ids"] == [notification_id]

    sent = client.get(f"{CREATE_URL}/{notification_id}", **_auth_headers()).json()
    assert sent["status"] == Notification.Status.SENT
    assert [d["channel"] for d in sent["dispatches"]] == ["alimtalk"]

    # 다시 스캔해도 같은 알림이 중복 발송되지 않는다.
    again = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert again.json()["count"] == 0


@pytest.mark.django_db
def test_alimtalk_failure_falls_back_to_sms(client):
    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    with override_settings(NOTIFICATION_FAKE_FAILING_CHANNELS=["alimtalk"]):
        response = client.post(
            CREATE_URL,
            data={
                "recipient_id": user.id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_auth_headers(),
        )

    body = response.json()
    assert body["status"] == Notification.Status.SENT
    channels = [(d["channel"], d["status"]) for d in body["dispatches"]]
    assert channels == [("alimtalk", "failed"), ("sms", "sent")]
    assert body["dispatches"][0]["failure_reason"] != ""


@pytest.mark.django_db
def test_all_channels_failing_marks_notification_failed(client):
    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    with override_settings(NOTIFICATION_FAKE_FAILING_CHANNELS=["alimtalk", "sms", "lms"]):
        response = client.post(
            CREATE_URL,
            data={
                "recipient_id": user.id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_auth_headers(),
        )

    body = response.json()
    assert body["status"] == Notification.Status.FAILED
    assert [d["channel"] for d in body["dispatches"]] == ["alimtalk", "sms", "lms"]
    assert all(d["status"] == "failed" for d in body["dispatches"])
    assert all(d["failure_reason"] for d in body["dispatches"])


@pytest.mark.django_db
def test_adapter_exception_falls_back_to_next_channel_and_is_recorded(client):
    """알림톡 어댑터가 실패 '응답'이 아니라 예외로 죽어도(타임아웃/5xx 흉내) SMS로
    넘어가야 하고, 죽은 시도 자체도 이력에 남아야 한다(코드리뷰 지적 #1)."""

    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    with override_settings(NOTIFICATION_FAKE_RAISING_CHANNELS=["alimtalk"]):
        response = client.post(
            CREATE_URL,
            data={
                "recipient_id": user.id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_auth_headers(),
        )

    body = response.json()
    # 예외로 죽었는데도 Notification 이 QUEUED 에 멈추지 않고 SENT 까지 갔다.
    assert body["status"] == Notification.Status.SENT
    channels = [(d["channel"], d["status"]) for d in body["dispatches"]]
    assert channels == [("alimtalk", "failed"), ("sms", "sent")]
    # 예외 자체가 실패사유로 보존된다 — 발송 이력에 구멍이 없다.
    assert "FakeAdapterCrashed" in body["dispatches"][0]["failure_reason"]


@pytest.mark.django_db
def test_batch_of_due_notifications_is_not_stranded_by_a_crashing_channel(client):
    """대체발송 체인의 모든 채널이 예외로 죽어도(과거였다면 배치 전체가 멈췄다) 야간
    큐에 쌓인 여러 건이 전부 처리되고 아무 것도 QUEUED 에 갇히지 않는다
    (코드리뷰 지적 #1/#2)."""

    _freeze(datetime(2026, 1, 10, 23, 0, tzinfo=KST))
    ids = []
    for i in range(3):
        user = _make_user(f"batch-dev-{i}")
        created = client.post(
            CREATE_URL,
            data={
                "recipient_id": user.id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_auth_headers(),
        ).json()
        assert created["status"] == Notification.Status.DEFERRED
        ids.append(created["id"])

    _freeze(datetime(2026, 1, 11, 8, 0, tzinfo=KST))
    with override_settings(NOTIFICATION_FAKE_RAISING_CHANNELS=["alimtalk", "sms", "lms"]):
        response = client.post(DISPATCH_DUE_URL, **_auth_headers())

    body = response.json()
    assert body["count"] == 3
    assert sorted(body["dispatched_ids"]) == sorted(ids)

    for nid in ids:
        detail = client.get(f"{CREATE_URL}/{nid}", **_auth_headers()).json()
        # 전부 실패로 끝났을 뿐, 하나도 QUEUED 에 갇혀있지 않다.
        assert detail["status"] == Notification.Status.FAILED
        assert len(detail["dispatches"]) == 3

    # 재스캔해도 더 처리할 것이 없다 — 아무 것도 DEFERRED 로 남아있지 않다.
    rescan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert rescan.json()["count"] == 0


@pytest.mark.django_db
def test_delayed_scan_re_defers_instead_of_sending_during_quiet_hours(client):
    """스캔이 크게 지연돼 처리 시점에 다시 야간(21~08시)로 들어와 있으면, 발송 시각이
    지났다는 이유만으로 그 순간 내보내면 안 된다 — 발송 직전에 다시 검사해 다음
    08시로 재연기해야 한다(코드리뷰 지적 #3, ADR-0010)."""

    _freeze(datetime(2026, 1, 10, 23, 0, tzinfo=KST))
    user = _make_user()

    created = client.post(
        CREATE_URL,
        data={"recipient_id": user.id, "notification_type": NotificationType.DEADLINE_REMINDER},
        content_type="application/json",
        **_auth_headers(),
    ).json()
    assert created["status"] == Notification.Status.DEFERRED
    notification_id = created["id"]
    first_scheduled_for = created["scheduled_for"]

    # 다음 날 08시가 아니라, 스캔이 지연돼 그날 23:30에야 처리된다 — 이미 다시 야간이다.
    _freeze(datetime(2026, 1, 11, 23, 30, tzinfo=KST))
    delayed_scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert delayed_scan.json()["count"] == 0  # 재연기됐을 뿐, 발송되지 않았다.

    still_deferred = client.get(f"{CREATE_URL}/{notification_id}", **_auth_headers()).json()
    assert still_deferred["status"] == Notification.Status.DEFERRED
    assert still_deferred["dispatches"] == []
    assert still_deferred["scheduled_for"] > first_scheduled_for

    # 그 다음 날 08시가 되면 그제서야 실제로 발송된다.
    _freeze(datetime(2026, 1, 12, 8, 0, tzinfo=KST))
    final_scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert final_scan.json()["count"] == 1

    final = client.get(f"{CREATE_URL}/{notification_id}", **_auth_headers()).json()
    assert final["status"] == Notification.Status.SENT


@pytest.mark.django_db
def test_creating_notification_with_unknown_type_returns_422_not_500(client):
    """모르는 notification_type 문자열은 NOTIFICATION_TYPE_FLAGS[...] 에서 KeyError로
    500이 나던 것을, 스키마 검증으로 422까지만 가게 한다(코드리뷰 지적 #5)."""

    user = _make_user()

    response = client.post(
        CREATE_URL,
        data={"recipient_id": user.id, "notification_type": "bogus"},
        content_type="application/json",
        **_auth_headers(),
    )

    assert response.status_code == 422
