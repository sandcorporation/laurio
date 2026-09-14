"""Celery beat 가 주기적으로 실행하는 태스크 (#137, #140, ADR-0003).

ADR-0003: 스캔 진입점은 내부 인증 HTTP 엔드포인트다 — 워커·수동 curl·Celery beat 모두 같은
하나의 HTTP 경로를 거치게 해서, "두 번 쏴도 한 번만 통과한다"는 보장을 지키는 코드 경로가 단
하나만 존재하게 한다. 스캔 태스크는 하나뿐이다 — 등록부(`core.scans.SCAN_REGISTRY`)의 스캔
이름을 받아 `/api/internal/scans/{name}` 에 POST 한다. beat 스케줄은 그 등록부에서 파생되므로
「엔드포인트는 있는데 아무도 부르지 않는」 스캔(#23 코디네이터 리뷰가 잡았던 사고)은 표현
자체가 불가능하다.

`call_internal`은 같은 모양(내부 인증 HTTP POST 한 번)을 쓰는 다른 앱의 즉시 실행 태스크도
재사용한다(#378, `classroom.tasks.score_attempt`) — 그래서 이름 앞의 밑줄을 뗐다.
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


@shared_task(name="core.run_scan")
def run_scan(name: str) -> dict:
    """등록부(`core.scans.SCAN_REGISTRY`)의 스캔 하나 — beat 스케줄이 스캔마다 이 태스크를
    이름과 함께 등록한다(#137). 등록부 밖의 이름은 엔드포인트가 404 로 거부한다."""

    return call_internal(f"/api/internal/scans/{name}")


@shared_task(name="core.backup_database", ignore_result=True)
def backup_database() -> dict:
    """매일 새벽 2시(서울) DB 를 오브젝트 스토리지로 백업한다 — `core.backups` 참고. 스캔과 달리
    내부 HTTP 를 거치지 않고 워커 안에서 직접 돈다(30초 타임아웃을 넘길 수 있는 작업이다)."""

    from core.backups import run_database_backup

    return run_database_backup()
