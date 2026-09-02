"""Celery beat 가 주기적으로 실행하는 태스크.

ADR-0003: "스캔 진입점은 내부 인증 HTTP 엔드포인트다 — 워커·수동 curl·Celery beat
모두 같은 하나의 HTTP 경로를 거치게 해서, '두 번 쏴도 한 번만 통과한다'는 보장을
지키는 코드 경로가 단 하나만 존재하게 한다. 이 파일의 태스크는 전부 그 경로를
호출하는 얇은 어댑터일 뿐이며 비즈니스 로직을 담지 않는다(비즈니스 로직 테스트는
각 앱의 HTTP 테스트 — tests/test_scheduler_tick.py, tests/test_refunds.py 등 —
가 이미 내부 엔드포인트를 직접 두드려 검증한다).

코디네이터 리뷰 지적(#23): 이 파일이 core.call_scheduler_tick 하나만 가지고 있어서
"틱"만 Celery beat 태스크로 존재하고, distributions/payments/handovers/
notifications/scoring 각자의 내부 스캔 엔드포인트(config/api.py 참고 — 전부
`/api/internal/*` 아래, 전부 core.auth.InternalAuth로 보호된다)는 아무도 주기적으로
부르지 않았다. 그 결과 Distribution 1/N 배분, 환불 재확인, Handover Escrow 해제,
야간 지연 알림 발송, 채점 재시도가 실제 배포에서 전부 멈춘다 — Celery beat가 있어도
등록되지 않은 태스크는 당연히 안 돈다.

이 태스크들을 각 앱(distributions/, notifications/ 등) 안에 두지 않고 여기 core/에
모아 둔 이유: distributions/notifications/contests는 다른 체인이 동시에 편집 중이라
그 디렉터리 안에 파일을 새로 만들거나 수정하지 않는다는 제약이 있다. 이 태스크들은
비즈니스 로직이 전혀 없는 "URL에 POST 한 번"이라 어느 파일에 있어도 동작이 같고,
core/tasks.py가 이미 그 정확한 패턴(호출부만 있고 로직은 없는 얇은 어댑터)의
전례다.
"""

import requests
from celery import shared_task
from django.conf import settings


def _call_internal(path: str) -> dict:
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


@shared_task(name="core.call_scheduler_tick")
def call_scheduler_tick() -> dict:
    """core/api.py의 단일 전이 스캔 — 등록된 TRANSITION_REGISTRY 규칙 전부."""

    return _call_internal("/api/internal/tick")


@shared_task(name="core.call_distributions_run_due")
def call_distributions_run_due() -> dict:
    """distributions/api.py: 심사기간 종료 후 무응답 기간이 지난 Contest에 1/N 배분."""

    return _call_internal("/api/internal/distributions/run-due")


@shared_task(name="core.call_payments_run_refunds")
def call_payments_run_refunds() -> dict:
    """payments/api.py: PENDING/타임아웃으로 남은 환불을 재확인해 확정한다."""

    return _call_internal("/api/internal/payments/run-refunds")


@shared_task(name="core.call_handovers_release_due")
def call_handovers_release_due() -> dict:
    """handovers/api.py: Sponsor 무응답 기간이 지난 Handover의 Escrow를 해제한다."""

    return _call_internal("/api/internal/handovers/release-due")


@shared_task(name="core.call_notifications_dispatch_due")
def call_notifications_dispatch_due() -> dict:
    """notifications/api.py: 야간 연기 큐를 스캔해 발송 시각이 지난 알림을 보낸다."""

    return _call_internal("/api/internal/notifications/dispatch-due")


@shared_task(name="core.call_scoring_run_pending")
def call_scoring_run_pending() -> dict:
    """scoring/api.py: 채점 대기·재시도 대상 Submission을 스캔해 LLM 채점을 돌린다."""

    return _call_internal("/api/internal/scoring/run-pending")


@shared_task(name="core.call_accounts_purge_expired_identities")
def call_accounts_purge_expired_identities() -> dict:
    """accounts/internal_api.py: 2년 미이용 신원 파기 + 보존 기간 만료
    RetainedIdentity 파기(#102, ADR-0025)."""

    return _call_internal("/api/internal/accounts/purge-expired-identities")
