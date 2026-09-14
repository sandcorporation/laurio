"""Notification 생성·발송 서비스 (ADR-0009, ADR-0010).

흐름:

1. 광고성인데 옵트인이 없으면 아예 시도하지 않고 BLOCKED_NO_OPT_IN 으로 기록한다.
2. 야간(21~08시)에 발생했으면 폐기하지 않고 다음 날 08시로 연기(DEFERRED)한다.
   거래성도 예외 없이 연기 대상이다 — 이 프로젝트는 법정 최소 기준(광고성만 야간
   규제)보다 엄격하게, 야간에는 어떤 Notification 도 내보내지 않는다. **예외가
   하나 있다**(#169, ADR-0010 개정) — `NOTIFICATION_TYPE_FLAGS` 에서
   `is_quiet_hours_exempt` 가 참인 유형(`PAYOUT_AWAITS_YOU`)은 야간에도 즉시
   채널 폴백을 시도한다.
3. 그 외에는 즉시 채널 폴백 체인(알림톡 → SMS → LMS)을 시도한다.

`notification-dispatch-deferred` 스캔 는 DEFERRED 로 쌓인 것 중 scheduled_for 가 지난 것을
찾아 실제로 발송을 시도한다. 이때도 core.transitions.claim_transition 과 같은 조건부
UPDATE 패턴을 그대로 재사용해, 같은 시각에 두 번 스캔해도 한 번만 발송을 시도한다
(ADR-0003 이 만든 메커니즘의 재사용).

시각은 이 모듈의 각 공개 함수(create_notification, notification-dispatch-deferred 스캔) 호출당
Clock.now() 를 딱 한 번만 구해서 그 값을 아래로 넘긴다. 채널마다, 행마다 다시 조회하면
SELECT 가 선형으로 쌓인다.
"""

import logging
from datetime import time, timedelta, timezone as dt_timezone

from django.db.models import Q
from django.utils import timezone

from core.clock import Clock
from core.scans import ScanSpec
from core.transitions import claim_transition

from .adapters import CHANNEL_FALLBACK_CHAIN, ChannelSendResult
from .models import (
    CLASSROOM_NOTIFICATION_TYPES,
    NOTIFICATION_TYPE_FLAGS,
    Notification,
    NotificationDispatch,
    NotificationOptIn,
)

logger = logging.getLogger(__name__)

QUIET_HOURS_START = time(21, 0)
QUIET_HOURS_END = time(8, 0)

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
    # 야간 전면 유예의 예외를 여는 유일한 자리(#169, ADR-0010 개정) — 호출부가 매번
    # "이건 급하다"고 주장하지 못하게, 이 유형 표만 본다.
    is_quiet_hours_exempt = flags["is_quiet_hours_exempt"]
    # 이 유형이 애초에 어느 채널로도 나가지 않는다는 성질(#301) — 마찬가지로
    # 호출부가 뒤집을 수 없다.
    is_internal_only = flags["is_internal_only"]
    context = context or {}

    now = Clock.now()

    if is_internal_only:
        # 옵트인·야간 연기 판정 자체를 건너뛴다 — 그 둘은 "밖으로 내보낼지"를
        # 가르는 판정인데 이 유형은 애초에 내보내지 않는다. `NOT_DISPATCHED`는
        # `FAILED`(전 채널 시도 후 실패)와 달리 채널을 한 번도 건드리지 않았다는
        # 뜻이라 `dispatches`가 항상 비어 있다.
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            is_transactional=is_transactional,
            is_promotional=is_promotional,
            status=Notification.Status.NOT_DISPATCHED,
            context=context,
            created_at=now,
        )
    elif is_promotional and not _has_opt_in(recipient, notification_type):
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            is_transactional=is_transactional,
            is_promotional=is_promotional,
            status=Notification.Status.BLOCKED_NO_OPT_IN,
            context=context,
            created_at=now,
        )
    elif in_quiet_hours(now) and not is_quiet_hours_exempt:
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
    else:
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            is_transactional=is_transactional,
            is_promotional=is_promotional,
            status=Notification.Status.QUEUED,
            # 아래 _attempt_dispatch가 이 요청 안에서 곧바로 끝내지 못하고(어댑터가
            # 예상 못 한 방식으로 죽는 등) 예외가 새 나가더라도, claimed_at을
            # 남겨두면 이 행이 QUEUED에 갇힌 채 영원히 잊히지 않는다 — 야간 큐
            # 스캐너가 나중에 STUCK_QUEUED_THRESHOLD를 넘긴 QUEUED도 함께 주워
            # 재시도한다(#10 리뷰 지적).
            claimed_at=now,
            context=context,
            created_at=now,
        )
        _attempt_dispatch(notification, now=now)
        notification.refresh_from_db()

    _publish_notification_changed_if_classroom(notification)
    return notification


def _publish_notification_changed_if_classroom(notification: Notification) -> None:
    """이 알림이 강의실 것이면(`CLASSROOM_NOTIFICATION_TYPES`) 벨이 새로고침 없이
    맞춰지도록 신호를 낸다(#381, ADR-0046) — 공모전 알림은 이 판정에 걸리지
    않아 신호를 내지 않는다(AC "공개 앱 알림은 신호를 내지 않는다").

    네 경로(내부 전용·옵트인 차단·야간 연기·즉시 발송) 전부가 이 한 자리로
    모이므로, 앞으로 분기가 늘어도 발행 자리를 또 늘릴 필요가 없다."""

    if notification.notification_type not in CLASSROOM_NOTIFICATION_TYPES:
        return

    # 신호 정의는 `notifications.realtime`(이 앱)에 있다 — 여기서는 "강의실 알림인가"만 판정한다.
    from notifications.realtime import publish_notification_changed

    publish_notification_changed(recipient_id=notification.recipient_id)


def notify_safely(*, recipient, notification_type: str, context: dict) -> None:
    """`create_notification` 을 호출하되 어떤 예외도 호출자에게 전파하지 않는다.

    호출자의 흐름(lifecycle 전이·스캔)이 알림 실패로 막히면 안 된다는 규율
    (ADR-0009)을 한 곳에 둔다 — 원래 `notifications.lifecycle._safe_notify` 였는데,
    지급 알림 스캔(#169, `payouts.notifications`)도 같은 보장이 필요해 여기로
    옮겼다. 여러 앱이 이 함수를 재사용하므로, 「알림 생성 실패가 호출자를 막지
    않는다」는 규율이 두 곳에 따로 구현되어 갈리는 일이 없다.
    """

    try:
        create_notification(
            recipient=recipient, notification_type=notification_type, context=context
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 호출자의 흐름을 막으면 안 된다.
        logger.exception(
            "Notification(type=%s, recipient=%s) 생성 중 예외 — 호출자의 흐름은 계속된다",
            notification_type,
            getattr(recipient, "id", None),
        )


def notify_once(*, recipient, notification_type: str, dedup_context: dict, context: dict) -> None:
    """`recipient` 에게 이 `dedup_context` 에 대한 알림을 정확히 한 번만(재시도
    안전하게) 만든다.

    원래 `notifications.lifecycle._safe_notify_once` 였다 — 그 함수의 독스트링이
    설명하는 관용구("이 수신자에게 이 dedup 맥락으로 한 번만")를 그대로 옮긴 것이다.
    지급 알림 스캔(#169)이 dedup_context 로 Payout 식별자·`HoldKind`·실이체 시도
    횟수 셋을 준다 — 스캔이 60초마다 돌아도 같은 차례에는 한 번만 발송되고,
    재시도로 시도 횟수가 오르면 새 dedup_context 라 다시 발송된다.

    **멱등 검사는 이전에 저장된 `context` 필드를 되짚어 읽는다** — 그러니
    `dedup_context` 의 키가 실제로 저장되는 `context` 에 없으면, 다음 호출이
    "아직 안 보냈다"로 잘못 판정해 매번 새로 보낸다(#169 에서 실제로 겪은
    실수). 호출부가 그 실수를 반복하지 않도록, 여기서 `dedup_context` 를
    `context` 에 항상 덮어써 넣는다 — 호출부가 두 dict 를 손으로 맞출 필요가
    없다.
    """

    filters = {f"context__{key}": value for key, value in dedup_context.items()}
    already_sent = Notification.objects.filter(
        recipient=recipient, notification_type=notification_type, **filters
    ).exists()
    if already_sent:
        return
    notify_safely(
        recipient=recipient,
        notification_type=notification_type,
        context={**context, **dedup_context},
    )


def _attempt_dispatch(notification: Notification, *, now=None) -> None:
    """알림톡 → SMS → LMS 순으로 시도하고, 채널마다 이력을 남긴다.

    성공한 채널이 나오는 즉시 멈추고 SENT 로 전이한다. 전부 실패하면 FAILED 로
    전이한다. 전이는 claim_transition(조건부 UPDATE)으로만 한다.

    어댑터는 신뢰할 수 없는 외부 벤더 클라이언트다 — 실패 응답이 아니라 예외로
    죽는 것(타임아웃, 5xx, 연결 거부)이 실제로는 훨씬 흔하다. 여기서 잡지 않으면
    ① 다음 채널로 넘어가지 못하고, ② 이 시도의 이력이 아예 안 남고(ADR-0009 의
    발송 이력=법적 방어선이 뚫린다), ③ Notification 이 QUEUED 에 영원히 멈춘다
    (야간 큐 스캐너는 DEFERRED 만 다시 줍는다). 그래서 채널마다 개별적으로 감싼다.

    **채널마다 두 단계로 기록한다(#51 코드리뷰 지적 7).** 벤더를 부르기 "전"에
    PENDING 행을 먼저 커밋하고, 응답을 받은 "후"에 SENT/FAILED로 갱신한다.
    실물 어댑터(Fake와 달리)는 실제로 과금되는 외부 호출이라, 벤더 발송이
    실제로 성공한 뒤 이 함수가 SENT를 기록하기 전에 프로세스가 죽으면(배포
    재시작, OOM 등) 이 Notification은 QUEUED에 claimed_at만 남긴 채 멈춘다.
    STUCK_QUEUED_THRESHOLD가 지나 재선점되면 예전 코드는 알림톡부터 처음부터
    다시 시도했다 — 이미 성공했을 수도 있는 채널에 실제 과금이 다시 발생하는
    "유료 재발송" 사고다. PENDING 기록이 있으면 "이 채널을 이미 시도했을 수도
    있다"는 증거가 남으므로, 재시도가 그 채널을 건너뛰고 다음 채널로 넘어간다 —
    "다시 보낸다"보다 "이 채널로는 확신이 없으니 넘어간다"를 우선한다(돈이
    새는 쪽보다 알림 하나가 덜 가는 쪽이 안전하다, ADR-0009와 같은 방향의
    선택).

    **이미 SENT인 채널이 있는지는 채널 순서를 따라가며 확인하지 않고, 반복문에
    들어가기 전에 전체를 한 번에 확인한다**(#51 3차 코드리뷰 지적 5) — 그렇지
    않으면 나중 채널(예: sms)이 SENT까지 기록된 뒤 claim_transition 직전에
    죽었을 때, 재선점이 그 SENT 행에 도달하기도 전에 앞 채널(알림톡, 정상
    FAILED라 재시도 대상)부터 다시 벤더를 불러 중복 도달·이중 과금을 만들
    수 있다.
    """

    now = now if now is not None else Clock.now()
    from_state = notification.status

    # 어떤 채널이든 이미 SENT로 기록돼 있으면 더는 아무 채널도 건드리지
    # 않는다(#51 3차 코드리뷰 지적 5). 이 확인을 반복문 "안"에서 채널 순서
    # (알림톡→SMS→LMS)대로만 하면, sms가 SENT까지 기록된 뒤 claim_transition
    # 직전에 죽었을 때 재선점이 sms의 SENT 행에 도달하기도 전에 alimtalk
    # (FAILED — 정상적인 실패라 재시도 대상이다)부터 다시 벤더를 부른다.
    # alimtalk 재시도 자체는 의도된 동작(실패한 채널은 재시도해야 한다)이지만,
    # 그 재시도가 이번에는 성공하면 이미 성공한 sms와 합쳐 같은 알림이 두
    # 채널로 중복 도달하고 두 번 과금된다 — 반복문에 들어가기 전에 전체
    # 채널을 한 번 훑어 "이미 성공한 채널이 있는가"부터 확인해야 이 순서
    # 문제가 사라진다.
    if NotificationDispatch.objects.filter(
        notification=notification, status=NotificationDispatch.Status.SENT
    ).exists():
        claim_transition(
            Notification,
            notification.pk,
            from_state=from_state,
            to_state=Notification.Status.SENT,
            state_field="status",
            now=now,
        )
        return

    for channel, adapter_factory in CHANNEL_FALLBACK_CHAIN:
        previous = (
            NotificationDispatch.objects.filter(notification=notification, channel=channel)
            .order_by("-id")
            .first()
        )
        if previous is not None and previous.status in (
            NotificationDispatch.Status.PENDING,
            NotificationDispatch.Status.INDETERMINATE,
        ):
            logger.warning(
                "Notification(pk=%s) 채널 %s 의 이전 시도가 결과 확정 전에 "
                "중단됐다(PENDING/INDETERMINATE) — 벤더가 실제로 발송에 "
                "성공했을 수 있으므로 중복 과금을 피하기 위해 재시도하지 "
                "않고 다음 채널로 넘어간다.",
                notification.pk,
                channel,
            )
            if previous.status == NotificationDispatch.Status.PENDING:
                # PENDING을 FAILED로 확정하면 안 된다(#51 3차 코드리뷰 지적 1
                # — 2차 수정이 되돌린 사고) — FAILED는 "안전하게 재시도해도
                # 되는 실패"로 다음 재선점에 읽혀, 이미 벤더가 성공시켰을 수도
                # 있는 채널에 또 벤더를 불러 재과금·중복 도달을 만든다. 그렇다고
                # PENDING을 사유 없이 그대로 두면 발송 이력이 아무것도 설명하지
                # 못한다(#51 2차 코드리뷰 지적 6). INDETERMINATE는 "재시도
                # 대상이 아니다"라는 사실을 SENT/PENDING과 같은 그룹으로 유지
                # 하면서(위 if 조건), 이력에는 "왜 재시도하지 않았는지"를
                # 정직하게 남긴다 — FAILED가 아니므로 다음 재선점도 이 분기를
                # 다시 타 안전하게 건너뛴다(이미 INDETERMINATE라 이 if 블록
                # 자체는 다시 쓰지 않는다).
                previous.status = NotificationDispatch.Status.INDETERMINATE
                previous.failure_reason = (
                    "이전 시도가 벤더 응답을 받기 전에 중단됐다 — 실제로 성공했을 "
                    "수 있어 중복 과금을 피하기 위해 재시도하지 않았다."
                )[:255]
                previous.save(update_fields=["status", "failure_reason"])
            continue

        # 벤더를 부르기 전에 PENDING을 먼저 커밋한다 — 아래 어댑터 호출 도중
        # 프로세스가 죽어도 이 행은 이미 DB에 있다.
        dispatch = NotificationDispatch.objects.create(
            notification=notification,
            channel=channel,
            status=NotificationDispatch.Status.PENDING,
            attempted_at=now,
            failure_reason="",
        )

        try:
            # 코디네이터 리뷰 지적(#23): adapter_factory()는 원래 이 try 밖에 있었다.
            # NOTIFICATION_*_ADAPTER가 존재하지 않는 dotted path(예: 아직 구현되지
            # 않은 실제 벤더 어댑터)를 가리키면 import_string이 ImportError를 던지고,
            # 그 예외가 이 함수를 그대로 빠져나가 create_notification 전체가 500으로
            # 죽는다 — 발송 이력도 안 남고 Notification은 QUEUED에 영원히 멈춘다.
            # .send()가 벤더 예외로 죽는 것과 같은 종류의 "이 채널을 신뢰할 수 없다"는
            # 신호이므로 같은 try/except로 감싸 다음 채널로 넘어가게 한다.
            adapter = adapter_factory()
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

        dispatch.status = (
            NotificationDispatch.Status.SENT
            if result.success
            else NotificationDispatch.Status.FAILED
        )
        dispatch.failure_reason = result.failure_reason[:255]
        dispatch.save(update_fields=["status", "failure_reason"])

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

    **야간 유예의 예외 유형은 재연기하지 않는다**(#169) — 예외 유형은 애초에
    DEFERRED 를 거치지 않지만(`create_notification`), QUEUED 에서 멈췄다가 야간에
    재선점되는 경로(`_reclaim_stuck`)에서는 이 함수가 그 사실을 다시 확인해야 한다.
    """

    # 재연기로 끝나는 경로(가장 흔한 야간 재선점)에는 유형 하나만 있으면 된다 —
    # 코드리뷰 지적: 행 전체(context JSON 포함)를 끌어와 놓고 그 값을 발송
    # 없이 버리는 낭비를 만들지 않는다. 실제로 발송을 시도하는 경로에서만
    # 전체 행을 다시 읽는다.
    notification_type = Notification.objects.values_list("notification_type", flat=True).get(pk=pk)
    is_quiet_hours_exempt = NOTIFICATION_TYPE_FLAGS[notification_type]["is_quiet_hours_exempt"]
    if in_quiet_hours(now) and not is_quiet_hours_exempt:
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


# --- 야간 큐 스캔 둘 (#10, #51, #139) ------------------------------------------------
#
# 야간 연기(DEFERRED)로 쌓인 것의 발송과, QUEUED에서 멈춰버린 것의 재선점은 각자 등록부
# 항목이다 — 예전에는 한 엔드포인트가 둘을 순서대로 돌리며 예산을 절반씩 나눴고, 그
# 나눔의 정확한 규칙(#51 2차 지적 1, 3차 지적 3)이 코드의 절반이었다. 이제 각 스캔이 자기
# 예산을 통째로 받으므로 「DEFERRED 가 몰리는 아침에 stuck-QUEUED 복구가 굶는다」는 구조
# 자체가 없다. stuck-QUEUED 재선점은 PENDING으로 죽은 행(벤더 발송 성공 이후, SENT 확정
# 이전에 프로세스가 죽은 경우)을 되살리는 **유일한** 경로다.
#
# 시간 예산 12초(#51 코드리뷰 지적 6): 진입점은 Celery beat 호출의 timeout=30(core/tasks.py)
# 안에 반드시 들어와야 한다 — 채널 하나의 벤더 타임아웃(notifications.adapters_aligo.
# _TIMEOUT_SECONDS=5)이 최악의 경우 셋 다 겹쳐 15초까지 걸릴 수 있으므로 그 여유를 남긴다
# (12 + 15 = 27초 < 30초). 예산을 넘기면 남은 행은 다음 실행(60초 뒤)에 넘긴다 — ADR-0010
# "연기하되 버리지 않는다"와 같은 원칙이고, 상태를 미리 건드리지 않았으므로 안전하다.
# 배치 500은 그보다 훨씬 못 미치는 조건에서만(벤더가 비정상적으로 빠른 경우) 걸리는 상한이다.
_DISPATCH_TIME_BUDGET_SECONDS = 12.0
_DISPATCH_BATCH_SIZE = 500


def _due_deferred(as_of, ctx):
    return Notification.objects.filter(status=Notification.Status.DEFERRED, scheduled_for__lte=as_of)


def _dispatch_deferred(notification, as_of, ctx):
    """DEFERRED -> QUEUED 를 조건부로 선점한 뒤에만 실제 발송을 시도한다. 같은 as_of 로 두
    번 돌아도 이미 QUEUED/SENT/FAILED/다시 DEFERRED 로 옮겨간 행은 다시 잡히지 않는다."""

    if not _claim_and_process_deferred(notification.pk, now=as_of):
        return None
    return {"notification_id": notification.pk}


def _stuck_queued(as_of, ctx):
    """STUCK_QUEUED_THRESHOLD 이상 멈춰 있는 QUEUED 행만(#10 리뷰 지적) — 그렇지 않으면 지금
    막 즉시발송 경로로 한창 처리 중인 정상적인 QUEUED 행까지 집어 이중 발송을 시도하게 된다."""

    stale_before = as_of - STUCK_QUEUED_THRESHOLD
    return Notification.objects.filter(status=Notification.Status.QUEUED).filter(
        Q(claimed_at__isnull=True) | Q(claimed_at__lte=stale_before)
    )


def _reclaim_stuck(notification, as_of, ctx):
    """재선점에 성공한 호출만 처리한다 — 설령 이 처리 자체가 다시 죽더라도 claimed_at 이 이미
    갱신돼 있으므로 다음 실행이 STUCK_QUEUED_THRESHOLD 뒤에 다시 집어간다. 완전히 잊히는
    경로가 없다."""

    stale_before = as_of - STUCK_QUEUED_THRESHOLD
    if not _reclaim_and_process_stuck_queued(notification.pk, now=as_of, stale_before=stale_before):
        return None
    return {"notification_id": notification.pk}


NOTIFICATION_SCANS = (
    ScanSpec(
        name="notification-dispatch-deferred",
        candidates=_due_deferred,
        handle_row=_dispatch_deferred,
        batch_size=_DISPATCH_BATCH_SIZE,
        time_budget_seconds=_DISPATCH_TIME_BUDGET_SECONDS,
    ),
    ScanSpec(
        name="notification-reclaim-stuck",
        candidates=_stuck_queued,
        handle_row=_reclaim_stuck,
        batch_size=_DISPATCH_BATCH_SIZE,
        time_budget_seconds=_DISPATCH_TIME_BUDGET_SECONDS,
    ),
)
