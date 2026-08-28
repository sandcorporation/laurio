"""Notification 생성·발송 서비스 (ADR-0009, ADR-0010).

흐름:

1. 광고성인데 옵트인이 없으면 아예 시도하지 않고 BLOCKED_NO_OPT_IN 으로 기록한다.
2. 야간(21~08시)에 발생했으면 폐기하지 않고 다음 날 08시로 연기(DEFERRED)한다.
   거래성도 예외 없이 연기 대상이다 — 이 프로젝트는 법정 최소 기준(광고성만 야간
   규제)보다 엄격하게, 야간에는 어떤 Notification 도 내보내지 않는다.
3. 그 외에는 즉시 채널 폴백 체인(알림톡 → SMS → LMS)을 시도한다.

`dispatch_due_notifications` 는 DEFERRED 로 쌓인 것 중 scheduled_for 가 지난 것을
찾아 실제로 발송을 시도한다. 이때도 core.transitions.claim_transition 과 같은 조건부
UPDATE 패턴을 그대로 재사용해, 같은 시각에 두 번 스캔해도 한 번만 발송을 시도한다
(ADR-0003 이 만든 메커니즘의 재사용).
"""

from datetime import time, timedelta, timezone as dt_timezone

from django.utils import timezone

from core.clock import Clock
from core.transitions import claim_transition

from .adapters import CHANNEL_FALLBACK_CHAIN
from .models import (
    NOTIFICATION_TYPE_FLAGS,
    Notification,
    NotificationDispatch,
    NotificationOptIn,
)

QUIET_HOURS_START = time(21, 0)
QUIET_HOURS_END = time(8, 0)


def in_quiet_hours(at) -> bool:
    """21:00~08:00(로컬 시각, KST) 사이인지. 21:00은 포함, 08:00은 제외한다."""

    local_time = timezone.localtime(at).time()
    return local_time >= QUIET_HOURS_START or local_time < QUIET_HOURS_END


def next_quiet_hours_end(at):
    """야간에 속한 시각이 주어지면, 그 다음 08:00(로컬)을 돌려준다."""

    local = timezone.localtime(at)
    if local.time() >= QUIET_HOURS_START:
        target_date = local.date() + timedelta(days=1)
    else:
        target_date = local.date()
    target_local = local.replace(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=8,
        minute=0,
        second=0,
        microsecond=0,
    )
    return target_local.astimezone(dt_timezone.utc)


def _has_opt_in(user, notification_type: str) -> bool:
    return NotificationOptIn.objects.filter(
        user=user, notification_type=notification_type, opted_in=True
    ).exists()


def create_notification(*, recipient, notification_type: str) -> Notification:
    """Notification 한 건을 만들고, 옵트인·야간 규칙에 따라 즉시 발송하거나 연기한다."""

    flags = NOTIFICATION_TYPE_FLAGS[notification_type]
    is_transactional = flags["is_transactional"]
    is_promotional = flags["is_promotional"]

    now = Clock.now()

    if is_promotional and not _has_opt_in(recipient, notification_type):
        return Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            is_transactional=is_transactional,
            is_promotional=is_promotional,
            status=Notification.Status.BLOCKED_NO_OPT_IN,
            created_at=now,
        )

    if in_quiet_hours(now):
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            is_transactional=is_transactional,
            is_promotional=is_promotional,
            status=Notification.Status.DEFERRED,
            scheduled_for=next_quiet_hours_end(now),
            created_at=now,
        )
        return notification

    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        is_transactional=is_transactional,
        is_promotional=is_promotional,
        status=Notification.Status.QUEUED,
        created_at=now,
    )
    _attempt_dispatch(notification)
    notification.refresh_from_db()
    return notification


def _attempt_dispatch(notification: Notification) -> None:
    """알림톡 → SMS → LMS 순으로 시도하고, 채널마다 이력을 남긴다.

    성공한 채널이 나오는 즉시 멈추고 SENT 로 전이한다. 전부 실패하면 FAILED 로
    전이한다. 전이는 claim_transition(조건부 UPDATE)으로만 한다.
    """

    from_state = notification.status

    for channel, adapter_factory in CHANNEL_FALLBACK_CHAIN:
        adapter = adapter_factory()
        result = adapter.send(recipient=notification.recipient, notification=notification)
        NotificationDispatch.objects.create(
            notification=notification,
            channel=channel,
            status=(
                NotificationDispatch.Status.SENT
                if result.success
                else NotificationDispatch.Status.FAILED
            ),
            attempted_at=Clock.now(),
            failure_reason=result.failure_reason,
        )
        if result.success:
            claim_transition(
                Notification,
                notification.pk,
                from_state=from_state,
                to_state=Notification.Status.SENT,
                state_field="status",
            )
            return

    claim_transition(
        Notification,
        notification.pk,
        from_state=from_state,
        to_state=Notification.Status.FAILED,
        state_field="status",
    )


def dispatch_due_notifications(as_of=None) -> list[int]:
    """야간 연기(DEFERRED)로 쌓인 것 중 scheduled_for 가 지난 것을 찾아 발송을 시도한다.

    각 행은 claim_transition 으로 DEFERRED -> QUEUED 를 먼저 조건부로 선점한 뒤에만
    실제 발송을 시도한다. 같은 as_of 로 두 번 불러도 이미 QUEUED/SENT/FAILED 로 옮겨간
    행은 다시 잡히지 않으므로 중복 발송이 없다.
    """

    as_of = as_of or Clock.now()
    due_ids = list(
        Notification.objects.filter(
            status=Notification.Status.DEFERRED, scheduled_for__lte=as_of
        ).values_list("pk", flat=True)
    )

    dispatched_ids: list[int] = []
    for pk in due_ids:
        claimed = claim_transition(
            Notification,
            pk,
            from_state=Notification.Status.DEFERRED,
            to_state=Notification.Status.QUEUED,
            state_field="status",
        )
        if not claimed:
            continue
        notification = Notification.objects.get(pk=pk)
        _attempt_dispatch(notification)
        dispatched_ids.append(pk)

    return dispatched_ids
