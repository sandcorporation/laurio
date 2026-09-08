"""AI 채점 내부 엔드포인트 (#12, ADR-0006, ADR-0007, ADR-0014, #223/ADR-0031).

core의 내부 틱 엔드포인트와 같은 `InternalAuth`를 쓴다. 채점 스캔 자체는 여기 없다 —
`scoring.services.SUBMISSION_SCORING_SCAN`(등록부 이름 `submission-scoring`, #139)이
core.scans 등록부에 올라 Celery beat 가 주기적으로 돌린다.
"""

from __future__ import annotations

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from ninja import Router

from contests.models import Contest
from core.auth import InternalAuth
from core.clock import Clock
from submissions.models import Submission

from .models import ScoringAttempt
from .services import SCORING_FAILURE_GRACE, SCORING_FAILURE_LIMIT

router = Router(tags=["internal", "scoring"], auth=InternalAuth())


@router.get("/incomplete-contests")
def incomplete_contests(request):
    """채점이 끝나지 않은 Contest를 운영자가 식별하는 진입점 (#12 AC, #223으로 확장).

    Distribution(#16)이 Score 스냅샷을 근거로 배분하기 전에 이 목록이 비어 있어야
    안전하다 — 그 게이트 자체는 만들지 않지만, 운영자가 여기서 미리 확인할 수 있다.

    **#223(ADR-0031)이 "Contest 당 건수 하나·최근 실패 사유 하나"에서 제출별
    상세로 넓힌다.** #222가 실패 상한(`SCORING_FAILURE_LIMIT`회·마감 후
    `SCORING_FAILURE_GRACE`)에 이른 제출을 0%로 강제 확정하므로, 그 유예 창이
    사람이 개입할 수 있는 유일한 시간이다 — 운영자가 "지금 몇 번째 시도 중이고
    언제 굳는가"를 여기서 한 번에 봐야 그 창이 장식이 되지 않는다. 새 엔드포인트를
    만들지 않고 운영자가 이미 치던 이 자리를 넓힌다.

    Submission마다:

    - `attempt_count`·`latest_error` — `ScoringAttempt` 집계(#221/#222와 같은 방식,
      `Submission`에 카운터를 두지 않는다).
    - `permanent` — 영구 실패가 하나라도 있으면 True. 유예를 기다리지 않고 다음
      스캔에서 즉시 0%로 확정되므로 `finalizes_at`이 없다(`waiting_on`도 전부
      False — 이미 확정 가능하다는 뜻이다).
    - `waiting_on` — 유예의 두 조건 중 아직 못 채운 것. `attempts`는 시도 횟수가
      상한에 못 미쳤다는 뜻이고 `grace_period`는 마감 후 유예가 아직 안 지났다는
      뜻이다 — 독립적으로 참·거짓이라 어느 쪽이 남았는지 구별된다.
    - `finalizes_at` — 마감(`deadline_at`) + `SCORING_FAILURE_GRACE`. 시도 횟수
      조건이 아직 안 찼어도 이 시각보다 먼저 굳을 수는 없으므로 항상 계산해
      돌려준다(하한선).

    **쿼리 수는 Contest·Submission 수와 무관하게 상수다.** Contest별 통계(총
    제출 수·미채점 수)를 한 annotate 쿼리로, 그 Contest들에 속한 미채점
    Submission 전부(시도 횟수·최근 오류·영구 실패 여부)를 서브쿼리로 annotate한
    또 한 쿼리로 가져온 뒤, 나머지는 파이썬에서 묶는다 — Contest마다 반복하던
    옛 루프(제출 수·미채점 수·최근 이력을 Contest당 세 번씩)를 없앤다.
    """

    now = Clock.now()

    # Contest별 통계 — 한 쿼리. 어느 status가 채점 대상인지는 Contest.Status.
    # SCOREABLE이 답한다(#141) — 스캔과 같은 질문이다.
    contests = list(
        Contest.objects.filter(status__in=Contest.Status.SCOREABLE.statuses)
        .annotate(
            total_submissions=Count("submissions", distinct=True),
            unscored_submissions=Count(
                "submissions", filter=Q(submissions__score__isnull=True), distinct=True
            ),
        )
        .filter(unscored_submissions__gt=0)
        .order_by("deadline_at")
    )
    if not contests:
        return {"count": 0, "contests": []}

    contest_by_id = {contest.id: contest for contest in contests}

    # 그 Contest들에 속한 미채점 Submission 전부 — 한 쿼리. attempt_count는
    # #221/#222와 같은 서브쿼리 집계 관용구다.
    attempt_count_subquery = (
        ScoringAttempt.objects.filter(submission=OuterRef("pk"))
        .order_by()
        .values("submission")
        .annotate(count=Count("id"))
        .values("count")
    )
    latest_error_subquery = (
        ScoringAttempt.objects.filter(submission=OuterRef("pk"))
        .order_by("-attempted_at")
        .values("error")[:1]
    )
    has_permanent_subquery = Exists(
        ScoringAttempt.objects.filter(submission=OuterRef("pk"), permanent=True)
    )

    submissions = Submission.objects.filter(
        contest_id__in=contest_by_id.keys(), score__isnull=True
    ).annotate(
        attempt_count=Coalesce(Subquery(attempt_count_subquery), 0),
        latest_error=Subquery(latest_error_subquery),
        is_permanent=has_permanent_subquery,
    ).order_by("contest_id", "id")

    submissions_by_contest: dict[int, list[dict]] = {contest.id: [] for contest in contests}
    for submission in submissions:
        contest = contest_by_id[submission.contest_id]
        if submission.is_permanent:
            waiting_on = {"attempts": False, "grace_period": False}
            finalizes_at = None
        else:
            grace_deadline = contest.deadline_at + SCORING_FAILURE_GRACE
            waiting_on = {
                "attempts": submission.attempt_count < SCORING_FAILURE_LIMIT,
                "grace_period": now < grace_deadline,
            }
            finalizes_at = grace_deadline.isoformat()

        submissions_by_contest[contest.id].append(
            {
                "submission_id": submission.id,
                "attempt_count": submission.attempt_count,
                "latest_error": submission.latest_error,
                "permanent": submission.is_permanent,
                "waiting_on": waiting_on,
                "finalizes_at": finalizes_at,
            }
        )

    payload = [
        {
            "contest_id": contest.id,
            "title": contest.title,
            "total_submissions": contest.total_submissions,
            "unscored_submissions": contest.unscored_submissions,
            "submissions": submissions_by_contest[contest.id],
        }
        for contest in contests
    ]
    return {"count": len(payload), "contests": payload}
