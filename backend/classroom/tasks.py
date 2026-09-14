"""강의실 즉시 채점 Celery 태스크 (#378, ADR-0046).

`core.tasks.run_scan`과 같은 모양이다 — 내부 인증 HTTP 엔드포인트
(`/api/internal/classroom/attempts/{id}/score`) 하나를 부른다. 다른 점은 진입
계기뿐이다: beat 가 아니라 강의실 제출이 커밋된 직후 `classroom.api`가 한 번
`.delay()`로 큐에 넣는다.

**dev·CI 는 이 태스크가 돌지 않는다**(#40, Celery 가 dev 기본 기동에 없다) —
큐에 쌓인 채 아무도 소비하지 않고, 60초 `classroom-submission-scoring` 스캔이
안전망으로 그 시도를 대신 줍는다. 배포 환경(워커가 있는 곳)에서만 이 태스크가
실제로 그 안전망보다 먼저 채점을 시작한다.
"""

from celery import shared_task

from core.tasks import call_internal


# **결과를 받지 않는다**(`ignore_result`, #378 후속) — 채점 결과는 ClassroomScore 로 남고
# 아무도 AsyncResult 를 읽지 않는다. 결과를 받는 작업은 보낼 때 결과 백엔드(Redis)에 구독을
# 거는데, Redis 가 없으면 그 재연결에 19초가 묶였다(실측) — 제출 요청이 그만큼 멈췄다.
@shared_task(name="classroom.score_attempt", ignore_result=True)
def score_attempt(submission_id: int) -> dict:
    """`ClassroomSubmission` 하나를 즉시 채점한다 — 내부 엔드포인트가 스캔과
    같은 후보 조건·같은 행 처리 함수를 쓰므로(`classroom.scoring.
    score_classroom_attempt`), 조건 밖의 시도를 불러도 조용히 건너뛴 결과가
    돌아올 뿐 이 태스크가 실패하지는 않는다."""

    return call_internal(f"/api/internal/classroom/attempts/{submission_id}/score")
