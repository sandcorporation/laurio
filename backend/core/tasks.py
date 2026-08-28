"""Celery beat 가 주기적으로 실행하는 태스크.

ADR-0003: "스캔 진입점은 내부 인증 HTTP 엔드포인트 하나이고 Celery beat가 이를
호출한다." 워커·수동 curl·Celery beat 모두 같은 하나의 HTTP 경로(`POST
/api/internal/tick`)를 거치게 해서, "두 번 쏴도 한 번만 통과한다"는 보장을 지키는
코드 경로가 단 하나만 존재하게 한다. 이 태스크 자체는 그 경로를 호출하는 얇은
어댑터일 뿐이며 비즈니스 로직을 담지 않는다(비즈니스 로직 테스트는 전부
`tests/test_scheduler_tick.py` 에서 HTTP로 `/api/internal/tick` 을 직접 두드려 검증한다).
"""

import requests
from celery import shared_task
from django.conf import settings


@shared_task(name="core.call_scheduler_tick")
def call_scheduler_tick() -> dict:
    response = requests.post(
        f"{settings.INTERNAL_API_BASE_URL}/api/internal/tick",
        headers={"X-Internal-Token": settings.INTERNAL_API_TOKEN},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
