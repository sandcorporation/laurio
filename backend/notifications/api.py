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
from core.clock import Clock

from .models import CLASSROOM_NOTIFICATION_TYPES, Notification, NotificationDispatch, NotificationType
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
    # 청중에 따라 값의 출처가 갈린다(#244) — `router`(내부/운영자)는
    # `NotificationDispatch.failure_reason` 원문을, `public_router`(수신자 본인의
    # `/notifications/me`)는 `_recipient_facing_reason`이 `status`만으로 만든
    # 사람이 읽는 문구를 낸다. 스키마 모양은 하나지만 값은 같은 필드가 아니다.
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
    # 수신자의 열람 여부(#230) — 발송 측 `status`와 독립인 축이다(위 `Notification.
    # read_at` 필드 독스트링). `null`이면 아직 안 읽었다는 뜻이다.
    read_at: str | None


class UnreadCountOut(Schema):
    count: int


class MarkAllReadOut(Schema):
    marked_count: int


# 수신자 화면(`/notifications/me`)에 낼 발송 실패 문구를 만드는 유일한 자리(#244).
# `NotificationDispatch.failure_reason`은 애초에 운영자용으로 쓰인 자유서술이라
# ADR 번호·과금 기준·벤더 원문 오류가 그대로 섞여 있다(adapters_aligo.py) —
# 그 문자열을 순화해 재사용하면 다음에 쓰는 사람이 또 내부 말을 적어 넣는
# 순간 다시 샌다. 그래서 원문은 전혀 들여다보지 않고 `status`만으로 정한다:
# 새 실패 사유가 앞으로 늘어도(운영자가 또 내부 말을 적어도) 이 매핑에 없으면
# 아래 기본값으로 떨어져 저절로 안전하다. 운영자용 원문은 그대로 `router`
# (`/api/internal/notifications*`)를 통해 여전히 볼 수 있다 — 이 함수는
# `public_router`에만 쓰인다.
_RECIPIENT_DISPATCH_REASONS: dict[str, str] = {
    NotificationDispatch.Status.PENDING: "발송을 시도하고 있습니다.",
    NotificationDispatch.Status.SENT: "",
    NotificationDispatch.Status.FAILED: "알 수 없는 이유로 도달하지 못했습니다.",
    NotificationDispatch.Status.INDETERMINATE: "발송 결과를 확인하지 못했습니다.",
}
# 위 매핑에 없는 상태가 생기더라도(예: 앞으로 새 Status가 추가돼도) 빈 문자열
# 대신 이 문구가 남는다 — AC: "사유를 모르는 실패도 이력에 남는다".
_RECIPIENT_DISPATCH_REASON_FALLBACK = "알 수 없는 이유로 도달하지 못했습니다."


def _recipient_facing_reason(dispatch: NotificationDispatch) -> str:
    return _RECIPIENT_DISPATCH_REASONS.get(dispatch.status, _RECIPIENT_DISPATCH_REASON_FALLBACK)


def _scope_by_classroom(qs, classroom_only: bool):
    """`/me`·`/unread-count`·`/mark-read` 셋이 공유하는 강의실 경계(#345).

    `classroom_only=True`(강의실 앱이 언제나 붙인다, #304)면 강의실 알림만
    남기고, `False`(공개 앱의 기본값)면 강의실 알림을 **뺀다** — 공개 앱은
    강의실 알림을 세지도 보이지도 읽음 처리하지도 않는다(CONTEXT.md
    「강의실 알림」). **목록·개수·모두읽음** 세 엔드포인트가 서로의 알림에
    닿지 않는 것은 이 분기 하나가 전부다 — 알림 하나를 지목하는
    `mark_one_read`·`mark_many_read`는 이 헬퍼를 쓰지 않는다(그쪽은 `id` 자체를
    `recipient=request.auth_user`로 좁히므로 유형 필터가 필요 없다)."""

    if classroom_only:
        return qs.filter(notification_type__in=CLASSROOM_NOTIFICATION_TYPES)
    return qs.exclude(notification_type__in=CLASSROOM_NOTIFICATION_TYPES)


def _serialize(notification: Notification, *, for_recipient: bool = False) -> dict:
    """`for_recipient=True`면 `public_router`(수신자 본인)용 — 채널별 시도
    시각·결과(ADR-0009가 요구하는 이력)는 그대로 두고 `failure_reason`만
    `_recipient_facing_reason`이 만든 문구로 바꾼다. 기본값(`False`)은
    `router`(내부/운영자)용으로, 원문 `failure_reason`을 그대로 낸다."""

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
                "failure_reason": (
                    _recipient_facing_reason(d) if for_recipient else d.failure_reason
                ),
            }
            for d in notification.dispatches.all()
        ],
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
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
    classroom_only: bool = False,
):
    """로그인한 사용자(Sponsor 포함) 자신에게 발송된 Notification 이력.

    채널·시각·결과·실패사유가 담긴 dispatches를 포함해 그대로 노출한다 — ADR-0009가
    요구하는 "연락받은 적 없다"는 항의에 대한 방어선이 이 화면이다(#19 AC). 최신순
    으로, `limit`/`offset`으로 페이지를 넘긴다 — `limit`은
    NOTIFICATION_HISTORY_MAX_LIMIT을 넘지 않게 잘라낸다(#19 리뷰 지적 5).

    `classroom_only=true`면 강의실 알림(`CLASSROOM_NOTIFICATION_TYPES`)만
    돌려준다(#304) — 강의실 화면이 이 값으로 부른다. 기본값(`False`)은 강의실
    알림을 **뺀** 나머지다(#345) — 공개 앱은 강의실 알림을 세지도 보이지도
    않는다(CONTEXT.md 「강의실 알림」). 두 앱이 계정을 공유해도 서로의 알림이
    섞이지 않는 것은 이 분기 하나가 전부다.
    """

    limit = max(1, min(limit, NOTIFICATION_HISTORY_MAX_LIMIT))
    offset = max(0, offset)

    notifications = Notification.objects.filter(recipient=request.auth_user)
    notifications = _scope_by_classroom(notifications, classroom_only)
    notifications = notifications.prefetch_related("dispatches").order_by("-created_at")[
        offset : offset + limit
    ]
    return [_serialize(n, for_recipient=True) for n in notifications]


@public_router.get("/unread-count", response=UnreadCountOut, auth=jwt_auth)
def unread_count(request, classroom_only: bool = False):
    """헤더 벨의 배지 숫자(#230). 목록 전체를 가져오지 않고 개수만 센다 — 벨은
    목록 화면 밖에서도(다른 페이지를 보는 동안) 계속 나타나야 하므로 가벼워야
    한다.

    `classroom_only=true`면 강의실 알림만 센다(#304) — 강의실 종 배지가 공모전·
    지급·이의 알림까지 섞어 세면 "자기 채점 결과를 그 안에서 찾아야" 하므로
    (#304 What to build), 강의실 벨은 이 값을 준다. 기본값(`False`)은 강의실
    알림을 뺀 나머지만 센다(#345) — 공개 앱 종 배지는 강의실 채점 결과로
    울리지 않는다."""

    qs = Notification.objects.filter(recipient=request.auth_user, read_at__isnull=True)
    qs = _scope_by_classroom(qs, classroom_only)
    return UnreadCountOut(count=qs.count())


@public_router.post("/mark-read", response=MarkAllReadOut, auth=jwt_auth)
def mark_all_read(request, classroom_only: bool = False):
    """지금 안 읽은 알림을 「모두 읽음」으로 한꺼번에 표시한다 — 각 앱의 「모두
    읽음」 버튼이 부른다(#345). 예전에는 목록 화면을 마운트하는 것만으로 이
    엔드포인트가 자동으로 불렸지만, 그 계약은 이 티켓이 CONTEXT.md 「Notification」
    ("목록을 열어 본 것만으로는 읽음이 아니다")에 맞춰 없앴다 — 지금은 이
    버튼을 누른 사실만이 읽음의 근거다.

    `recipient=request.auth_user`로만 골라 갱신한다 — 남의 알림은 이 계정으로
    어떤 요청을 보내도 이 WHERE 절 밖에 있어 손댈 수 없다(AC: "남의 알림은 어떤
    방법으로도 읽거나 읽음 처리할 수 없다"). 개별 알림 id를 받는 파라미터가
    아예 없다 — 그런 파라미터가 있었다면 그 자체가 남의 알림 id를 넣어보는
    시도의 표면이 됐을 것이다(개별 알림 하나를 지목하려면 아래
    `mark_one_read`를 쓴다).

    `classroom_only=true`면 강의실 알림만 읽음 처리한다(#304) — 강의실 화면을
    여는 것이 그 사람의 공모전·지급 알림까지 함께 읽음으로 만들면 안 된다
    (두 제품이 계정을 공유하는 사람에게 생기는 부작용). 기본값(`False`)은
    강의실 알림을 뺀 나머지만 치운다(#345) — 공개 앱의 「모두 읽음」이 그
    사람의 강의실 알림까지 읽음으로 만들면 안 되는 것이 같은 이유로 반대
    방향에도 적용된다.

    발송 측 필드(`status`·`dispatches`)는 이 갱신이 전혀 건드리지 않는다 — 읽음
    처리가 발송 이력을 바꾸지 않는다는 AC가 그래서 구조적으로 성립한다.

    `classroom_only=true`이고 실제로 뭔가 읽음이 됐으면(`marked_count > 0`)
    강의실 벨에 `notification-changed`를 낸다(#381) — 공개 앱의 「모두 읽음」
    (`classroom_only` 생략)은 이 판정 자체를 타지 않아 신호를 내지 않는다."""

    qs = Notification.objects.filter(recipient=request.auth_user, read_at__isnull=True)
    qs = _scope_by_classroom(qs, classroom_only)
    marked_count = qs.update(read_at=Clock.now())
    if classroom_only and marked_count:
        _publish_classroom_notification_changed(request.auth_user.id)
    return MarkAllReadOut(marked_count=marked_count)


@public_router.post("/{int:notification_id}/mark-read", response=NotificationOut, auth=jwt_auth)
def mark_one_read(request, notification_id: int):
    """알림 하나를 지목해 읽음으로 표시한다(#345) — 링크가 있는 알림을 눌러 그
    화면으로 갈 때, 또는 링크 없는 알림 줄의 「읽음」 버튼이 부른다.

    `recipient=request.auth_user`로 먼저 좁혀 조회한다 — 남의 알림 id는
    `get_object_or_404`가 곧바로 404로 답해, 존재 자체를 알려주지 않는다(AC:
    "남의 알림 id는 존재하지 않는 것처럼 다룬다"). 강의실 묶음(#305)의 머리글처럼
    알림 여러 개를 한 번에 읽음 처리해야 하는 자리는 아래 `mark_many_read`를 쓴다.

    이미 읽은 알림에 다시 호출해도 에러가 아니다(멱등) — `read_at`을 덮어쓰지
    않고 그대로 둔다(최초로 읽은 시각을 보존한다). **갱신 자체가 조건부
    `UPDATE`다**(`read_at__isnull=True`인 행만) — 조회 후 파이썬에서 `if`로
    가르면 동시에 들어온 두 요청이 둘 다 `None`을 보고 둘 다 쓸 수 있어, 나중에
    커밋된 쪽의 시각이 "최초"를 덮어쓴다. DB가 조건을 다시 확인하는 조건부
    `UPDATE`는 둘 중 하나만 실제로 행을 바꾼다."""

    notification = get_object_or_404(Notification, pk=notification_id, recipient=request.auth_user)
    Notification.objects.filter(pk=notification.pk, read_at__isnull=True).update(read_at=Clock.now())
    notification.refresh_from_db(fields=["read_at"])
    if notification.notification_type in CLASSROOM_NOTIFICATION_TYPES:
        _publish_classroom_notification_changed(request.auth_user.id)
    return _serialize(notification, for_recipient=True)


class MarkManyReadIn(Schema):
    notification_ids: list[int]


@public_router.post("/mark-read-many", response=MarkAllReadOut, auth=jwt_auth)
def mark_many_read(request, payload: MarkManyReadIn):
    """알림 여러 개를 한 번에 지목해 읽음으로 표시한다(#345) — 강의실 묶음(#305)의
    머리글을 누르면 그 문제의 안 읽은 시도 전부가 한 번에 읽음이 되어야 하는데,
    시도마다 `mark_one_read`를 따로 부르면 문제 하나에 시도가 쌓일수록 요청 수가
    그만큼 는다. `pk__in` 을 `recipient=request.auth_user` 로 좁혀서만 갱신한다 —
    남의 알림 id 가 섞여 들어와도 그 행만 조용히 걸러진다(에러를 내지 않는다,
    `mark_all_read`가 이미 받는 값이 `recipient` 로만 갇혀 있는 것과 같은 모양).
    `NOTIFICATION_HISTORY_MAX_LIMIT`(위, 응답 상한)과 같은 이유로 요청 하나의
    id 개수도 그 값으로 잘라낸다 — 무제한 입력을 그대로 쿼리에 넣지 않는다."""

    ids = payload.notification_ids[:NOTIFICATION_HISTORY_MAX_LIMIT]
    qs = Notification.objects.filter(pk__in=ids, recipient=request.auth_user, read_at__isnull=True)
    # 갱신 전에 판정한다 — `read_at`을 이미 채운 뒤에는 이 필터가 더 이상 그
    # 갱신 대상 집합과 같은 행을 가리키지 않을 이유는 없지만(update가 유형을
    # 바꾸지 않는다), 갱신 여부와 무관하게 "이 요청이 강의실 알림을 하나라도
    # 지목했는가"만 물으면 되므로 순서가 결과를 바꾸지 않는다.
    marked_ids_include_classroom = qs.filter(
        notification_type__in=CLASSROOM_NOTIFICATION_TYPES
    ).exists()
    marked_count = qs.update(read_at=Clock.now())
    if marked_count and marked_ids_include_classroom:
        _publish_classroom_notification_changed(request.auth_user.id)
    return MarkAllReadOut(marked_count=marked_count)


def _publish_classroom_notification_changed(recipient_id: int) -> None:
    """읽음 처리 세 엔드포인트(모두·하나·묶음)가 공유하는 발행 호출(#381,
    ADR-0046) — "그 알림이 강의실 것인가"만 이 앱이 판정하고, 실제 신호 종류·
    수신자 규칙은 `notifications.realtime`이 정한다
    (`notifications.services._publish_notification_changed_if_classroom`과
    같은 이유)."""

    from notifications.realtime import publish_notification_changed

    publish_notification_changed(recipient_id=recipient_id)


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
