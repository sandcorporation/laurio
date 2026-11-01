"""Celery beat 가 주기적으로 실행하는 태스크 (#137, #140, ADR-0003).

ADR-0003: 스캔 진입점은 내부 인증 HTTP 엔드포인트다 — 워커·수동 curl·Celery beat 모두 같은
하나의 HTTP 경로를 거치게 해서, "두 번 쏴도 한 번만 통과한다"는 보장을 지키는 코드 경로가 단
하나만 존재하게 한다. 스캔 태스크는 하나뿐이다 — 등록부(`core.scans.SCAN_REGISTRY`)의 스캔
이름을 받아 `/api/internal/scans/{name}` 에 POST 한다. beat 스케줄은 그 등록부에서 파생되므로
「엔드포인트는 있는데 아무도 부르지 않는」 스캔(#23 코디네이터 리뷰가 잡았던 사고)은 표현
자체가 불가능하다.

**예외가 있다 — 워커 안에서 직접 도는 태스크.** 내부 HTTP 를 거치면 그 일이 gunicorn
요청 하나(`call_internal` 30초 — 넘으면 부른 쪽이 끊는다) 안에 들어야 하고, 요청 경로의 DB
한도(`core.db_timeouts`)도 받는다. 그럴 필요가 없거나 그보다 길 수 있는 일은 워커 안에서 직접 돈다:

- `contests.index_contest`(#450) — 공모전 하나를 검색 색인에 다시 싣는 멱등 갱신이라 HTTP
  경계를 하나 더 둘 이유가 없다.

강의실 채점은 celery 태스크가 아니다 — 상주 프로세스 `manage.py grader`(ADR-0059, #584)가
큐를 읽어 채점한다. #582 부터 #584 전까지는 워커 안의 `classroom.score_attempt` 태스크였다.

`call_internal`은 #378 부터 #582 전까지 강의실 즉시 채점 태스크도 썼다 — 그래서 이름 앞의
밑줄을 뗐다. 지금은 스캔 태스크만 부른다.
"""

import requests
from celery import shared_task
from django.conf import settings


def call_internal(path: str) -> dict:
    """`path`(예: "/api/internal/tick")로 내부 인증 POST 한 번을 보낸다.

    응답이 2xx가 아니면 `raise_for_status()`가 예외를 던진다 — Celery가 이 태스크를
    실패로 기록하고 재시도 정책(설정돼 있다면)을 그대로 적용한다. 실패를 여기서
    삼키지 않는다: 삼키면 "beat가 돌고는 있지만 매번 조용히 실패한다"는, 이번
    리뷰가 지적한 것과 같은 부류의 조용한 실패를 새로 만든다.
    """

    response = requests.post(
        f"{settings.INTERNAL_API_BASE_URL}{path}",
        headers={"X-Internal-Token": settings.INTERNAL_API_TOKEN},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# **배포 중에는 backend 가 잠깐 없다 — 그때의 연결 실패는 사고가 아니다**
# (2026-09-16). `deploy.sh` 가 backend 컨테이너를 바꿔 끼우는 몇 초 동안 beat 는
# 계속 돌아, 그 순간의 tick 이 `Connection refused` 로 죽는다(오류 수집기를 붙인
# 첫날 실제로 3건 올라왔다 — `notification-dispatch-deferred`). 스캔은 「두 번
# 쏴도 한 번만 통과한다」가 보장돼 있으므로(ADR-0003, 위 docstring) 다시 쏘는
# 것이 안전하다. 그래서 연결·타임아웃 실패만 몇 번 물러서서 재시도하고, 그래도
# 안 되면 예외를 그대로 낸다 — 실패를 삼키지 않는다는 원칙은 그대로다.
@shared_task(
    name="core.run_scan",
    autoretry_for=(requests.ConnectionError, requests.Timeout),
    retry_backoff=2,
    retry_backoff_max=30,
    retry_jitter=True,
    max_retries=3,
)
def run_scan(name: str) -> dict:
    """등록부(`core.scans.SCAN_REGISTRY`)의 스캔 하나 — beat 스케줄이 스캔마다 이 태스크를
    이름과 함께 등록한다(#137). 등록부 밖의 이름은 엔드포인트가 404 로 거부한다."""

    from core.observability import tag_error_scope

    tag_error_scope("scan", scan=name)
    return call_internal(f"/api/internal/scans/{name}")

