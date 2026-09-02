"""Celery 앱 정의 + beat 스케줄.

브로커(Redis)는 staging/prod compose에 있다(docker/compose.staging.yaml,
docker/compose.prod.yaml, #23). 이 모듈은 임포트 시점에 브로커에 연결하지 않으므로,
브로커 없이도(dev·CI) 설정 자체는 임포트·검증할 수 있다.

코디네이터 리뷰 지적(#23): beat 스케줄에 core.call_scheduler_tick 하나만 있으면
"틱"만 주기적으로 돈다 — Distribution 1/N 배분, 환불 재확인, Handover Escrow 해제,
야간 지연 알림 발송, 채점 재시도는 각자 별도의 내부 스캔 엔드포인트라 별도로
등록해야 실제로 돈다(core/tasks.py의 각 태스크 docstring 참고). 전부 같은 60초
주기를 쓴다 — ADR-0003이 이미 "스캔 주기만큼 전이가 늦어지는 건 무해하다"고
규정했으므로, 엔드포인트마다 다른 주기를 골라야 할 이유가 없다.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("laurio")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

_SCAN_INTERVAL_SECONDS = 60.0

app.conf.beat_schedule = {
    "scheduler-tick": {
        "task": "core.call_scheduler_tick",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
    "distributions-run-due": {
        "task": "core.call_distributions_run_due",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
    "payments-run-refunds": {
        "task": "core.call_payments_run_refunds",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
    "handovers-release-due": {
        "task": "core.call_handovers_release_due",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
    "notifications-dispatch-due": {
        "task": "core.call_notifications_dispatch_due",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
    "scoring-run-pending": {
        "task": "core.call_scoring_run_pending",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
    "accounts-purge-expired-identities": {
        "task": "core.call_accounts_purge_expired_identities",
        "schedule": _SCAN_INTERVAL_SECONDS,
    },
}
