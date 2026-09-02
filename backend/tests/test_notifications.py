"""Notification 기반 — 어댑터 · 거래성/광고성 · 야간 연기 · 대체발송 (티켓 17, #18).

이 프로젝트의 유일한 테스트 시임은 HTTP다. User·NotificationOptIn·ClockOverride를
ORM으로 직접 만드는 것은 픽스처 준비일 뿐이고(test_admin.py가 유저를
create_superuser로 만드는 것과 같은 성격), 실제 동작 — 발송되는지, 야간이면
연기되는지, 대체발송이 되는지 — 은 전부 `/api/internal/notifications*` HTTP
엔드포인트를 통해서만 확인한다.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings

from accounts.models import PhoneContact
from core.models import ClockOverride
from notifications.models import (
    Notification,
    NotificationDispatch,
    NotificationOptIn,
    NotificationType,
)

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
def test_broken_adapter_dotted_path_falls_back_instead_of_500ing(client):
    """NOTIFICATION_ALIMTALK_ADAPTER가 존재하지 않는 dotted path를 가리켜도(운영
    배포에서 아직 구현 안 된 실제 벤더 어댑터를 잘못 설정한 경우를 흉내낸다)
    create_notification 자체가 500으로 죽으면 안 된다(코디네이터 리뷰 지적 #23) —
    이전에는 adapter_factory() 호출이 try 밖에 있어서 import_string의
    ImportError가 그대로 빠져나가 발송 이력도 안 남고 Notification이 QUEUED에
    영원히 멈췄다. 지금은 .send() 가 예외로 죽는 것과 같은 경로로 잡혀 SMS로
    넘어가야 한다."""

    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    with override_settings(NOTIFICATION_ALIMTALK_ADAPTER="notifications.adapters.DoesNotExist"):
        response = client.post(
            CREATE_URL,
            data={
                "recipient_id": user.id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == Notification.Status.SENT
    channels = [(d["channel"], d["status"]) for d in body["dispatches"]]
    assert channels == [("alimtalk", "failed"), ("sms", "sent")]
    assert body["dispatches"][0]["failure_reason"]


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
def test_stuck_queued_notification_is_recovered_by_a_later_scan(client):
    """DEFERRED -> QUEUED 선점 뒤 발송 시도 도중 죽으면(DB 장애 등, 어댑터 예외와는
    다른 종류의 실패) 그 행은 QUEUED에 멈춘다 — 예전 스캐너는 DEFERRED만 다시
    주웠으므로 이 행은 영원히 재시도되지 않았다(#10 리뷰 지적: _attempt_dispatch의
    자기 docstring이 막는다고 주장하던 바로 그 시나리오).

    "죽었다"는 걸 실제로 재현하려면 이 앱의 유일한 시임(HTTP)을 우회해야 하는데,
    이 파일의 관례대로 그건 픽스처 준비로만 쓴다 — 직접 검증하는 것은 이 상태에서
    실제로 무슨 일이 일어나는지(다음 스캔이 이 행을 찾아 발송까지 끝내는지)뿐이고,
    그건 전부 `/api/internal/notifications/dispatch-due` 를 통해서만 확인한다.
    """

    user = _make_user()
    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=stuck_at,
        created_at=stuck_at,
    )
    assert notification.dispatches.count() == 0  # 발송 시도 흔적이 전혀 없다 — 죽은 것.

    # 5분보다 짧게 지난 시점에는 아직 "정상적으로 진행 중"으로 보고 건드리지 않는다
    # (안 그러면 지금 막 즉시발송 경로로 처리 중인 정상 QUEUED까지 이중 발송하게 된다).
    _freeze(stuck_at + timedelta(minutes=1))
    too_soon = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert too_soon.json()["count"] == 0
    still_stuck = client.get(f"{CREATE_URL}/{notification.id}", **_auth_headers()).json()
    assert still_stuck["status"] == Notification.Status.QUEUED
    assert still_stuck["dispatches"] == []

    # STUCK_QUEUED_THRESHOLD(5분)를 넘기면 다음 스캔이 이 행을 다시 집어 끝까지
    # 처리한다 — QUEUED에 영원히 갇히지 않는다.
    _freeze(stuck_at + timedelta(minutes=10))
    recovery_scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    body = recovery_scan.json()
    assert body["count"] == 1
    assert body["dispatched_ids"] == [notification.id]

    recovered = client.get(f"{CREATE_URL}/{notification.id}", **_auth_headers()).json()
    assert recovered["status"] == Notification.Status.SENT
    assert len(recovered["dispatches"]) >= 1

    # 재스캔해도 더 처리할 것이 없다 — 회복된 행은 다시 잡히지 않는다.
    rescan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert rescan.json()["count"] == 0


@pytest.mark.django_db
def test_reclaimed_channel_already_sent_is_not_retried_to_avoid_double_charge(client):
    """#51 코드리뷰 지적 7: 벤더 발송이 실제로 성공한 '뒤' 이 채널을 SENT로
    확정하기 '전'에 프로세스가 죽으면, 예전 코드는 재선점 시 알림톡부터 다시
    시도해 이미 성공한 채널까지 다시 벤더를 불렀다 — 실물 어댑터는 실제로
    과금되므로 이것이 유료 재발송 사고다. 이미 SENT인 채널은 다시 시도하지
    않고 그 성공을 그대로 확정해야 한다."""

    user = _make_user()
    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=stuck_at,
        created_at=stuck_at,
    )
    # alimtalk는 시도했다가 실패했고, sms는 실제로 성공했지만 그 직후 죽어서
    # Notification.status가 SENT로 갱신되지 못한 채 QUEUED에 멈췄다고 가정한다.
    NotificationDispatch.objects.create(
        notification=notification,
        channel="alimtalk",
        status=NotificationDispatch.Status.FAILED,
        attempted_at=stuck_at,
        failure_reason="fake-alimtalk-forced-failure",
    )
    NotificationDispatch.objects.create(
        notification=notification,
        channel="sms",
        status=NotificationDispatch.Status.SENT,
        attempted_at=stuck_at,
        failure_reason="",
    )

    _freeze(stuck_at + timedelta(minutes=10))
    recovery_scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert recovery_scan.json()["count"] == 1

    recovered = client.get(f"{CREATE_URL}/{notification.id}", **_auth_headers()).json()
    assert recovered["status"] == Notification.Status.SENT
    # sms 채널의 발송 시도는 여전히 하나뿐이다 — 재선점이 두 번째 sms 시도를
    # 새로 만들지 않았다(다시 벤더를 부르지 않았다는 뜻).
    sms_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "sms"]
    assert len(sms_dispatches) == 1
    assert sms_dispatches[0]["status"] == "sent"
    # alimtalk도 원래의 FAILED 기록 하나뿐이다(#51 3차 코드리뷰 지적 5) — sms
    # 가 이미 SENT라는 사실은 채널 순서(알림톡→SMS→LMS)를 따라가며 발견하는
    # 게 아니라 반복문에 들어가기 전에 전체를 한 번에 확인하므로, "정상적인
    # 실패라 재시도 대상"인 alimtalk라도 다시 벤더를 부르지 않는다. 예전
    # 버그(순서대로만 확인)라면 알림톡이 먼저 재시도돼(Fake 알림톡은 기본
    # 성공한다) 이 채널에 새 SENT 기록이 추가되고, sms의 기존 성공과 합쳐
    # 같은 알림이 두 채널로 중복 도달했을 것이다.
    alimtalk_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "alimtalk"]
    assert len(alimtalk_dispatches) == 1
    assert alimtalk_dispatches[0]["status"] == "failed"
    # lms는 아예 시도되지 않았다 — sms의 기존 성공으로 바로 종결됐다.
    assert all(d["channel"] != "lms" for d in recovered["dispatches"])


@pytest.mark.django_db
def test_reclaimed_channel_still_pending_is_skipped_not_retried(client):
    """#51 코드리뷰 지적 7: 벤더 응답을 받기 '전'에(성공인지 실패인지 확정하기
    전에) 죽으면 그 채널의 기록은 PENDING으로 남는다 — 벤더가 실제로는
    성공했을 수도 있으므로, 재선점이 이 채널을 다시 시도하면 중복 과금
    가능성이 있다. PENDING인 채널은 건너뛰고 다음 채널로 넘어가야 한다."""

    user = _make_user()
    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=stuck_at,
        created_at=stuck_at,
    )
    NotificationDispatch.objects.create(
        notification=notification,
        channel="alimtalk",
        status=NotificationDispatch.Status.PENDING,
        attempted_at=stuck_at,
        failure_reason="",
    )

    _freeze(stuck_at + timedelta(minutes=10))
    recovery_scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert recovery_scan.json()["count"] == 1

    recovered = client.get(f"{CREATE_URL}/{notification.id}", **_auth_headers()).json()
    # alimtalk는 재시도로 새 시도가 추가되지 않았다 — 다만 PENDING으로 영원히
    # 남지 않고, "왜 재시도하지 않았는지"를 설명하는 INDETERMINATE로
    # 확정된다(#51 3차 코드리뷰 지적 1) — FAILED로 확정하면 사유는 남지만
    # 다음 재선점이 "안전하게 재시도해도 되는 실패"로 오인해 이미 벤더가
    # 성공시켰을 수 있는 채널에 다시 벤더를 불러 재과금·중복 도달을 만든다
    # (2차 수정이 되돌렸던 1차 수정의 사고). 사유가 빈 PENDING이
    # /api/notifications/me에 영구히 노출되는 것도 여전히 막는다.
    alimtalk_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "alimtalk"]
    assert len(alimtalk_dispatches) == 1
    assert alimtalk_dispatches[0]["status"] == "indeterminate"
    assert alimtalk_dispatches[0]["failure_reason"] != ""
    # sms로 넘어가 정상적으로 발송을 끝냈다(기본 Fake sms는 성공한다).
    sms_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "sms"]
    assert len(sms_dispatches) == 1
    assert sms_dispatches[0]["status"] == "sent"
    assert recovered["status"] == Notification.Status.SENT


@pytest.mark.django_db
def test_an_already_indeterminate_channel_is_never_retried_across_repeated_crashes(client):
    """#51 3차 코드리뷰 지적 1: 크래시가 두 번 겹치는 상황을 그대로 재현한다 —
    alimtalk는 이미 이전 재선점에서 INDETERMINATE로 확정됐고(PENDING이었다가
    "재시도 안 함"으로 넘어간 채널), sms는 이번에 처음 PENDING인 채로
    죽었다고 가정한다. 재선점은 alimtalk를 다시 건드리지 않고(새 시도도,
    상태·사유 변경도 없다), sms는 INDETERMINATE로 안전하게 넘기고, lms로
    넘어가 정상적으로 발송을 끝내야 한다. INDETERMINATE가 FAILED처럼
    "재시도해도 되는 실패"로 다시 읽히면 alimtalk에 다시 벤더를 불러
    재과금·중복 도달이 생긴다."""

    user = _make_user()
    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=stuck_at,
        created_at=stuck_at,
    )
    original_alimtalk_reason = (
        "이전 시도가 벤더 응답을 받기 전에 중단됐다 — 실제로 성공했을 수 있어 "
        "중복 과금을 피하기 위해 재시도하지 않았다."
    )
    NotificationDispatch.objects.create(
        notification=notification,
        channel="alimtalk",
        status=NotificationDispatch.Status.INDETERMINATE,
        attempted_at=stuck_at,
        failure_reason=original_alimtalk_reason,
    )
    NotificationDispatch.objects.create(
        notification=notification,
        channel="sms",
        status=NotificationDispatch.Status.PENDING,
        attempted_at=stuck_at,
        failure_reason="",
    )

    _freeze(stuck_at + timedelta(minutes=10))
    recovery_scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert recovery_scan.json()["count"] == 1

    recovered = client.get(f"{CREATE_URL}/{notification.id}", **_auth_headers()).json()

    # alimtalk는 완전히 그대로다 — 새 시도도, 상태·사유 변경도 없다(벤더를
    # 다시 부르지 않았다는 뜻).
    alimtalk_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "alimtalk"]
    assert len(alimtalk_dispatches) == 1
    assert alimtalk_dispatches[0]["status"] == "indeterminate"
    assert alimtalk_dispatches[0]["failure_reason"] == original_alimtalk_reason

    # sms는 이번에 INDETERMINATE로 안전하게 확정됐다 — 새 시도가 추가되지 않았다.
    sms_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "sms"]
    assert len(sms_dispatches) == 1
    assert sms_dispatches[0]["status"] == "indeterminate"
    assert sms_dispatches[0]["failure_reason"] != ""

    # lms로 넘어가 정상적으로 발송을 끝냈다.
    lms_dispatches = [d for d in recovered["dispatches"] if d["channel"] == "lms"]
    assert len(lms_dispatches) == 1
    assert lms_dispatches[0]["status"] == "sent"
    assert recovered["status"] == Notification.Status.SENT


@pytest.mark.django_db
def test_stuck_queued_recovery_re_defers_instead_of_sending_during_quiet_hours(client):
    """멈춘 QUEUED를 재선점하는 경로도, DEFERRED 재선점 경로와 똑같이 발송 직전에
    다시 야간인지 확인해야 한다 — 재선점 시점이 마침 야간이면 그대로 내보내지 않고
    다음 날 08시로 연기한다(ADR-0010)."""

    user = _make_user()
    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=stuck_at,
        created_at=stuck_at,
    )

    # 5분 이상 지났고, 지금은 야간(23:00)이다.
    _freeze(datetime(2026, 1, 10, 23, 0, tzinfo=KST))
    scan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert scan.json()["count"] == 0  # 재연기됐을 뿐, 발송되지 않았다.

    deferred = client.get(f"{CREATE_URL}/{notification.id}", **_auth_headers()).json()
    assert deferred["status"] == Notification.Status.DEFERRED
    assert deferred["dispatches"] == []
    assert deferred["scheduled_for"] is not None


@pytest.mark.django_db
def test_dispatch_scan_stops_early_when_the_time_budget_is_exhausted(client):
    """#51 코드리뷰 지적 6: 실물 어댑터는 진짜 네트워크 호출이라 배치가 커지면
    gunicorn/Celery의 30초 요청 타임아웃을 넘길 수 있다. 이 스캔은 시간
    예산(DUE_SCAN_TIME_BUDGET_SECONDS)을 넘기면 나머지 행을 이번에는 건드리지
    않고 다음 스캔(60초 뒤)에 넘겨야 한다 — ADR-0010 "연기하되 버리지
    않는다"와 같은 원칙이다."""

    from unittest.mock import patch

    user = _make_user()
    as_of = datetime(2026, 1, 10, 14, 0, tzinfo=KST)

    notifications = [
        Notification.objects.create(
            recipient=user,
            notification_type=NotificationType.DEADLINE_REMINDER,
            is_transactional=True,
            is_promotional=False,
            status=Notification.Status.DEFERRED,
            scheduled_for=as_of,
            created_at=as_of,
        )
        for _ in range(3)
    ]
    _freeze(as_of)

    # 첫 monotonic() 호출이 DEFERRED 몫의 마감시각 계산(0.0+6=6.0)이고, 두
    # 번째(첫 행 처리 전)는 아직 그 안이라 진행하지만, 세 번째(두 번째 행
    # 처리 전)는 이미 넘긴 것으로 만든다 — 그래서 딱 한 건만 처리되고
    # DEFERRED 루프가 멈춘다. 네 번째 호출은 stuck-QUEUED 몫의 마감시각을
    # DEFERRED 루프가 끝난 시점부터 새로 계산하는 호출이다(stuck_queued_ids가
    # 비어 있어 그 루프 자체는 반복하지 않는다).
    with patch(
        "notifications.services.time_module.monotonic", side_effect=[0.0, 0.0, 100.0, 100.0]
    ):
        response = client.post(DISPATCH_DUE_URL, **_auth_headers())

    body = response.json()
    assert body["count"] == 1  # 셋 중 하나만 처리됐다 — 나머지는 건드리지 않았다.

    statuses = {
        n.id: client.get(f"{CREATE_URL}/{n.id}", **_auth_headers()).json()["status"]
        for n in notifications
    }
    processed = [nid for nid, status in statuses.items() if status == Notification.Status.SENT]
    still_deferred = [
        nid for nid, status in statuses.items() if status == Notification.Status.DEFERRED
    ]
    assert len(processed) == 1
    # 나머지 둘은 상태를 건드리지 않았다 — 다음 스캔이 안전하게 다시 집을 수 있다.
    assert len(still_deferred) == 2

    # 다음 스캔(시간 제약 없이)이 남은 것을 마저 처리한다.
    rescan = client.post(DISPATCH_DUE_URL, **_auth_headers())
    assert rescan.json()["count"] == 2


@pytest.mark.django_db
def test_stuck_queued_recovery_is_not_starved_when_deferred_uses_its_share_of_the_budget(client):
    """#51 2차 코드리뷰 지적 1: 이전에는 DEFERRED 루프와 stuck-QUEUED 루프가
    시간 예산 하나를 공유하고 DEFERRED가 먼저 돌아, DEFERRED가 예산을 다
    쓰면 그 자리에서 곧장 반환해 stuck-QUEUED 재선점 루프가 아예 실행되지
    않았다 — PENDING으로 죽은 행을 되살리는 유일한 경로가 매 스캔 굶주렸다.
    이제 두 루프는 예산을 절반씩 나눠 쓰므로, DEFERRED가 자기 몫을 다 써도
    stuck-QUEUED는 여전히 시도된다."""

    from unittest.mock import patch

    user = _make_user()
    as_of = datetime(2026, 1, 10, 14, 0, tzinfo=KST)

    deferred_notifications = [
        Notification.objects.create(
            recipient=user,
            notification_type=NotificationType.DEADLINE_REMINDER,
            is_transactional=True,
            is_promotional=False,
            status=Notification.Status.DEFERRED,
            scheduled_for=as_of,
            created_at=as_of,
        )
        for _ in range(2)
    ]
    stuck_notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=as_of,
        created_at=as_of,
    )
    # 벤더 발송이 성공한 뒤 SENT 확정 전에 죽은 것을 흉내낸다 — stuck-QUEUED
    # 재선점만이 이 행을 다시 찾아 결론(FAILED로 확정, #51 2차 코드리뷰
    # 지적 6)을 남길 수 있다.
    NotificationDispatch.objects.create(
        notification=stuck_notification,
        channel="alimtalk",
        status=NotificationDispatch.Status.PENDING,
        attempted_at=as_of,
        failure_reason="",
    )
    # STUCK_QUEUED_THRESHOLD(5분)가 지나야 stuck-QUEUED 재선점 대상이 된다 —
    # claimed_at=as_of인 채로 스캔 시각도 as_of면 아직 "막 처리 중"으로 보고
    # 건드리지 않는다.
    _freeze(as_of + timedelta(minutes=10))

    # 1번째 호출은 deferred_deadline 계산(0.0+6=6.0). 2번째(첫 행 처리 전)는
    # 아직 여유(0.0<6.0)라 진행하지만, 3번째(두 번째 행 처리 전)는 이미
    # 초과(7.0>=6.0)라 멈춘다. DEFERRED 루프가 끝난 "그 시점"(4번째 호출,
    # 7.0)부터 stuck_deadline을 새로 절반 받는다(7.0+6=13.0) — DEFERRED가
    # 자기 몫을 다 썼어도 stuck-QUEUED 루프 진입 시점(5번째 호출, 7.0)은
    # 그 새 마감(13.0) 안이라 실제로 시도된다.
    with patch(
        "notifications.services.time_module.monotonic",
        side_effect=[0.0, 0.0, 7.0, 7.0, 7.0],
    ):
        response = client.post(DISPATCH_DUE_URL, **_auth_headers())

    assert response.json()["count"] == 2  # deferred 하나 + stuck 하나.

    stuck_recovered = client.get(
        f"{CREATE_URL}/{stuck_notification.id}", **_auth_headers()
    ).json()
    assert stuck_recovered["status"] == Notification.Status.SENT

    deferred_statuses = [
        client.get(f"{CREATE_URL}/{n.id}", **_auth_headers()).json()["status"]
        for n in deferred_notifications
    ]
    assert deferred_statuses.count(Notification.Status.SENT) == 1
    assert deferred_statuses.count(Notification.Status.DEFERRED) == 1


@pytest.mark.django_db
def test_stuck_queued_still_gets_its_share_even_when_a_single_slow_deferred_row_blows_the_original_full_budget(
    client,
):
    """#51 3차 코드리뷰 지적 3: 예산을 스캔 시작 시점에 통째로 고정해 두면
    (deferred 절반 + stuck 절반을 둘 다 scan_start 기준으로), 진행 중이던
    DEFERRED 행 하나가 최대 15초(3채널 × 5초)를 써버리는 것만으로 stuck 몫의
    마감시각(scan_start + 전체 예산)이 이미 지나 버린다 — 벤더가 느려서
    stuck 행이 생기는 바로 그 상황에서 stuck-QUEUED 루프가 진입하자마자
    0초짜리 예산을 받는 모순이다. 이 테스트는 그 "느린 한 행" 시나리오를
    monotonic()에 큰 시간 도약으로 직접 흉내낸다 — 이전 버전의 고정 4개
    값짜리 테스트는 이 경로를 타지 않았다."""

    from unittest.mock import patch

    user = _make_user()
    as_of = datetime(2026, 1, 10, 14, 0, tzinfo=KST)

    deferred_notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.DEFERRED,
        scheduled_for=as_of,
        created_at=as_of,
    )
    stuck_notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.DEADLINE_REMINDER,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.QUEUED,
        claimed_at=as_of,
        created_at=as_of,
    )
    NotificationDispatch.objects.create(
        notification=stuck_notification,
        channel="alimtalk",
        status=NotificationDispatch.Status.PENDING,
        attempted_at=as_of,
        failure_reason="",
    )
    _freeze(as_of + timedelta(minutes=10))

    # 1번째 호출: deferred_deadline = 0.0 + 6.0 = 6.0. 2번째(단 하나뿐인
    # DEFERRED 행 처리 전): 0.0 < 6.0이라 진행한다 — 그 행 처리 자체가
    # "15초짜리 벤더 지연"을 흉내내, 다음 monotonic() 호출은 15.0을 반환한다
    # (원래 방식이었다면 stuck_deadline = scan_start(0.0) + 전체 예산(12.0)
    # = 12.0으로 이미 고정돼 있었을 것이므로, 15.0 >= 12.0으로 stuck 루프가
    # 진입하자마자 멈췄을 것이다). 3번째 호출(stuck_deadline을 새로 계산하는
    # 시점) = 15.0 → stuck_deadline = 15.0 + 6.0 = 21.0. 4번째 호출(stuck
    # 행 처리 전) = 15.0 < 21.0이므로 실제로 처리된다.
    with patch(
        "notifications.services.time_module.monotonic",
        side_effect=[0.0, 0.0, 15.0, 15.0],
    ):
        response = client.post(DISPATCH_DUE_URL, **_auth_headers())

    assert response.json()["count"] == 2  # deferred 하나 + stuck 하나 — 둘 다 처리됐다.

    stuck_recovered = client.get(
        f"{CREATE_URL}/{stuck_notification.id}", **_auth_headers()
    ).json()
    assert stuck_recovered["status"] == Notification.Status.SENT

    deferred_recovered = client.get(
        f"{CREATE_URL}/{deferred_notification.id}", **_auth_headers()
    ).json()
    assert deferred_recovered["status"] == Notification.Status.SENT


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


# --- 실물 알리고 어댑터: 알림톡 실패 → SMS 대체발송이 HTTP 시임을 통해 실제로 동작한다 (#51) ---


def _aligo_response(status_code: int, json_body: dict | None = None, text: str = "") -> Mock:
    import requests

    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text if json_body is None else json.dumps(json_body)
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


@pytest.mark.django_db
def test_real_alimtalk_adapter_falls_back_to_real_sms_adapter(client):
    """#51 AC: 알림톡 어댑터가 존재하고, 승인 전에는 실패를 돌려줘 SMS/LMS
    대체발송 경로가 실제로 동작한다 — Fake가 아니라 실제로 배포에 쓸 두
    클래스(AligoAlimtalkAdapter/AligoSmsAdapter)를 그대로 붙여서 확인한다."""

    from unittest.mock import patch

    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()
    PhoneContact.objects.create(user=user, phone_number="01011112222")

    with override_settings(
        NOTIFICATION_ALIMTALK_ADAPTER="notifications.adapters_aligo.AligoAlimtalkAdapter",
        NOTIFICATION_SMS_ADAPTER="notifications.adapters_aligo.AligoSmsAdapter",
        ALIGO_API_KEY="test-api-key",
        ALIGO_USER_ID="test-user-id",
        ALIGO_SENDER_PHONE_NUMBER="01000000000",
    ):
        with patch("notifications.adapters_aligo.requests.post") as mock_post:
            mock_post.return_value = _aligo_response(200, {"result_code": "1", "message": "success"})
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
    assert "사전심사" in body["dispatches"][0]["failure_reason"]
    # 알림톡은 벤더를 전혀 부르지 않았다 — SMS 시도 한 번만 실제로 요청이 나갔다.
    mock_post.assert_called_once()


@pytest.mark.django_db
def test_missing_vendor_credentials_falls_through_every_channel_without_crashing(client):
    """#51 AC: 벤더가 응답하지 않아도(여기서는 자격증명 자체가 없어 어댑터
    생성 자체가 실패하는 극단적인 경우) 통지 발송 스캔 전체가 죽지 않는다 —
    세 채널 다 실패해도 create_notification은 500이 아니라 FAILED 상태로
    정상 종결되고, 실패 사유가 전부 보존된다."""

    _freeze(datetime(2026, 1, 10, 14, 0, tzinfo=KST))
    user = _make_user()

    with override_settings(
        NOTIFICATION_ALIMTALK_ADAPTER="notifications.adapters_aligo.AligoAlimtalkAdapter",
        NOTIFICATION_SMS_ADAPTER="notifications.adapters_aligo.AligoSmsAdapter",
        NOTIFICATION_LMS_ADAPTER="notifications.adapters_aligo.AligoLmsAdapter",
        ALIGO_API_KEY="",
        ALIGO_USER_ID="",
        ALIGO_SENDER_PHONE_NUMBER="",
    ):
        response = client.post(
            CREATE_URL,
            data={
                "recipient_id": user.id,
                "notification_type": NotificationType.DEADLINE_REMINDER,
            },
            content_type="application/json",
            **_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == Notification.Status.FAILED
    assert [d["channel"] for d in body["dispatches"]] == ["alimtalk", "sms", "lms"]
    assert all(d["status"] == "failed" for d in body["dispatches"])
    assert all(d["failure_reason"] for d in body["dispatches"])
