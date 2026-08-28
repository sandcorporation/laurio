"""AI 채점 내부 엔드포인트 (#12, ADR-0006, ADR-0007, ADR-0014).

core의 내부 틱 엔드포인트와 같은 `InternalAuth`를 쓴다 — notifications의
`/internal/notifications/dispatch-due`와 같은 구조로, Contest 마감 전이 스캔
(core의 틱)과는 별개의 주기로 Celery beat가 반복 호출하는 채점 전용 스캔이다.
"""

from __future__ import annotations

from ninja import Router

from contests.models import Contest
from core.auth import InternalAuth
from submissions.models import Submission

from .models import ScoringAttempt
from .services import run_pending_scoring

router = Router(tags=["internal", "scoring"], auth=InternalAuth())


@router.post("/run-pending")
def run_pending(request):
    """CLOSED Contest 중 아직 채점되지 않은 Submission을 스캔해 채점을 시도한다.

    이미 Score가 있는 Submission은 항상 건너뛴다 — 재채점 경로는 없다(ADR-0006).
    실패한 시도는 다음 호출에서 자동으로 다시 시도된다.
    """

    results = run_pending_scoring()
    return {"count": len(results), "results": results}


@router.get("/incomplete-contests")
def incomplete_contests(request):
    """채점이 끝나지 않은 CLOSED Contest를 운영자가 식별하는 진입점 (#12 AC).

    Distribution(#16, 이 티켓 범위 밖)이 Score 스냅샷을 근거로 배분하기 전에
    이 목록이 비어 있어야 안전하다 — 그 게이트 자체는 만들지 않지만, 운영자가
    여기서 미리 확인할 수 있다.
    """

    payload = []
    closed_contests = Contest.objects.filter(status=Contest.Status.CLOSED).order_by("deadline_at")
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
