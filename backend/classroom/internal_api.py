"""강의실 즉시 채점 내부 엔드포인트 (#378, ADR-0046).

`core.api`의 스캔 엔드포인트, `scoring.api`·`notifications.api`의 내부 라우터와
같은 `InternalAuth`를 쓴다 — 내부 토큰 없이는 401 이다. `classroom.tasks.
score_attempt` Celery 태스크가 부르는 자리이고, 스캔(`classroom-submission-
scoring`)이 안전망으로 도는 동안 이 자리는 시도 하나만 즉시 처리한다.
"""

from ninja import Router

from core.auth import InternalAuth

from .scoring import score_classroom_attempt

router = Router(tags=["internal", "classroom"], auth=InternalAuth())


@router.post("/attempts/{submission_id}/score")
def score_attempt(request, submission_id: int):
    """시도 하나를 채점한다 — 스캔이 행 하나를 처리하는 것과 같은 함수·같은
    후보 조건이다(`classroom.scoring.score_classroom_attempt`). 조건 밖이거나
    다른 경로가 이미 잠그고 있으면 200으로 그 사실만 돌려준다(#378 AC) — 존재
    자체를 감추지 않는다, 이 표면은 내부 토큰 뒤에 있다."""

    return score_classroom_attempt(submission_id)
