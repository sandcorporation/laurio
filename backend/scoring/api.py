"""AI 채점 내부 엔드포인트 (#12, ADR-0006, ADR-0007, ADR-0014).

core의 내부 틱 엔드포인트와 같은 `InternalAuth`를 쓴다. 채점 스캔 자체는 여기 없다 —
`scoring.services.SUBMISSION_SCORING_SCAN`(등록부 이름 `submission-scoring`, #139)이
core.scans 등록부에 올라 Celery beat 가 주기적으로 돌린다.
"""

from __future__ import annotations

from ninja import Router

from contests.models import Contest
from core.auth import InternalAuth
from submissions.models import Submission

from .models import ScoringAttempt

router = Router(tags=["internal", "scoring"], auth=InternalAuth())


@router.get("/incomplete-contests")
def incomplete_contests(request):
    """채점이 끝나지 않은 CLOSED Contest를 운영자가 식별하는 진입점 (#12 AC).

    Distribution(#16, 이 티켓 범위 밖)이 Score 스냅샷을 근거로 배분하기 전에
    이 목록이 비어 있어야 안전하다 — 그 게이트 자체는 만들지 않지만, 운영자가
    여기서 미리 확인할 수 있다.
    """

    payload = []
    # 어느 status 가 채점 대상인지는 Contest.Status.SCOREABLE 이 답한다(#141) — 스캔과 같은 질문이다.
    closed_contests = Contest.objects.filter(
        status__in=Contest.Status.SCOREABLE.statuses
    ).order_by("deadline_at")
    for contest in closed_contests:
        submissions = Submission.objects.filter(contest=contest)
        total = submissions.count()
        unscored = submissions.filter(score__isnull=True).count()
        if unscored == 0:
            continue
        latest_attempt = (
            ScoringAttempt.objects.filter(submission__contest=contest)
            .order_by("-attempted_at")
            .first()
        )
        payload.append(
            {
                "contest_id": contest.id,
                "title": contest.title,
                "total_submissions": total,
                "unscored_submissions": unscored,
                "latest_error": latest_attempt.error if latest_attempt else None,
            }
        )
    return {"count": len(payload), "contests": payload}
