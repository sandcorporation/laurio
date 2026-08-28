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
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from contests.models import Contest
from core.clock import Clock

from .models import NotificationType
from .services import create_notification

logger = logging.getLogger(__name__)

User = get_user_model()

# 한 스캔에서 처리하는 최대 Contest 수. core.transitions.DEFAULT_BATCH_SIZE·
# distributions.services.BATCH_SIZE와 같은 이유 — 무제한 스캔은 백로그가 쌓였을
# 때 이 요청 자체를 타임아웃으로 몰아넣는다.
BATCH_SIZE = 200


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


def _participating_developer_users(contest: Contest):
    """이 Contest에 Submission을 낸 Developer들의 User 목록(중복 없이)."""

    return User.objects.filter(developer_profile__submissions__contest=contest).distinct()


# --- 마감 임박 -------------------------------------------------------------------


def send_due_deadline_reminders(as_of=None) -> list[dict]:
    """마감이 다가오는 PUBLISHED Contest의 Sponsor와 참가 Developer에게 알린다.

    Contest 당 한 번만 보낸다 — `deadline_reminder_sent_at`이 비어 있는 행만
    대상으로 하고, 조건부 UPDATE로 실제 선점에 성공한 스캔만 알림을 만든다.
    스캔이 겹쳐 돌아도(core.transitions.claim_transition과 같은 정신) 중복
    발송되지 않는다.
    """

    as_of = as_of or Clock.now()
    lead = timedelta(hours=settings.DEADLINE_REMINDER_LEAD_HOURS)

    due = list(
        Contest.objects.filter(
            status=Contest.Status.PUBLISHED,
            deadline_reminder_sent_at__isnull=True,
            deadline_at__lte=as_of + lead,
        )
        .select_related("sponsor__user")
        .order_by("id")[:BATCH_SIZE]
    )

    results = []
    for contest in due:
        try:
            claimed = (
                Contest.objects.filter(
                    pk=contest.pk, deadline_reminder_sent_at__isnull=True
                ).update(deadline_reminder_sent_at=as_of)
                == 1
            )
            if not claimed:
                continue

            context = {
                "contest_id": contest.id,
                "contest_title": contest.title,
                "deadline_at": contest.deadline_at.isoformat(),
            }
            _safe_notify(
                recipient=contest.sponsor.user,
                notification_type=NotificationType.DEADLINE_REMINDER,
                context={**context, "role": "sponsor"},
            )
            for dev_user in _participating_developer_users(contest):
                _safe_notify(
                    recipient=dev_user,
                    notification_type=NotificationType.DEADLINE_REMINDER,
                    context={**context, "role": "developer"},
                )
            results.append({"event": "deadline_reminder_sent", "contest_id": contest.id})
        except Exception:  # noqa: BLE001 - 한 Contest의 실패가 배치를 막으면 안 된다.
            logger.exception("Contest(pk=%s) 마감 임박 알림 처리 중 예외, 다음 건으로 계속", contest.id)

    return results


# --- 심사기간 종료 임박 ------------------------------------------------------------


def send_due_judging_end_reminders(as_of=None) -> list[dict]:
    """심사기간 종료가 다가오는 CLOSED Contest의 Sponsor에게 Award를 상기시킨다."""

    as_of = as_of or Clock.now()
    lead = timedelta(hours=settings.JUDGING_END_REMINDER_LEAD_HOURS)

    due = list(
        Contest.objects.filter(
            status=Contest.Status.CLOSED,
            judging_end_reminder_sent_at__isnull=True,
            judging_ends_at__isnull=False,
            judging_ends_at__lte=as_of + lead,
        )
        .select_related("sponsor__user")
        .order_by("id")[:BATCH_SIZE]
    )

    results = []
    for contest in due:
        try:
            claimed = (
                Contest.objects.filter(
                    pk=contest.pk, judging_end_reminder_sent_at__isnull=True
                ).update(judging_end_reminder_sent_at=as_of)
                == 1
            )
            if not claimed:
                continue

            _safe_notify(
                recipient=contest.sponsor.user,
                notification_type=NotificationType.JUDGING_PERIOD_ENDING_REMINDER,
                context={
                    "contest_id": contest.id,
                    "contest_title": contest.title,
                    "judging_ends_at": contest.judging_ends_at.isoformat(),
                },
            )
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


def send_due_distribution_final_warnings(as_of=None) -> list[dict]:
    """Distribution 실행이 다가오는 JUDGING_ENDED Contest의 Sponsor에게 금액을
    명시한 최종 경고를 보낸다.

    아직 Distribution이 만들어지지 않은 Contest만 대상이다 — 이미 실행됐다면
    경고가 아니라 결과 통지(`notify_distribution_shares`)가 맞다.
    """

    as_of = as_of or Clock.now()

    due = list(
        Contest.objects.filter(
            status=Contest.Status.JUDGING_ENDED,
            distribution__isnull=True,
            distribution_final_warning_sent_at__isnull=True,
            judging_ends_at__isnull=False,
        )
        .select_related("sponsor__user")
        .order_by("id")[:BATCH_SIZE]
    )

    results = []
    for contest in due:
        try:
            distribution_due_at = contest.judging_ends_at + timedelta(
                days=settings.DISTRIBUTION_WAIT_DAYS
            )
            warning_target = _constructed_daytime_target(
                distribution_due_at,
                lead_days=settings.DISTRIBUTION_FINAL_WARNING_LEAD_DAYS,
                hour=settings.NOTIFICATION_DAYTIME_HOUR,
            )
            if as_of < warning_target:
                continue

            claimed = (
                Contest.objects.filter(
                    pk=contest.pk, distribution_final_warning_sent_at__isnull=True
                ).update(distribution_final_warning_sent_at=as_of)
                == 1
            )
            if not claimed:
                continue

            _safe_notify(
                recipient=contest.sponsor.user,
                notification_type=NotificationType.DISTRIBUTION_FINAL_WARNING,
                context={
                    "contest_id": contest.id,
                    "contest_title": contest.title,
                    "amount": contest.prize,
                    "distribution_due_at": distribution_due_at.isoformat(),
                },
            )
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


def run_due_lifecycle_notifications(as_of=None) -> list[dict]:
    """세 스캔(마감 임박·심사기간 종료 임박·Distribution 최종 경고)을 한 번에 돈다."""

    as_of = as_of or Clock.now()
    results: list[dict] = []
    results += send_due_deadline_reminders(as_of=as_of)
    results += send_due_judging_end_reminders(as_of=as_of)
    results += send_due_distribution_final_warnings(as_of=as_of)
    return results


# --- 결과 알림: Award / Distribution ----------------------------------------------


def notify_award_result(award) -> None:
    """Award가 확정된 직후 우승 Developer에게 결과를 알린다.

    호출자(`awards.api.award_submission`)의 응답을 절대 막지 않는다 — 이
    함수 자체가 모든 예외를 삼킨다(#19 AC, ADR-0009).
    """

    try:
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
    except Exception:  # noqa: BLE001 - 알림 실패가 Award 응답을 막으면 안 된다.
        logger.exception(
            "Award(pk=%s) 결과 알림 처리 중 예외 — Award 자체는 이미 커밋됐다",
            getattr(award, "pk", None),
        )


def notify_distribution_shares(distribution, qualifying_submissions) -> None:
    """Distribution이 만들어진 직후 배분받은 Developer들에게 금액과 함께 알린다.

    호출자(`distributions.services._create_distribution_for_contest`)가 이미
    DB 트랜잭션을 커밋한 뒤에 불러야 한다 — 알림 실패가 그 트랜잭션을 되돌리면
    안 된다(#19 AC: "전 채널이 미도달이어도 Distribution이 예정대로 실행된다",
    ADR-0009). 이 함수 자체도 모든 예외를 삼킨다 — 이중으로 안전하다.
    """

    try:
        contest = distribution.contest
        for submission in qualifying_submissions:
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
    except Exception:  # noqa: BLE001 - 알림 실패가 Distribution 실행을 막으면 안 된다.
        logger.exception(
            "Distribution(pk=%s) 결과 알림 처리 중 예외 — Distribution 자체는 이미 커밋됐다",
            getattr(distribution, "pk", None),
        )
