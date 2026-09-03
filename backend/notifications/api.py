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

from accounts.middleware import jwt_auth
from core.auth import InternalAuth

from .models import Notification, NotificationType
from .services import create_notification

router = Router(tags=["internal", "notifications"], auth=InternalAuth())

# Sponsor(및 그 외 recipient) 본인이 자신의 발송 이력을 조회하는 사용자 대면
# 엔드포인트(#19 AC) — 위 `router`와 달리 InternalAuth가 아니라 jwt_auth를 쓴다.
public_router = Router(tags=["notifications"])

# GET /notifications/me 한 번이 돌려줄 수 있는 최대 건수(#19 리뷰 지적 5). 오래
# 진행된 Contest는 dispatches까지 함께 직렬화하는 이 응답이 무제한이면 요청이
# 느려지거나 타임아웃난다 — core.transitions.DEFAULT_BATCH_SIZE 등과 같은
# "무제한 스캔/응답을 만들지 않는다"는 이 코드베이스의 관용구를 조회 엔드포인트에도
# 그대로 적용한다.
NOTIFICATION_HISTORY_MAX_LIMIT = 100
NOTIFICATION_HISTORY_DEFAULT_LIMIT = 50


class CreateNotificationIn(Schema):
    recipient_id: int
    # NotificationType 로 타입을 고정해두면 django-ninja/pydantic 이 유형 값 자체를
    # 검증한다. str 이었다면 "bogus" 같은 값이 NOTIFICATION_TYPE_FLAGS[...] 조회에서
    # KeyError -> 500 으로 터졌다. 여기서 막으면 422 로 끝난다.
    notification_type: NotificationType
    # 이 알림이 무엇에 관한 것인지(대상 Contest, 금액 등)를 담는 구조화된 맥락(#19).
    # 내부 테스트/도구용 엔드포인트라 선택 입력이다 — 실제 lifecycle 연결은
    # notifications.lifecycle이 create_notification을 Python 레벨에서 직접 부른다.
    context: dict | None = None


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
    context: dict
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
        "context": notification.context or {},
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
        recipient=recipient,
        notification_type=payload.notification_type,
        context=payload.context,
    )
    return _serialize(notification)


# 정적 경로("/types/")는 반드시
# "/{notification_id}" 보다 먼저 등록한다. django-ninja/Django의 URL 매칭은 등록
# 순서를 따르므로, 동적 경로가 먼저 있으면 그 문자열들이 그 경로에 먼저 매치해
# 405를 낸다.
@public_router.get("/me", response=list[NotificationOut], auth=jwt_auth)
def list_my_notifications(
    request,
    limit: int = NOTIFICATION_HISTORY_DEFAULT_LIMIT,
    offset: int = 0,
):
    """로그인한 사용자(Sponsor 포함) 자신에게 발송된 Notification 이력.

    채널·시각·결과·실패사유가 담긴 dispatches를 포함해 그대로 노출한다 — ADR-0009가
    요구하는 "연락받은 적 없다"는 항의에 대한 방어선이 이 화면이다(#19 AC). 최신순
    으로, `limit`/`offset`으로 페이지를 넘긴다 — `limit`은
    NOTIFICATION_HISTORY_MAX_LIMIT을 넘지 않게 잘라낸다(#19 리뷰 지적 5).
    """

    limit = max(1, min(limit, NOTIFICATION_HISTORY_MAX_LIMIT))
    offset = max(0, offset)

    notifications = (
        Notification.objects.filter(recipient=request.auth_user)
        .prefetch_related("dispatches")
        .order_by("-created_at")[offset : offset + limit]
    )
    return [_serialize(n) for n in notifications]


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
