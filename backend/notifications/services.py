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

시각은 이 모듈의 각 공개 함수(create_notification, dispatch_due_notifications) 호출당
Clock.now() 를 딱 한 번만 구해서 그 값을 아래로 넘긴다. 채널마다, 행마다 다시 조회하면
SELECT 가 선형으로 쌓인다.
"""

import logging
from datetime import time, timedelta, timezone as dt_timezone

from django.utils import timezone

from core.clock import Clock
from core.transitions import claim_transition

from .adapters import CHANNEL_FALLBACK_CHAIN, ChannelSendResult
from .models import (
    NOTIFICATION_TYPE_FLAGS,
    Notification,
    NotificationDispatch,
    NotificationOptIn,
)

logger = logging.getLogger(__name__)

QUIET_HOURS_START = time(21, 0)
QUIET_HOURS_END = time(8, 0)

# 야간 큐(DEFERRED) 한 번 스캔에서 처리하는 최대 건수. core.transitions.DEFAULT_BATCH_SIZE
# 와 같은 이유(무제한 스캔이 요청 타임아웃을 만든다)로 둔다.
DUE_SCAN_BATCH_SIZE = 500


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
    _attempt_dispatch(notification, now=now)
    notification.refresh_from_db()
    return notification


def _attempt_dispatch(notification: Notification, *, now=None) -> None:
    """알림톡 → SMS → LMS 순으로 시도하고, 채널마다 이력을 남긴다.

    성공한 채널이 나오는 즉시 멈추고 SENT 로 전이한다. 전부 실패하면 FAILED 로
    전이한다. 전이는 claim_transition(조건부 UPDATE)으로만 한다.

    어댑터는 신뢰할 수 없는 외부 벤더 클라이언트다 — 실패 응답이 아니라 예외로
    죽는 것(타임아웃, 5xx, 연결 거부)이 실제로는 훨씬 흔하다. 여기서 잡지 않으면
    ① 다음 채널로 넘어가지 못하고, ② 이 시도의 이력이 아예 안 남고(ADR-0009 의
    발송 이력=법적 방어선이 뚫린다), ③ Notification 이 QUEUED 에 영원히 멈춘다
    (야간 큐 스캐너는 DEFERRED 만 다시 줍는다). 그래서 채널마다 개별적으로 감싼다.
    """

    now = now if now is not None else Clock.now()
    from_state = notification.status

    for channel, adapter_factory in CHANNEL_FALLBACK_CHAIN:
        adapter = adapter_factory()
        try:
            result = adapter.send(recipient=notification.recipient, notification=notification)
        except Exception as exc:  # noqa: BLE001 - 외부 벤더 어댑터 호출이라 신뢰할 수 없다.
            logger.warning(
                "Notification(pk=%s) 채널 %s 어댑터가 예외로 실패했다: %r",
                notification.pk,
                channel,
                exc,
            )
            result = ChannelSendResult(
                success=False, failure_reason=f"{type(exc).__name__}: {exc}"[:255]
            )

        NotificationDispatch.objects.create(
            notification=notification,
            channel=channel,
            status=(
                NotificationDispatch.Status.SENT
                if result.success
                else NotificationDispatch.Status.FAILED
            ),
            attempted_at=now,
            failure_reason=result.failure_reason[:255],
        )
        if result.success:
            claim_transition(
                Notification,
                notification.pk,
                from_state=from_state,
                to_state=Notification.Status.SENT,
                state_field="status",
                now=now,
            )
            return

    claim_transition(
        Notification,
        notification.pk,
        from_state=from_state,
        to_state=Notification.Status.FAILED,
        state_field="status",
        now=now,
    )


def _claim_and_process_deferred(pk: int, *, now) -> bool:
    """DEFERRED -> QUEUED 를 조건부로 선점한 뒤, 발송을 시도(혹은 재연기)한다.

    선점에 실패하면(이미 다른 스캔이 가져갔거나 상태가 바뀌었으면) False.
    스캔이 지연되어 처리 시점에 다시 야간(21~08시)로 들어와 있으면 — 예:
    다음 날 08:00으로 연기해둔 것을 그 다음 21:30에야 스캔했다면 — 발송하지
    않고 그 다음 08:00으로 다시 연기한다. "발송 시각이 지났다"는 것과 "지금
    당장 내보내도 되는 시각이다"는 것은 다른 판정이라, 두 번째 것도 실제 발송
    직전에 다시 확인해야 한다(ADR-0010).
    """

    claimed = claim_transition(
        Notification,
        pk,
        from_state=Notification.Status.DEFERRED,
        to_state=Notification.Status.QUEUED,
        state_field="status",
        now=now,
    )
    if not claimed:
        return False

    if in_quiet_hours(now):
        Notification.objects.filter(pk=pk, status=Notification.Status.QUEUED).update(
            status=Notification.Status.DEFERRED, scheduled_for=next_quiet_hours_end(now)
        )
        return False

    notification = Notification.objects.get(pk=pk)
    _attempt_dispatch(notification, now=now)
    return True


def dispatch_due_notifications(as_of=None) -> list[int]:
    """야간 연기(DEFERRED)로 쌓인 것 중 scheduled_for 가 지난 것을 찾아 발송을 시도한다.

    각 행은 claim_transition 으로 DEFERRED -> QUEUED 를 먼저 조건부로 선점한 뒤에만
    실제 발송을 시도한다. 같은 as_of 로 두 번 불러도 이미 QUEUED/SENT/FAILED/다시
    DEFERRED 로 옮겨간 행은 다시 잡히지 않으므로 중복 발송이 없다.

    한 행 처리 중 예기치 못한 예외가 나도(_attempt_dispatch 자체는 채널 예외를 이미
    다 잡지만, 방어적으로 한 번 더) 나머지 행 처리를 막지 않는다 — 배치 하나가 통째로
    막혀 뒤에 있는 정상 건들까지 무기한 QUEUED 로 남는 사고를 막기 위함이다.
    """

    as_of = as_of or Clock.now()
    due_ids = list(
        Notification.objects.filter(status=Notification.Status.DEFERRED, scheduled_for__lte=as_of)
        .order_by("pk")
        .values_list("pk", flat=True)[:DUE_SCAN_BATCH_SIZE]
    )

    dispatched_ids: list[int] = []
    for pk in due_ids:
        try:
            if _claim_and_process_deferred(pk, now=as_of):
                dispatched_ids.append(pk)
        except Exception:  # noqa: BLE001 - 한 행의 실패가 나머지 배치를 막으면 안 된다.
            logger.exception("Notification(pk=%s) 야간 큐 처리 중 예외, 다음 행으로 계속", pk)

    return dispatched_ids
