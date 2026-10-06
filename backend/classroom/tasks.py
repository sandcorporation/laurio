"""강의실 채점 Celery 태스크 (#378, #582, ADR-0046, ADR-0056).

**강의실 채점은 이 태스크 하나로만 돈다 — 워커 안에서 직접.** 내부 HTTP 를 거치지
않는다(ADR-0003 「진입점은 내부 HTTP 하나」의 예외, ADR-0056 — 선례는 `core.
backup_database`). 진입 계기는 둘이고 둘 다 큐에 넣기만 한다: 강의실 제출이 커밋된 직후
(`classroom.api`)와 60초 안전망 스캔(`classroom-submission-scoring`). 큐에 넣는 자리는
`classroom.scoring.enqueue_scoring` 하나다.

**왜 워커 안인가.** #581(GlitchTip 오류 87)까지는 이 태스크가 backend 의 내부 엔드포인트를
`call_internal`(30초)로 불렀고 채점은 그 요청을 받은 gunicorn 워커(`--timeout` 기본 30초)
안에서 돌았다 — 벤더가 30초보다 늦으면 워커가 채점 도중 죽어 시도 기록도 남지 않았다.
워커 안에서는 그 예산이 없으므로 벤더를 3분(`classroom.scoring.
CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS`)까지 기다린다.

**시간 한도가 벤더 타임아웃을 감싼다.** 벤더 180초 < soft 210초 < hard 240초 < 큐 창
5분(`classroom.scoring.SCORING_QUEUE_WINDOW`). soft 한도는 채점 도중
`SoftTimeLimitExceeded` 를 던지고, `_score_one` 이 그것을 실패한 시도로 남긴다 — 실패
한도(5회)에 닿는다. hard 한도는 프로세스를 죽인다(그때는 기록이 없고, 5분 뒤 스캔이 다시
줍는다). 배포 compose 의 `celery-scoring` 은 hard 한도만큼 따뜻한 종료를 기다린다
(`stop_grace_period`).

**두 번 불러도 한 번만 채점한다.** 같은 시도의 태스크가 둘 돌 수 있다(즉시 채점과 스캔이
겹치거나 메시지가 재전달될 때) — `_score_one` 의 `select_for_update(skip_locked=True)` 와
「이미 채점됨」 확인이 벤더 호출을 하나로 막는다.

**재시도하지 않는다.** 채점 실패는 `ClassroomScoringAttempt` 로 남고 다음 스캔 tick 이 다시
넣는다 — Celery 재시도와 스캔이 함께 다시 부르면 실패 한도를 두 배로 빨리 쓴다.

**dev·CI 는 eager 다**(`CELERY_TASK_ALWAYS_EAGER`) — 큐에 넣는 자리에서 이 태스크가 그대로
돈다. 그래서 제출 요청과 스캔 요청 안에서 (흉내 어댑터로) 채점이 끝난다.

**결과를 받지 않는다**(`ignore_result`, #378 후속) — 채점 결과는 ClassroomScore 로 남고
아무도 AsyncResult 를 읽지 않는다.
"""

from celery import shared_task

from .scoring import score_classroom_attempt

#: 벤더 타임아웃(180초)에 프롬프트 구성·소스 읽기·DB 의 여유 30초를 더한 값 — 이 시각에
#: 채점 도중 `SoftTimeLimitExceeded` 가 나 실패한 시도로 남는다.
SCORING_SOFT_TIME_LIMIT_SECONDS = 210
#: soft 한도에 걸린 뒤 기록을 마칠 30초를 더 준다. 넘으면 워커가 프로세스를 죽인다.
SCORING_HARD_TIME_LIMIT_SECONDS = 240


@shared_task(
    name="classroom.score_attempt",
    ignore_result=True,
    soft_time_limit=SCORING_SOFT_TIME_LIMIT_SECONDS,
    time_limit=SCORING_HARD_TIME_LIMIT_SECONDS,
)
def score_attempt(submission_id: int) -> dict:
    """`ClassroomSubmission` 하나를 채점한다 — 스캔과 같은 후보 조건·같은 행 처리 함수
    (`classroom.scoring.score_classroom_attempt`). 조건 밖의 시도(키 없음·이미 채점됨 등)는
    조용히 건너뛴 결과가 돌아올 뿐 실패하지 않는다."""

    return score_classroom_attempt(submission_id)
