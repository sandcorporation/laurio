"""발송 실패 운영 경보(#1123) — `POST /api/internal/scans/notification-dispatch-alert` 하나로만 친다.

발송 이력 행은 ORM 으로 깐다(픽스처 준비). 웹훅은 `ops_metrics.alerts.post_webhook` 을 갈아끼운다."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.models import Notification, NotificationDispatch, NotificationType
from ops_metrics import alerts

URL = "/api/internal/scans/notification-dispatch-alert"
HOOK = "https://discord.invalid/api/webhooks/test"
EMAIL = "secret-person@example.com"


@pytest.fixture
def sent(monkeypatch, settings):
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = HOOK
    out: list[str] = []
    monkeypatch.setattr(alerts, "post_webhook", lambda url, content: out.append(content))
    return out


def _scan(client) -> dict:
    response = client.post(URL, HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN)
    assert response.status_code == 200, response.content
    return response.json()


def _notification(user, *, statuses, kind=NotificationType.CLASSROOM_SUBMISSION_SCORED, minutes_ago=5):
    at = timezone.now() - timedelta(minutes=minutes_ago)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=kind,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.SENT if "sent" in statuses else Notification.Status.FAILED,
        created_at=at,
    )
    for status in statuses:
        NotificationDispatch.objects.create(
            notification=notification,
            channel=NotificationDispatch.Channel.ALIMTALK,
            status=status,
            attempted_at=at,
            failure_reason=EMAIL if status == "failed" else "",
        )
    return notification


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="u1", email=EMAIL, password="x")


@pytest.mark.django_db
def test_failures_over_threshold_alert_once_then_resolve(client, user, sent):
    for _ in range(5):
        _notification(user, statuses=["failed", "sent"])  # 대체 채널로 닿아 수신자 0 은 아니다

    _scan(client)
    _scan(client)  # 같은 사건은 되풀이하지 않는다

    assert len(sent) == 1
    assert "notification-dispatch-failures 발생" in sent[0] and "5건" in sent[0] and "알림톡" in sent[0]
    assert EMAIL not in sent[0]

    NotificationDispatch.objects.all().update(attempted_at=timezone.now() - timedelta(hours=3))
    _scan(client)
    assert len(sent) == 2 and "해소" in sent[1]
    _scan(client)
    assert len(sent) == 2


@pytest.mark.django_db
def test_quiet_below_threshold(client, user, sent):
    for _ in range(4):
        _notification(user, statuses=["failed", "sent"])

    _scan(client)

    assert sent == []


@pytest.mark.django_db
def test_zero_reach_batch_alerts_with_type_and_count(client, user, sent):
    for _ in range(3):
        _notification(user, statuses=["failed"])

    _scan(client)

    texts = [s for s in sent if "notification-zero-reach 발생" in s]
    assert len(texts) == 1 and "3건" in texts[0]
    assert NotificationType.CLASSROOM_SUBMISSION_SCORED.label in texts[0]
    assert EMAIL not in texts[0]


@pytest.mark.django_db
def test_zero_reach_not_raised_when_someone_was_reached(client, user, sent):
    for _ in range(3):
        _notification(user, statuses=["failed"])
    _notification(user, statuses=["sent"])

    _scan(client)

    assert not any("zero-reach" in s for s in sent)


@pytest.mark.django_db
def test_unset_webhook_stays_silent(client, user, settings):
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = ""
    for _ in range(5):
        _notification(user, statuses=["failed"])

    body = _scan(client)

    assert body["rows"][0]["notification-dispatch-failures"] == "firing"
    assert _scan(client)["rows"] == []  # 바뀐 게 없으면 행도 없다
