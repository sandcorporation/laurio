"""정정이 끝나면 보내는 알림 둘(#1182, 스펙 #1178) — `scoring.corrections` 의 정정 완료 훅에 건다(상장·알림을 아는 쪽 — `scoring` 은 그 앱들을 모른다).

- 참가자: 「플랫폼 오류로 다시 채점했다」 — 원래 점수와 새 점수.
- 개최자: 정정된 제출에 취소되지 않은 상장이 있으면 한 번. 상장은 자동으로 취소하지 않는다(개최자가 상장 화면에서 정한다).
"""

from __future__ import annotations

from contests.models import ContestSubmission

from scoring.corrections import on_correction_done
from scoring.models import ScoreCorrection


@on_correction_done
def notify_correction_done(correction: ScoreCorrection) -> None:
    from certificates.models import Certificate
    from notifications.models import NotificationType
    from notifications.services import notify_safely

    submission = ContestSubmission.objects.select_related("contest__sponsor__user", "developer__user").get(
        pk=correction.score.submission_id
    )
    contest = submission.contest
    base = {
        "contest_id": contest.id,
        "contest_title": contest.title,
        "submission_id": submission.id,
        "correction_id": correction.id,
        "original_percentage": str(correction.score.percentage),
        "percentage": str(correction.percentage),
    }
    notify_safely(
        recipient=submission.developer.user,
        notification_type=NotificationType.SCORE_CORRECTED,
        context=base,
    )
    issued = Certificate.objects.filter(submission_id=submission.id, cancelled_at__isnull=True).count()
    if issued:
        notify_safely(
            recipient=contest.sponsor.user,
            notification_type=NotificationType.CERTIFICATE_SCORE_CORRECTED,
            context={**base, "count": issued},
        )
