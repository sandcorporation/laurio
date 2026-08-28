"""Notification 내부 엔드포인트.

이 티켓(#18)은 Notification 기반만 세운다 — 실제 Contest 라이프사이클 이벤트에서
Notification 을 만드는 것은 #19(다른 체인) 소관이다. 그때까지는 이 내부 엔드포인트가
"어떤 계기로 Notification 이 하나 필요하다"는 것을 대신하는 진입점이며, 동시에 이
티켓의 HTTP 테스트 시임이기도 하다.

core 의 내부 틱 엔드포인트와 같은 `InternalAuth` 를 쓴다 — 둘 다 사람이 아니라 운영
인프라(또는 아직 없는 상위 도메인 로직)가 호출하는 진입점이기 때문이다.
"""

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from core.auth import InternalAuth

from .models import Notification, NotificationType
from .services import create_notification, dispatch_due_notifications

router = Router(tags=["internal", "notifications"], auth=InternalAuth())


class CreateNotificationIn(Schema):
    recipient_id: int
    notification_type: str


class DispatchOut(Schema):
    id: int
    channel: str
    status: str
    attempted_at: str
    failure_reason: str


class NotificationOut(Schema):
    id: int
    notification_type: str
    is_transactional: bool
    is_promotional: bool
    status: str
    scheduled_for: str | None
    created_at: str
    dispatches: list[DispatchOut]


def _serialize(notification: Notification) -> dict:
    return {
        "id": notification.pk,
        "notification_type": notification.notification_type,
        "is_transactional": notification.is_transactional,
        "is_promotional": notification.is_promotional,
        "status": notification.status,
        "scheduled_for": (
            notification.scheduled_for.isoformat() if notification.scheduled_for else None
        ),
        "created_at": notification.created_at.isoformat(),
        "dispatches": [
            {
                "id": d.pk,
                "channel": d.channel,
                "status": d.status,
                "attempted_at": d.attempted_at.isoformat(),
                "failure_reason": d.failure_reason,
            }
            for d in notification.dispatches.all()
        ],
    }


@router.post("", response=NotificationOut)
def create(request, payload: CreateNotificationIn):
    recipient = get_object_or_404(get_user_model(), pk=payload.recipient_id)
    notification = create_notification(
        recipient=recipient, notification_type=payload.notification_type
    )
    return _serialize(notification)


# 정적 경로("/dispatch-due", "/types/")는 반드시 "/{notification_id}" 보다 먼저
# 등록한다. django-ninja/Django의 URL 매칭은 등록 순서를 따르므로, 동적 경로가
# 먼저 있으면 "dispatch-due" 같은 문자열이 그 경로에 먼저 매치해 405를 낸다.
@router.post("/dispatch-due")
def dispatch_due(request):
    """야간 연기 큐를 스캔해 발송 시각이 지난 것을 발송한다.

    Celery beat 틱과 별개의 진입점이다 — 틱(#3)은 상태 전이 스캔 전반을 다루고, 이
    엔드포인트는 Notification 야간 큐에 특화된 스캔이다. 필요하면 나중에 같은 beat
    스케줄에 나란히 등록하면 된다.
    """

    dispatched_ids = dispatch_due_notifications()
    return {"count": len(dispatched_ids), "dispatched_ids": dispatched_ids}


@router.get("/types/")
def list_types(request):
    from .models import NOTIFICATION_TYPE_FLAGS

    return [
        {"value": value, "label": label, **NOTIFICATION_TYPE_FLAGS[value]}
        for value, label in NotificationType.choices
    ]


@router.get("/{int:notification_id}", response=NotificationOut)
def retrieve(request, notification_id: int):
    notification = get_object_or_404(Notification, pk=notification_id)
    return _serialize(notification)
