"""Contest 라이프사이클 이벤트를 notifications 기반(#18)에 연결한다 (#19).

이 모듈은 notifications 앱의 dispatch·quiet-hours·fallback 로직(services.py)을
전혀 바꾸지 않는다 — `create_notification`을 호출해 그 로직을 그대로 재사용할
뿐이다. 여기서 새로 정의하는 것은 "어떤 Contest 이벤트가 어떤 Notification을
언제, 누구에게 만드는가"뿐이다.

핵심 규율(#19 AC, ADR-0009): Notification 생성이 실패해도(어댑터 예외, DB
문제 등) 이를 호출한 쪽의 lifecycle 전이·Distribution 실행은 절대 막히지
않는다. 그래서 이 모듈의 "결과 알림" 공개 함수(`notify_award_result`,
`notify_distribution_shares`)는 내부에서 예외를 전부 잡고 로깅만 한다 —
호출자에게 예외를 전파하지 않는다. 스캔 다섯(`LIFECYCLE_SCANS`, #138)은 core.scans
의 뼈대가 행 단위로 예외를 격리한다 — 한 행의 실패가 배치를 막지 않는다.

리뷰 지적(#19) 이후의 두 번째 규율: **완료 표시는 실제로 다 보낸 뒤에만
남긴다.** "보내기 전에 먼저 완료로 찍고 나서 보낸다"는 순서는, 그 사이(특히
여러 수신자를 순회하는 팬아웃 도중)에 프로세스가 죽으면 "이미 끝났다"는
표시만 남고 알림은 일부(또는 전부) 못 나간 채로 영원히 다시 시도되지 않는
사고를 만든다. 그래서 이 모듈의 모든 스캔·결과 알림 함수는 (1) 수신자별로
`_safe_notify_once`(이미 보낸 적 있으면 건너뛴다)로 시도한 뒤 (2) 그 뒤에만
완료 표시를 남긴다 — 중간에 죽어도 다음 스캔이 "아직 못 받은 수신자만" 안전하게
마저 처리한다.

다섯 스캔은 각자 등록부 항목이라 **각자 자기 예산**으로 돈다(#138) — 예전에는 한
엔드포인트가 다섯을 고정 순서로 돌리며 예산을 나눠 썼고, 앞 스캔(마감 임박 팬아웃)이
자기 몫을 넘길 때마다 뒤의 복구 스캔이 굶었다(#51 3차 코드리뷰 지적 4). 이제 그 구조
자체가 없다. 팬아웃 **안쪽**의 예산 확인은 `core.scans.budget_exhausted(ctx)` 로 한다 —
예산으로 중단된 Contest 는 완료 표시가 없으므로 다음 실행이 안전하게 이어받는다.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from contests.models import Contest
from core import scans
from core.clock import Clock
from core.scans import ScanSpec
from policies.scope import current_policy

from .models import NotificationType
# `_safe_notify`/`_safe_notify_once`는 원래 이 모듈에서 정의됐다(#19). #169가
# 지급 알림 스캔(`payouts.notifications`)에서도 같은 "예외를 삼킨다"·"dedup_context로
# 한 번만 만든다" 관용구가 필요해 `notifications.services`로 옮겼다 — 이름은
# 이 모듈의 나머지 호출부(아래 다섯 스캔)가 안 바뀌도록 그대로 별칭한다.
from .services import notify_once as _safe_notify_once
from .services import notify_safely as _safe_notify

logger = logging.getLogger(__name__)

User = get_user_model()

def _budget_exhausted(ctx) -> bool:
    """이번 스캔 실행의 예산이 다 됐는가 — 즉시 경로(ctx=None)에서는 예산이 없다."""

    return ctx is not None and scans.budget_exhausted(ctx)


def _participating_developer_users(contest: Contest):
    """이 Contest에 Submission을 낸 Developer들의 User 목록(중복 없이)."""

    return User.objects.filter(developer_profile__submissions__contest=contest).distinct()


# --- 마감 임박 -------------------------------------------------------------------


def _deadline_reminder_candidates(as_of, ctx):
    """마감이 다가오는 PUBLISHED Contest — Contest 당 한 번만 "완료"로 표시하므로
    `deadline_reminder_sent_at` 이 비어 있는 행만 대상이다."""

    lead = timedelta(hours=current_policy().deadline_reminder_lead_hours)
    return Contest.objects.filter(
        status__in=Contest.Status.SUBMITTABLE.statuses,
        deadline_reminder_sent_at__isnull=True,
        deadline_at__lte=as_of + lead,
    ).select_related("sponsor__user")


def _send_deadline_reminder(contest, as_of, ctx):
    """Sponsor 와 참가 Developer 전원에게 알린 **뒤에만** 완료 표시를 남긴다(#19 리뷰 지적 2)
    — 참가자가 많은 Contest에서 팬아웃 도중 타임아웃·재배포로 죽으면, 표시를 먼저 찍는
    예전 방식은 남은 수신자를 영원히 못 받게 만들었다. `_safe_notify_once`가 이미 받은
    수신자에게 중복 발송하지 않으므로, 다음 실행이 이 Contest를 다시 집어도 안전하다.

    팬아웃 도중 예산이 다 되면 그 자리에서 멈추고 완료 표시를 남기지 않는다 — 이미 보낸
    수신자는 다음 실행에서 건너뛰고, 못 보낸 나머지만 이어서 보낸다.
    """

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
    for dev_user in _participating_developer_users(contest):
        if _budget_exhausted(ctx):
            logger.warning(
                "Contest(pk=%s) 마감 임박 알림 팬아웃이 시간 예산을 넘겨 중단한다 — 남은 "
                "참가자는 다음 실행에서 이어서 받는다.",
                contest.id,
            )
            return None
        _safe_notify_once(
            recipient=dev_user,
            notification_type=NotificationType.DEADLINE_REMINDER,
            dedup_context={"contest_id": contest.id},
            context={**context, "role": "developer"},
        )
    Contest.objects.filter(pk=contest.pk, deadline_reminder_sent_at__isnull=True).update(
        deadline_reminder_sent_at=as_of
    )
    return {"event": "deadline_reminder_sent", "contest_id": contest.id}


# --- 심사기간 종료 임박 ------------------------------------------------------------


def _judging_end_reminder_candidates(as_of, ctx):
    """심사기간 종료가 다가오는 CLOSED Contest. 유료 연장(`JudgingExtensionPayment.on_paid`)이
    `judging_ends_at`을 늘릴 때 `judging_end_reminder_sent_at`도 함께 비운다(#19 리뷰 지적 1)
    — 그래야 연장된 새 종료일이 다가올 때 이 스캔이 다시 알릴 수 있다."""

    lead = timedelta(hours=current_policy().judging_end_reminder_lead_hours)
    return Contest.objects.filter(
        status__in=Contest.Status.AWARDABLE.statuses,
        judging_end_reminder_sent_at__isnull=True,
        judging_ends_at__isnull=False,
        judging_ends_at__lte=as_of + lead,
    ).select_related("sponsor__user")


def _send_judging_end_reminder(contest, as_of, ctx):
    # judging_ends_at을 dedup_context에 함께 넣는다 — 유료 연장이 이 값을 바꾸면서
    # judging_end_reminder_sent_at도 함께 비우므로(#19 리뷰 지적 1), 이 존재 검사가
    # "예전(연장 전) 종료일에 대한 알림"까지 같은 것으로 보고 새 알림을 막아버리면 안
    # 된다. 새 judging_ends_at은 이전 값과 다르므로, 이 필터는 "이번 종료일에 대해서는
    # 아직 안 보냈다"만 정확히 검사한다.
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
    Contest.objects.filter(pk=contest.pk, judging_end_reminder_sent_at__isnull=True).update(
        judging_end_reminder_sent_at=as_of
    )
    return {"event": "judging_end_reminder_sent", "contest_id": contest.id}


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


def _final_warning_candidates(as_of, ctx):
    """Distribution 실행이 다가오는 JUDGING_ENDED Contest — 아직 Distribution이 만들어지지
    않은 것만(이미 실행됐다면 경고가 아니라 결과 통지가 맞다).

    경고 시각(`warning_target`)은 `judging_ends_at`으로부터 정확히 선형으로 계산되지
    않는다(`_constructed_daytime_target`이 로컬 날짜 경계에서 시각을 고정한다) — 그래서
    DB 쿼리만으로는 정확한 조건을 표현할 수 없다. 대신 `judging_ends_at__lte=cutoff` 는
    "확실히 아직 멀었다"는 Contest만 걸러내는, **절대 과소포함하지 않는** 느슨한
    상한이다(#19 리뷰 지적 4) — 이 필터가 없으면 아직 멀었지만 개수가 많은 후보들이
    배치를 다 채워, 실제로 마감된 경고가 이번 실행에서 밀려날 수 있다(특히 유료 연장으로
    id 순서와 judging_ends_at 순서가 어긋나기 시작하면). 정확한 최종 판정은 행 처리의
    `_constructed_daytime_target` 비교가 한다.
    """

    policy = current_policy()
    # warning_target은 (judging_ends_at + WAIT_DAYS - LEAD_DAYS)의 로컬 날짜를 낮 시각으로
    # 고정한 것이므로, 그 "날짜 고정" 때문에 원래 시각에서 최대 하루(24시간)까지만
    # 벗어난다. 그래서 "warning_target <= as_of"이려면 최소한 "judging_ends_at + WAIT_DAYS
    # - LEAD_DAYS <= as_of + 1일"이어야 한다 — 이 필요조건을 만족하지 못하는 Contest는
    # 진짜 대상일 수가 없으므로 안전하게 걸러낸다.
    cutoff = (
        as_of
        + timedelta(days=1)
        - timedelta(days=policy.distribution_wait_days)
        + timedelta(days=policy.distribution_final_warning_lead_days)
    )
    return Contest.objects.filter(
        status__in=Contest.Status.AWAITING_DISTRIBUTION.statuses,
        distribution__isnull=True,
        distribution_final_warning_sent_at__isnull=True,
        judging_ends_at__isnull=False,
        judging_ends_at__lte=cutoff,
    ).select_related("sponsor__user")


def _send_final_warning(contest, as_of, ctx):
    """`NOTIFICATION_DAYTIME_HOUR`(낮 시각 자체를 고정하는 상수)는 settings에 그대로 남는다."""

    policy = current_policy()
    distribution_due_at = contest.judging_ends_at + timedelta(days=policy.distribution_wait_days)
    warning_target = _constructed_daytime_target(
        distribution_due_at,
        lead_days=policy.distribution_final_warning_lead_days,
        hour=settings.NOTIFICATION_DAYTIME_HOUR,
    )
    if as_of < warning_target:
        return None
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
    Contest.objects.filter(pk=contest.pk, distribution_final_warning_sent_at__isnull=True).update(
        distribution_final_warning_sent_at=as_of
    )
    return {
        "event": "distribution_final_warning_sent",
        "contest_id": contest.id,
        "amount": contest.prize,
    }


# --- 결과 알림 복구: Award / Distribution -----------------------------------------
#
# awards.api.award_submission / distributions.services._create_distribution_for_contest 가
# 커밋 직후 부르는 즉시 경로가 보통의 경우를 이미 처리한다 — 이 두 스캔은 그 즉시 경로가
# 프로세스 강제종료 등으로 끝까지 완료되지 못하고 죽은 나머지만 쓸어담는 복구 경로다
# (#19 리뷰 지적 3: "발송하고 잊어버리는" 방식이 아니라, 언젠가 누군가 실제로 재시도한다는
# 보장이 있어야 한다). `result_notice_sent_at`이 비어 있는 행이 "아직 완료되지 않았다"는
# 표식이다.


def _pending_award_notices(as_of, ctx):
    from awards.models import Award

    return Award.objects.filter(result_notice_sent_at__isnull=True).select_related(
        "submission__developer__user", "contest"
    )


def _recover_award_notice(award, as_of, ctx):
    notify_award_result(award)
    award.refresh_from_db(fields=["result_notice_sent_at"])
    if award.result_notice_sent_at is None:
        return None
    return {"event": "award_result_notice_recovered", "award_id": award.id}


def _pending_share_notices(as_of, ctx):
    from distributions.models import DistributionShare

    return DistributionShare.objects.filter(result_notice_sent_at__isnull=True).select_related(
        "submission__developer__user", "distribution__contest"
    )


def _recover_share_notice(share, as_of, ctx):
    # notify_distribution_shares 는 (distribution, [submission, ...]) 모양을 기대한다 —
    # 몫 하나짜리 목록으로 그 함수를 그대로 재사용한다. 예산(ctx)도 넘겨 팬아웃에서도
    # 지켜지게 한다.
    notify_distribution_shares(share.distribution, [share.submission], ctx=ctx)
    share.refresh_from_db(fields=["result_notice_sent_at"])
    if share.result_notice_sent_at is None:
        return None
    return {"event": "distribution_result_notice_recovered", "submission_id": share.submission_id}


# 배치 200 은 예전 BATCH_SIZE·RESULT_NOTICE_BATCH_SIZE 그대로다. 예산은 뼈대 기본(20초) —
# 예전의 12초/5 는 한 엔드포인트가 다섯을 나눠 쓰던 구조의 산물이었다.
LIFECYCLE_SCANS = (
    ScanSpec(
        name="deadline-reminder",
        candidates=_deadline_reminder_candidates,
        handle_row=_send_deadline_reminder,
        batch_size=200,
        order_by=("deadline_at", "id"),
    ),
    ScanSpec(
        name="judging-end-reminder",
        candidates=_judging_end_reminder_candidates,
        handle_row=_send_judging_end_reminder,
        batch_size=200,
        order_by=("judging_ends_at", "id"),
    ),
    ScanSpec(
        name="distribution-final-warning",
        candidates=_final_warning_candidates,
        handle_row=_send_final_warning,
        batch_size=200,
        order_by=("judging_ends_at", "id"),
    ),
    ScanSpec(
        name="award-result-notice-recovery",
        candidates=_pending_award_notices,
        handle_row=_recover_award_notice,
        batch_size=200,
    ),
    ScanSpec(
        name="distribution-result-notice-recovery",
        candidates=_pending_share_notices,
        handle_row=_recover_share_notice,
        batch_size=200,
    ),
)


# --- 결과 알림: Award / Distribution ----------------------------------------------


def notify_award_result(award) -> None:
    """Award가 확정된 직후(또는 복구 스캔에 의해 나중에) 우승 Developer에게
    결과를 알린다.

    호출자(`awards.api.award_submission`)의 응답을 절대 막지 않는다 — 이
    함수 자체가 모든 예외를 삼킨다(#19 AC, ADR-0009). `result_notice_sent_at`
    이 이미 채워져 있으면 아무 것도 다시 하지 않는다 — `award-result-notice-recovery` 스캔의 재시도가 중복 발송을 만들지 않는 이유가 이것이다(#19
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


def notify_distribution_shares(distribution, qualifying_submissions, *, ctx=None) -> None:
    """Distribution이 만들어진 직후(또는 복구 스캔에 의해 나중에) 배분받은
    Developer들에게 금액과 함께 알린다.

    호출자(`distributions.services._create_distribution_for_contest`)가 이미
    DB 트랜잭션을 커밋한 뒤에 불러야 한다 — 알림 실패가 그 트랜잭션을 되돌리면
    안 된다(#19 AC: "전 채널이 미도달이어도 Distribution이 예정대로 실행된다",
    ADR-0009). 이 함수 자체도 모든 예외를 삼킨다 — 이중으로 안전하다. 각
    Submission의 `DistributionShare.result_notice_sent_at`이 이미 채워져
    있으면 그 몫만 건너뛴다 — `distribution-result-notice-recovery` 스캔
    의 재시도가 이미 보낸 몫까지 다시 보내지 않는 이유다(#19 리뷰 지적 3).

    `ctx`는 기본값 None이라 즉시 경로(`distributions.services.
    _create_distribution_for_contest`)의 동작은 그대로다 — 시간 예산은
    복구 스캔(`distribution-result-notice-recovery`)만 자기 실행의 ctx 를 넘긴다
    (#51 2차 코드리뷰 지적 2). 예산을 넘기면 남은 몫은 건드리지 않는다 —
    `result_notice_sent_at`이 비어 있으므로 다음 복구 스캔이 안전하게
    이어받는다.
    """

    try:
        contest = distribution.contest
        now = Clock.now()
        for submission in qualifying_submissions:
            if _budget_exhausted(ctx):
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
