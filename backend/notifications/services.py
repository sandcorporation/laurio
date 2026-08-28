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

from django.db.models import Q
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

# QUEUED로 선점된 뒤 이만큼 지나도 여전히 QUEUED면 "멈췄다"고 본다(#10 리뷰 지적).
# 정상적인 발송 시도는 어댑터 타임아웃을 포함해도 이보다 훨씬 빨리 SENT/FAILED로
# 끝난다 — 그래서 이 문턱을 넘긴 QUEUED는 진행 중이 아니라 죽은 것으로 취급해도
# 안전하다.
STUCK_QUEUED_THRESHOLD = timedelta(minutes=5)


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


def create_notification(
    *, recipient, notification_type: str, context: dict | None = None
) -> Notification:
    """Notification 한 건을 만들고, 옵트인·야간 규칙에 따라 즉시 발송하거나 연기한다.

    `context`는 이 알림이 무엇에 관한 것인지(대상 Contest, 금액 등)를 담는
    구조화된 맥락이다(#19) — 옵트인·야간 판정·채널 폴백 로직에는 전혀 관여하지
    않는다. 생략하면 빈 dict로 남는다.
    """

    flags = NOTIFICATION_TYPE_FLAGS[notification_type]
    is_transactional = flags["is_transactional"]
    is_promotional = flags["is_promotional"]
    context = context or {}

    now = Clock.now()

    if is_promotional and not _has_opt_in(recipient, notification_type):
        return Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            is_transactional=is_transactional,
            is_promotional=is_promotional,
            status=Notification.Status.BLOCKED_NO_OPT_IN,
            context=context,
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
            context=context,
            created_at=now,
        )
        return notification

    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        is_transactional=is_transactional,
        is_promotional=is_promotional,
        status=Notification.Status.QUEUED,
        # 아래 _attempt_dispatch가 이 요청 안에서 곧바로 끝내지 못하고(어댑터가
        # 예상 못 한 방식으로 죽는 등) 예외가 새 나가더라도, claimed_at을 남겨두면
        # 이 행이 QUEUED에 갇힌 채 영원히 잊히지 않는다 — 야간 큐 스캐너가 나중에
        # STUCK_QUEUED_THRESHOLD를 넘긴 QUEUED도 함께 주워 재시도한다(#10 리뷰 지적).
        claimed_at=now,
        context=context,
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


def _process_claimed_queued_row(pk: int, *, now) -> bool:
    """QUEUED 선점(신규든 재선점이든)에 성공한 뒤 공통으로 할 일.

    스캔이 지연되어 처리 시점에 다시 야간(21~08시)로 들어와 있으면 — 예: 다음 날
    08:00으로 연기해둔 것을 그 다음 21:30에야 스캔했다면 — 발송하지 않고 그 다음
    08:00으로 다시 연기한다. "발송 시각이 지났다"는 것과 "지금 당장 내보내도 되는
    시각이다"는 것은 다른 판정이라, 두 번째 것도 실제 발송 직전에 다시 확인해야
    한다(ADR-0010). 재연기했으면 False, 실제로 발송을 시도했으면 True를 돌려준다 —
    호출자가 "이 스캔에서 몇 건이나 실제로 처리됐는지"를 셀 때 재연기를 발송으로
    잘못 세지 않게 하기 위해서다.
    """

    if in_quiet_hours(now):
        Notification.objects.filter(pk=pk, status=Notification.Status.QUEUED).update(
            status=Notification.Status.DEFERRED, scheduled_for=next_quiet_hours_end(now)
        )
        return False

    notification = Notification.objects.get(pk=pk)
    _attempt_dispatch(notification, now=now)
    return True


def _claim_and_process_deferred(pk: int, *, now) -> bool:
    """DEFERRED -> QUEUED 를 조건부로 선점한 뒤, 발송을 시도(혹은 재연기)한다.

    선점에 실패하면(이미 다른 스캔이 가져갔거나 상태가 바뀌었으면) False. 상태
    전이와 `claimed_at` 갱신은 `claim_transition` 한 번의 조건부 UPDATE로 함께
    커밋된다(#10 리뷰 지적) — 둘을 별도 문장으로 나누면 그 사이의 예외가 "상태만
    QUEUED로 바뀌고 claimed_at은 못 채워진" 행을 만들 수 있었다.
    """

    claimed = claim_transition(
        Notification,
        pk,
        from_state=Notification.Status.DEFERRED,
        to_state=Notification.Status.QUEUED,
        state_field="status",
        now=now,
        extra_fields={"claimed_at": now},
    )
    if not claimed:
        return False

    return _process_claimed_queued_row(pk, now=now)


def _reclaim_stuck_queued(pk: int, *, now, stale_before) -> bool:
    """QUEUED에서 STUCK_QUEUED_THRESHOLD 이상 멈춰 있는 행을 다시 선점한다.

    DEFERRED -> QUEUED 선점 뒤 재연기/발송 판정 사이(또는 즉시발송 경로의 발송
    시도 자체)에서 예기치 못한 예외가 나면 그 행은 QUEUED에서 멈춘 채로 남을 수
    있다 — 예전 스캐너는 DEFERRED만 다시 주웠으므로 그런 행은 영원히 재시도되지
    않았다(#10 리뷰 지적: "_attempt_dispatch의 docstring이 막는다던 바로 그 상황").

    `claimed_at`을 조건에 넣은 조건부 UPDATE라서 여러 스캔이 동시에 같은 행을
    집어도 정확히 하나만 성공한다 — 먼저 이긴 스캔이 `claimed_at`을 신선한 값으로
    갱신하면, 뒤이은 UPDATE는 더 이상 `claimed_at__lte=stale_before` 를 만족하지
    않아 rowcount 0으로 끝난다(claim_transition의 상태 문자열 대신 시각을 조건으로
    쓰는 같은 원리).
    """

    updated = Notification.objects.filter(
        Q(claimed_at__isnull=True) | Q(claimed_at__lte=stale_before),
        pk=pk,
        status=Notification.Status.QUEUED,
    ).update(claimed_at=now)
    return updated == 1


def _reclaim_and_process_stuck_queued(pk: int, *, now, stale_before) -> bool:
    if not _reclaim_stuck_queued(pk, now=now, stale_before=stale_before):
        return False
    return _process_claimed_queued_row(pk, now=now)


def dispatch_due_notifications(as_of=None) -> list[int]:
    """야간 연기(DEFERRED)로 쌓인 것과, QUEUED에서 멈춰버린 것을 찾아 발송을 시도한다.

    DEFERRED 행은 claim_transition 으로 DEFERRED -> QUEUED 를 먼저 조건부로 선점한
    뒤에만 실제 발송을 시도한다. QUEUED 행은 STUCK_QUEUED_THRESHOLD 이상 멈춰 있는
    것만 재선점 대상이다(#10 리뷰 지적) — 그렇지 않으면 지금 막 즉시발송 경로로
    한창 처리 중인(아직 SENT/FAILED로 끝나지 않은) 정상적인 QUEUED 행까지 이 스캔이
    집어 이중 발송을 시도하게 된다.

    같은 as_of 로 두 번 불러도 이미 QUEUED/SENT/FAILED/다시 DEFERRED 로 옮겨간 행은
    다시 잡히지 않으므로 중복 발송이 없다.

    한 행 처리 중 예기치 못한 예외가 나도(_attempt_dispatch 자체는 채널 예외를 이미
    다 잡지만, 방어적으로 한 번 더) 나머지 행 처리를 막지 않는다 — 배치 하나가 통째로
    막혀 뒤에 있는 정상 건들까지 무기한 QUEUED 로 남는 사고를 막기 위함이다. 설령
    이 처리 자체가 다시 죽더라도, claimed_at이 이미 갱신돼 있으므로 다음 스캔이
    STUCK_QUEUED_THRESHOLD 뒤에 다시 집어간다 — 완전히 잊히는 경로가 없다.
    """

    as_of = as_of or Clock.now()
    stale_before = as_of - STUCK_QUEUED_THRESHOLD

    due_deferred_ids = list(
        Notification.objects.filter(status=Notification.Status.DEFERRED, scheduled_for__lte=as_of)
        .order_by("pk")
        .values_list("pk", flat=True)[:DUE_SCAN_BATCH_SIZE]
    )

    stuck_queued_ids = list(
        Notification.objects.filter(status=Notification.Status.QUEUED)
        .filter(Q(claimed_at__isnull=True) | Q(claimed_at__lte=stale_before))
        .order_by("pk")
        .values_list("pk", flat=True)[:DUE_SCAN_BATCH_SIZE]
    )

    dispatched_ids: list[int] = []
    for pk in due_deferred_ids:
        try:
            if _claim_and_process_deferred(pk, now=as_of):
                dispatched_ids.append(pk)
        except Exception:  # noqa: BLE001 - 한 행의 실패가 나머지 배치를 막으면 안 된다.
            logger.exception("Notification(pk=%s) 야간 큐 처리 중 예외, 다음 행으로 계속", pk)

    for pk in stuck_queued_ids:
        try:
            if _reclaim_and_process_stuck_queued(pk, now=as_of, stale_before=stale_before):
                dispatched_ids.append(pk)
        except Exception:  # noqa: BLE001 - 한 행의 실패가 나머지 배치를 막으면 안 된다.
            logger.exception("Notification(pk=%s) 멈춘 QUEUED 재처리 중 예외, 다음 행으로 계속", pk)

    return dispatched_ids
