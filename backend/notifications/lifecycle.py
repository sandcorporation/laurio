"""Contest 라이프사이클 이벤트를 notifications 기반(#18)에 연결한다 (#19).

이 모듈은 notifications 앱의 dispatch·quiet-hours·fallback 로직(services.py)을
전혀 바꾸지 않는다 — `create_notification`을 호출해 그 로직을 그대로 재사용할
뿐이다. 여기서 새로 정의하는 것은 "어떤 Contest 이벤트가 어떤 Notification을
언제, 누구에게 만드는가"뿐이다.

핵심 규율(#19 AC, ADR-0009): Notification 생성이 실패해도(어댑터 예외, DB
문제 등) 이를 호출한 쪽의 lifecycle 전이·Distribution 실행은 절대 막히지
않는다. 그래서 이 모듈의 "결과 알림" 공개 함수(`notify_award_result`,
`notify_distribution_shares`)는 내부에서 예외를 전부 잡고 로깅만 한다 —
호출자에게 예외를 전파하지 않는다. 스캔 함수들(`send_due_*`)은 반대로 한
행의 예외가 배치 전체를 막지 않도록 행 단위로 잡는다
(`distributions.services.run_due_distributions`와 같은 관용구).

리뷰 지적(#19) 이후의 두 번째 규율: **완료 표시는 실제로 다 보낸 뒤에만
남긴다.** "보내기 전에 먼저 완료로 찍고 나서 보낸다"는 순서는, 그 사이(특히
여러 수신자를 순회하는 팬아웃 도중)에 프로세스가 죽으면 "이미 끝났다"는
표시만 남고 알림은 일부(또는 전부) 못 나간 채로 영원히 다시 시도되지 않는
사고를 만든다. 그래서 이 모듈의 모든 스캔·결과 알림 함수는 (1) 수신자별로
`_safe_notify_once`(이미 보낸 적 있으면 건너뛴다)로 시도한 뒤 (2) 그 뒤에만
완료 표시를 남긴다 — 중간에 죽어도 다음 스캔이 "아직 못 받은 수신자만" 안전하게
마저 처리한다.
"""

from __future__ import annotations

import logging
import time as time_module
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from contests.models import Contest
from core.clock import Clock
from policies.services import get_current_policy

from .models import Notification, NotificationType
from .services import create_notification

logger = logging.getLogger(__name__)

User = get_user_model()

# 한 스캔에서 처리하는 최대 Contest 수. core.transitions.DEFAULT_BATCH_SIZE·
# distributions.services.BATCH_SIZE와 같은 이유 — 무제한 스캔은 백로그가 쌓였을
# 때 이 요청 자체를 타임아웃으로 몰아넣는다.
BATCH_SIZE = 200

# Award/Distribution 결과 알림 복구 스캔 한 번이 처리하는 최대 행 수. 같은 이유.
RESULT_NOTICE_BATCH_SIZE = 200

# 다섯 스캔 전체(run_due_lifecycle_notifications)가 실물 벤더 HTTP를 부르며
# 쓸 수 있는 최대 시간(초)(#51 2차 코드리뷰 지적 2). `_safe_notify`/
# `_safe_notify_once`는 내부에서 `create_notification`을 부르고, 그 함수는
# 즉시 `_attempt_dispatch`로 실물 벤더에 동기 HTTP를 낸다 — Contest 200개 ×
# 참가자 전원이면 한 요청 안에서 벤더를 수백~수천 번 부르게 된다.
# `notifications.services.dispatch_due_notifications`와 같은 원칙
# (DUE_SCAN_TIME_BUDGET_SECONDS)을 여기도 적용한다 — 이 예산을 넘기면 남은
# Contest/행은 이번 스캔에서 건드리지 않고 다음 스캔에 넘긴다. "완료 표시
# (*_sent_at)는 실제로 다 보낸 뒤에만 남긴다"(모듈 독스트링)는 원칙과 그대로
# 맞물린다 — 시간 예산으로 중단된 Contest는 완료 표시가 없으므로 다음 스캔이
# 안전하게 이어받는다. `run_due_lifecycle_notifications`가 다섯 스캔에 같은
# 마감시각(deadline) 하나를 넘겨, 스캔 하나가 예산을 다 쓰면 나머지 넷은
# 이번 호출에서 사실상 건드릴 시간이 없다는 것까지 함께 표현한다.
LIFECYCLE_TIME_BUDGET_SECONDS = 12.0


def _budget_exhausted(deadline: float | None) -> bool:
    return deadline is not None and time_module.monotonic() >= deadline


def _safe_notify(*, recipient, notification_type: str, context: dict) -> None:
    """`create_notification`을 호출하되, 어떤 예외도 호출자에게 전파하지 않는다."""

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


def _safe_notify_once(
    *, recipient, notification_type: str, dedup_context: dict, context: dict
) -> None:
    """`recipient`에게 이 `dedup_context`에 대한 알림을 정확히 한 번만(재시도
    안전하게) 만든다.

    "완료 표시는 실제로 다 보낸 뒤에만 남긴다"(모듈 docstring)는 방식과 짝을
    이루는 재시작 안전장치다(#19 리뷰 지적 2) — 스캔이 중간에 죽거나(타임아웃,
    재배포) 다시 실행돼도, 이미 이 수신자에게 같은 `dedup_context`로 만들어진
    Notification이 있으면 다시 만들지 않는다.

    `dedup_context`는 보통 `{"contest_id": ...}`처럼 "이 Contest에 대해 평생
    한 번"을 뜻하지만, 유료 연장처럼 같은 Contest에 대해 같은 유형의 알림이
    **다시** 정당하게 나가야 하는 경우(#19 리뷰 지적 1)에는 그 "새로운 계기"를
    구분하는 값(예: 갱신된 `judging_ends_at`)을 함께 넣어야 한다 — 그렇지
    않으면 이 존재 검사가 예전 알림을 근거로 정당한 재발송까지 막아버린다.

    동시에 실행되는 두 스캔이 이 존재 검사를 동시에 통과해 드물게 중복
    발송될 가능성은 남아 있다 — 이는 "알림이 조용히 유실되는 것보다 드물게
    중복되는 편이 낫다"는 이 코드베이스의 기존 입장(notifications.services의
    STUCK_QUEUED 재선점과 같은 트레이드오프)과 일관된 선택이다.
    """

    filters = {f"context__{key}": value for key, value in dedup_context.items()}
    already_sent = Notification.objects.filter(
        recipient=recipient, notification_type=notification_type, **filters
    ).exists()
    if already_sent:
        return
    _safe_notify(recipient=recipient, notification_type=notification_type, context=context)


def _participating_developer_users(contest: Contest):
    """이 Contest에 Submission을 낸 Developer들의 User 목록(중복 없이)."""

    return User.objects.filter(developer_profile__submissions__contest=contest).distinct()


# --- 마감 임박 -------------------------------------------------------------------


def send_due_deadline_reminders(as_of=None, policy=None, deadline=None) -> list[dict]:
    """마감이 다가오는 PUBLISHED Contest의 Sponsor와 참가 Developer에게 알린다.

    Contest 당 한 번만 "완료"로 표시한다 — `deadline_reminder_sent_at`이 비어
    있는 행만 대상으로 한다. 이 표시는 Sponsor·참가 Developer 전원에게 시도를
    마친 **뒤에만** 남긴다(#19 리뷰 지적 2) — 참가자가 많은 Contest에서 팬아웃
    도중 타임아웃·재배포로 죽으면, 표시를 먼저 찍는 예전 방식은 남은 수신자를
    영원히 못 받게 만들었다. `_safe_notify_once`가 이미 받은 수신자에게 중복
    발송하지 않으므로, 다음 스캔이 이 Contest를 다시 집어도 안전하다.

    `policy`는 이 스캔 스코프에서 한 번 읽은 `PlatformPolicy`다(#78,
    ADR-0023) — 생략하면(단독 호출 편의용, `as_of`와 같은 관용구) 이 함수가
    대신 한 번 읽는다. `run_due_lifecycle_notifications`가 세 스캔에 같은
    `policy`를 넘겨 다섯 스캔 전체에서 정책 조회가 늘어나지 않게 한다.

    `deadline`(#51 2차 코드리뷰 지적 2)은 `time.monotonic()` 기준 마감시각이다
    — 넘기면 Contest 하나든(바깥 루프), 그 Contest의 참가자 팬아웃 도중이든
    (안쪽 루프) 그 자리에서 멈춘다. 팬아웃 도중 멈춘 Contest는 완료 표시를
    남기지 않는다 — 이미 보낸 수신자는 `_safe_notify_once`가 다음 스캔에서
    건너뛰고, 못 보낸 나머지만 이어서 보낸다.
    """

    as_of = as_of or Clock.now()
    policy = policy or get_current_policy()
    lead = timedelta(hours=policy.deadline_reminder_lead_hours)

    due = list(
        Contest.objects.filter(
            status=Contest.Status.PUBLISHED,
            deadline_reminder_sent_at__isnull=True,
            deadline_at__lte=as_of + lead,
        )
        .select_related("sponsor__user")
        .order_by("deadline_at", "id")[:BATCH_SIZE]
    )

    results = []
    for contest in due:
        if _budget_exhausted(deadline):
            logger.warning(
                "마감 임박 알림 스캔이 시간 예산을 넘겨 중단한다 — 나머지 "
                "Contest는 다음 스캔에서 처리된다."
            )
            break
        try:
            context = {
                "contest_id": contest.id,
                "contest_title": contest.title,
                "deadline_at": contest.deadline_at.isoformat(),
            }
            _safe_notify_once(
                recipient=contest.sponsor.user,
                notification_type=NotificationType.DEADLINE_REMINDER,
                dedup_context={"contest_id": contest.id},
                context={**context, "role": "sponsor"},
            )

            fanout_complete = True
            for dev_user in _participating_developer_users(contest):
                if _budget_exhausted(deadline):
                    logger.warning(
                        "Contest(pk=%s) 마감 임박 알림 팬아웃이 시간 예산을 "
                        "넘겨 중단한다 — 남은 참가자는 다음 스캔에서 이어서 "
                        "받는다.",
                        contest.id,
                    )
                    fanout_complete = False
                    break
                _safe_notify_once(
                    recipient=dev_user,
                    notification_type=NotificationType.DEADLINE_REMINDER,
                    dedup_context={"contest_id": contest.id},
                    context={**context, "role": "developer"},
                )

            if not fanout_complete:
                # 이 Contest를 끝까지 못 돌았다 — 완료 표시를 남기지 않고
                # (위 docstring), 예산이 이미 다 소진됐으므로 남은 Contest도
                # 이번 스캔에서는 더 건드리지 않는다.
                break

            # 전원(Sponsor + 참가 Developer)에게 시도를 마친 뒤에만 완료 표시를
            # 남긴다 — 위 docstring 참고.
            Contest.objects.filter(pk=contest.pk, deadline_reminder_sent_at__isnull=True).update(
                deadline_reminder_sent_at=as_of
            )
            results.append({"event": "deadline_reminder_sent", "contest_id": contest.id})
        except Exception:  # noqa: BLE001 - 한 Contest의 실패가 배치를 막으면 안 된다.
            logger.exception("Contest(pk=%s) 마감 임박 알림 처리 중 예외, 다음 건으로 계속", contest.id)

    return results


# --- 심사기간 종료 임박 ------------------------------------------------------------


def send_due_judging_end_reminders(as_of=None, policy=None, deadline=None) -> list[dict]:
    """심사기간 종료가 다가오는 CLOSED Contest의 Sponsor에게 Award를 상기시킨다.

    유료 연장(`contests.services.mark_extension_paid`)이 `judging_ends_at`을
    늘릴 때 `judging_end_reminder_sent_at`도 함께 비운다(#19 리뷰 지적 1) —
    그래야 연장된 새 종료일이 다가올 때 이 스캔이 다시 알릴 수 있다. 여기서는
    그 결과(비워진 플래그)를 그대로 소비할 뿐이다.

    `policy` 파라미터는 `send_due_deadline_reminders`와 같다(#78, ADR-0023).
    `deadline`도 같다(#51 2차 코드리뷰 지적 2).
    """

    as_of = as_of or Clock.now()
    policy = policy or get_current_policy()
    lead = timedelta(hours=policy.judging_end_reminder_lead_hours)

    due = list(
        Contest.objects.filter(
            status=Contest.Status.CLOSED,
            judging_end_reminder_sent_at__isnull=True,
            judging_ends_at__isnull=False,
            judging_ends_at__lte=as_of + lead,
        )
        .select_related("sponsor__user")
        .order_by("judging_ends_at", "id")[:BATCH_SIZE]
    )

    results = []
    for contest in due:
        if _budget_exhausted(deadline):
            logger.warning(
                "심사기간 종료 임박 알림 스캔이 시간 예산을 넘겨 중단한다 — "
                "나머지 Contest는 다음 스캔에서 처리된다."
            )
            break
        try:
            # judging_ends_at을 dedup_context에 함께 넣는다 — 유료 연장이 이
            # 값을 바꾸면서 judging_end_reminder_sent_at도 함께 비우므로(#19
            # 리뷰 지적 1), 이 존재 검사가 "예전(연장 전) 종료일에 대한
            # 알림"까지 같은 것으로 보고 새 알림을 막아버리면 안 된다. 새
            # judging_ends_at은 이전 값과 다르므로, 이 필터는 "이번 종료일에
            # 대해서는 아직 안 보냈다"만 정확히 검사한다.
            _safe_notify_once(
                recipient=contest.sponsor.user,
                notification_type=NotificationType.JUDGING_PERIOD_ENDING_REMINDER,
                dedup_context={
                    "contest_id": contest.id,
                    "judging_ends_at": contest.judging_ends_at.isoformat(),
                },
                context={
                    "contest_id": contest.id,
                    "contest_title": contest.title,
                    "judging_ends_at": contest.judging_ends_at.isoformat(),
                },
            )
            Contest.objects.filter(
                pk=contest.pk, judging_end_reminder_sent_at__isnull=True
            ).update(judging_end_reminder_sent_at=as_of)
            results.append({"event": "judging_end_reminder_sent", "contest_id": contest.id})
        except Exception:  # noqa: BLE001 - 한 Contest의 실패가 배치를 막으면 안 된다.
            logger.exception(
                "Contest(pk=%s) 심사기간 종료 임박 알림 처리 중 예외, 다음 건으로 계속", contest.id
            )

    return results


# --- Distribution 최종 경고: 금액 명시 + 낮 시각 스케줄링(구성 단계에서 보장) -----------


def _constructed_daytime_target(due_at, *, lead_days: int, hour: int):
    """`due_at`으로부터 `lead_days` 전, 항상 로컬(KST) `hour`시로 고정된 시각을 돌려준다.

    ADR-0010의 08시 연기는 "이미 야간에 잡혀버린 발송을 사후에 구조하는"
    안전망이다. Distribution 최종 경고는 그 안전망에 기대지 않고 애초에 낮
    시각으로 스케줄을 구성한다(#19 AC) — `hour`가 08~21 사이인 한, 이 함수가
    돌려주는 시각은 `due_at`의 시·분(자정 근처든 새벽이든)과 무관하게 항상 낮이다.
    """

    local_due = timezone.localtime(due_at)
    raw_date = (local_due - timedelta(days=lead_days)).date()
    target_local = local_due.replace(
        year=raw_date.year,
        month=raw_date.month,
        day=raw_date.day,
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    return target_local.astimezone(dt_timezone.utc)


def send_due_distribution_final_warnings(as_of=None, policy=None, deadline=None) -> list[dict]:
    """Distribution 실행이 다가오는 JUDGING_ENDED Contest의 Sponsor에게 금액을
    명시한 최종 경고를 보낸다.

    `deadline`은 `send_due_deadline_reminders`와 같다(#51 2차 코드리뷰 지적 2).

    아직 Distribution이 만들어지지 않은 Contest만 대상이다 — 이미 실행됐다면
    경고가 아니라 결과 통지(`notify_distribution_shares`)가 맞다.

    경고 시각(`warning_target`)은 `judging_ends_at`으로부터 정확히 선형으로
    계산되지 않는다(`_constructed_daytime_target`이 로컬 날짜 경계에서 시각을
    고정한다) — 그래서 DB 쿼리만으로는 정확한 조건을 표현할 수 없다. 대신 아래
    `judging_ends_at__lte=judging_ends_at_cutoff`는 "확실히 아직 멀었다"는
    Contest만 걸러내는, **절대 과소포함하지 않는(항상 진짜 대상을 포함하는)**
    느슨한 상한이다(#19 리뷰 지적 4) — 이 필터가 없으면 아직 멀었지만 개수가
    많은 후보들이 LIMIT을 다 채워, 실제로 마감된 경고가 이번 스캔에서 밀려날 수
    있다(특히 유료 연장으로 id 순서와 judging_ends_at 순서가 어긋나기 시작하면).
    정확한 최종 판정은 여전히 아래 루프의 `_constructed_daytime_target` 비교가
    한다.

    `policy` 파라미터는 `send_due_deadline_reminders`와 같다(#78, ADR-0023).
    `NOTIFICATION_DAYTIME_HOUR`(낮 시각 자체를 고정하는 상수)는 이 티켓의
    이전 대상이 아니다 — settings에 그대로 남는다.
    """

    as_of = as_of or Clock.now()
    policy = policy or get_current_policy()

    # warning_target은 (judging_ends_at + WAIT_DAYS - LEAD_DAYS)의 로컬 날짜를
    # 낮 시각으로 고정한 것이므로, 그 "날짜 고정" 때문에 원래 시각에서 최대
    # 하루(24시간)까지만 벗어난다. 그래서 "warning_target <= as_of"이려면
    # 최소한 "judging_ends_at + WAIT_DAYS - LEAD_DAYS <= as_of + 1일"이어야
    # 한다 — 이 필요조건을 만족하지 못하는(=judging_ends_at이 이 상한보다 큰)
    # Contest는 진짜 대상일 수가 없으므로 안전하게 걸러낸다.
    judging_ends_at_cutoff = (
        as_of
        + timedelta(days=1)
        - timedelta(days=policy.distribution_wait_days)
        + timedelta(days=policy.distribution_final_warning_lead_days)
    )

    due = list(
        Contest.objects.filter(
            status=Contest.Status.JUDGING_ENDED,
            distribution__isnull=True,
            distribution_final_warning_sent_at__isnull=True,
            judging_ends_at__isnull=False,
            judging_ends_at__lte=judging_ends_at_cutoff,
        )
        .select_related("sponsor__user")
        .order_by("judging_ends_at", "id")[:BATCH_SIZE]
    )

    results = []
    for contest in due:
        if _budget_exhausted(deadline):
            logger.warning(
                "Distribution 최종 경고 스캔이 시간 예산을 넘겨 중단한다 — "
                "나머지 Contest는 다음 스캔에서 처리된다."
            )
            break
        try:
            distribution_due_at = contest.judging_ends_at + timedelta(
                days=policy.distribution_wait_days
            )
            warning_target = _constructed_daytime_target(
                distribution_due_at,
                lead_days=policy.distribution_final_warning_lead_days,
                hour=settings.NOTIFICATION_DAYTIME_HOUR,
            )
            if as_of < warning_target:
                continue

            _safe_notify_once(
                recipient=contest.sponsor.user,
                notification_type=NotificationType.DISTRIBUTION_FINAL_WARNING,
                dedup_context={"contest_id": contest.id},
                context={
                    "contest_id": contest.id,
                    "contest_title": contest.title,
                    "amount": contest.prize,
                    "distribution_due_at": distribution_due_at.isoformat(),
                },
            )
            Contest.objects.filter(
                pk=contest.pk, distribution_final_warning_sent_at__isnull=True
            ).update(distribution_final_warning_sent_at=as_of)
            results.append(
                {
                    "event": "distribution_final_warning_sent",
                    "contest_id": contest.id,
                    "amount": contest.prize,
                }
            )
        except Exception:  # noqa: BLE001 - 한 Contest의 실패가 배치를 막으면 안 된다.
            logger.exception(
                "Contest(pk=%s) Distribution 최종 경고 처리 중 예외, 다음 건으로 계속", contest.id
            )

    return results


# --- 결과 알림 복구: Award / Distribution -----------------------------------------


def send_pending_award_result_notices(as_of=None, deadline=None) -> list[dict]:
    """`notify_award_result`가 끝까지 완료되지 못한 Award를 다시 찾아 마저 알린다.

    awards.api.award_submission이 커밋 직후 호출하는 즉시 경로가 보통의 경우를
    이미 처리한다 — 이 스캔은 그 즉시 경로가 프로세스 강제종료 등으로 끝까지
    완료되지 못하고 죽은 나머지만 쓸어담는 복구 경로다(#19 리뷰 지적 3: "발송하고
    잊어버리는" 방식이 아니라, 언젠가 누군가 실제로 재시도한다는 보장이 있어야
    한다). `Award.result_notice_sent_at`이 비어 있는 행이 "아직 완료되지 않았다"
    는 표식이다.

    `deadline`은 `send_due_deadline_reminders`와 같다(#51 2차 코드리뷰 지적 2).
    """

    from awards.models import Award

    as_of = as_of or Clock.now()
    pending = list(
        Award.objects.filter(result_notice_sent_at__isnull=True)
        .select_related("submission__developer__user", "contest")
        .order_by("id")[:RESULT_NOTICE_BATCH_SIZE]
    )

    results = []
    for award in pending:
        if _budget_exhausted(deadline):
            logger.warning(
                "Award 결과 알림 복구 스캔이 시간 예산을 넘겨 중단한다 — "
                "나머지는 다음 스캔에서 처리된다."
            )
            break
        notify_award_result(award)
        award.refresh_from_db(fields=["result_notice_sent_at"])
        if award.result_notice_sent_at is not None:
            results.append({"event": "award_result_notice_recovered", "award_id": award.id})

    return results


def send_pending_distribution_share_result_notices(as_of=None, deadline=None) -> list[dict]:
    """`notify_distribution_shares`가 끝까지 완료되지 못한 몫을 다시 찾아 마저 알린다.

    `send_pending_award_result_notices`와 같은 이유·같은 구조다(#19 리뷰 지적
    3) — `distributions.services._create_distribution_for_contest`의 즉시
    경로가 대부분을 처리하고, 이 스캔은 죽은 나머지만 복구한다.
    `DistributionShare.result_notice_sent_at`이 비어 있는 몫이 대상이다.

    `deadline`은 `send_due_deadline_reminders`와 같다(#51 2차 코드리뷰 지적 2)
    — `notify_distribution_shares`에도 그대로 넘겨, Distribution 하나가
    수신자를 많이 가진 경우(팬아웃)에도 예산이 지켜지게 한다.
    """

    from distributions.models import DistributionShare

    as_of = as_of or Clock.now()
    pending = list(
        DistributionShare.objects.filter(result_notice_sent_at__isnull=True)
        .select_related("submission__developer__user", "distribution__contest")
        .order_by("id")[:RESULT_NOTICE_BATCH_SIZE]
    )

    # notify_distribution_shares는 (distribution, [submission, ...]) 모양을
    # 기대한다 — Distribution별로 몫을 묶어 그 함수를 그대로 재사용한다.
    by_distribution: dict[int, list] = {}
    for share in pending:
        by_distribution.setdefault(share.distribution_id, []).append(share)

    results = []
    for shares in by_distribution.values():
        if _budget_exhausted(deadline):
            logger.warning(
                "Distribution 결과 알림 복구 스캔이 시간 예산을 넘겨 중단한다 "
                "— 나머지는 다음 스캔에서 처리된다."
            )
            break
        distribution = shares[0].distribution
        submissions = [share.submission for share in shares]
        notify_distribution_shares(distribution, submissions, deadline=deadline)
        for share in shares:
            share.refresh_from_db(fields=["result_notice_sent_at"])
            if share.result_notice_sent_at is not None:
                results.append(
                    {
                        "event": "distribution_result_notice_recovered",
                        "submission_id": share.submission_id,
                    }
                )

    return results


def run_due_lifecycle_notifications(as_of=None) -> list[dict]:
    """다섯 스캔(마감 임박·심사기간 종료 임박·Distribution 최종 경고·Award/
    Distribution 결과 알림 복구)을 한 번에 돈다.

    이 호출(스캔 스코프) 전체에서 정책을 한 번만 읽어 세 리드타임 스캔에
    같이 넘긴다(#78, ADR-0023) — `as_of`를 한 번만 구해 재사용하는 것과
    같은 이유다. 시간 예산(LIFECYCLE_TIME_BUDGET_SECONDS)도 이 호출 전체에서
    한 번만 계산해 다섯 스캔에 같이 넘긴다(#51 2차 코드리뷰 지적 2) — 다섯
    스캔 각자 별도의 12초를 받으면 합이 60초까지 늘어나 gunicorn/Celery의
    30초 요청 타임아웃을 넘긴다.
    """

    as_of = as_of or Clock.now()
    policy = get_current_policy()
    deadline = time_module.monotonic() + LIFECYCLE_TIME_BUDGET_SECONDS
    results: list[dict] = []
    results += send_due_deadline_reminders(as_of=as_of, policy=policy, deadline=deadline)
    results += send_due_judging_end_reminders(as_of=as_of, policy=policy, deadline=deadline)
    results += send_due_distribution_final_warnings(as_of=as_of, policy=policy, deadline=deadline)
    results += send_pending_award_result_notices(as_of=as_of, deadline=deadline)
    results += send_pending_distribution_share_result_notices(as_of=as_of, deadline=deadline)
    return results


# --- 결과 알림: Award / Distribution ----------------------------------------------


def notify_award_result(award) -> None:
    """Award가 확정된 직후(또는 복구 스캔에 의해 나중에) 우승 Developer에게
    결과를 알린다.

    호출자(`awards.api.award_submission`)의 응답을 절대 막지 않는다 — 이
    함수 자체가 모든 예외를 삼킨다(#19 AC, ADR-0009). `result_notice_sent_at`
    이 이미 채워져 있으면 아무 것도 다시 하지 않는다 — `send_pending_award_
    result_notices`의 재시도가 중복 발송을 만들지 않는 이유가 이것이다(#19
    리뷰 지적 3).
    """

    try:
        if award.result_notice_sent_at is not None:
            return

        submission = award.submission
        contest = award.contest
        _safe_notify(
            recipient=submission.developer.user,
            notification_type=NotificationType.RESULT_NOTICE,
            context={
                "contest_id": contest.id,
                "contest_title": contest.title,
                "outcome": "awarded",
            },
        )
        now = Clock.now()
        type(award).objects.filter(pk=award.pk, result_notice_sent_at__isnull=True).update(
            result_notice_sent_at=now
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 Award 응답을 막으면 안 된다.
        logger.exception(
            "Award(pk=%s) 결과 알림 처리 중 예외 — Award 자체는 이미 커밋됐다",
            getattr(award, "pk", None),
        )


def notify_distribution_shares(distribution, qualifying_submissions, deadline=None) -> None:
    """Distribution이 만들어진 직후(또는 복구 스캔에 의해 나중에) 배분받은
    Developer들에게 금액과 함께 알린다.

    호출자(`distributions.services._create_distribution_for_contest`)가 이미
    DB 트랜잭션을 커밋한 뒤에 불러야 한다 — 알림 실패가 그 트랜잭션을 되돌리면
    안 된다(#19 AC: "전 채널이 미도달이어도 Distribution이 예정대로 실행된다",
    ADR-0009). 이 함수 자체도 모든 예외를 삼킨다 — 이중으로 안전하다. 각
    Submission의 `DistributionShare.result_notice_sent_at`이 이미 채워져
    있으면 그 몫만 건너뛴다 — `send_pending_distribution_share_result_notices`
    의 재시도가 이미 보낸 몫까지 다시 보내지 않는 이유다(#19 리뷰 지적 3).

    `deadline`은 기본값 None이라 즉시 경로(`distributions.services.
    _create_distribution_for_contest`)의 동작은 그대로다 — 시간 예산은
    복구 스캔(`send_pending_distribution_share_result_notices`)만 넘긴다
    (#51 2차 코드리뷰 지적 2). 예산을 넘기면 남은 몫은 건드리지 않는다 —
    `result_notice_sent_at`이 비어 있으므로 다음 복구 스캔이 안전하게
    이어받는다.
    """

    try:
        contest = distribution.contest
        now = Clock.now()
        for submission in qualifying_submissions:
            if _budget_exhausted(deadline):
                logger.warning(
                    "Distribution(pk=%s) 결과 알림 팬아웃이 시간 예산을 넘겨 "
                    "중단한다 — 남은 몫은 다음 복구 스캔에서 이어서 보낸다.",
                    distribution.pk,
                )
                break
            share = submission.distribution_share
            if share.result_notice_sent_at is not None:
                continue

            _safe_notify(
                recipient=submission.developer.user,
                notification_type=NotificationType.RESULT_NOTICE,
                context={
                    "contest_id": contest.id,
                    "contest_title": contest.title,
                    "outcome": "distributed",
                    "amount": distribution.share_amount,
                },
            )
            type(share).objects.filter(pk=share.pk, result_notice_sent_at__isnull=True).update(
                result_notice_sent_at=now
            )
    except Exception:  # noqa: BLE001 - 알림 실패가 Distribution 실행을 막으면 안 된다.
        logger.exception(
            "Distribution(pk=%s) 결과 알림 처리 중 예외 — Distribution 자체는 이미 커밋됐다",
            getattr(distribution, "pk", None),
        )
