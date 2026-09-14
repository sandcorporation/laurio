"""Celery beat 설정 (티켓 02, ADR-0003, #23, #137).

브로커(Redis)는 공유 dev 인프라에 없으므로 "beat 가 주기적으로 스캔을 부른다"는 요건은 실제
실행 대신 코드 수준에서 확인한다 — 스케줄이 **스캔 등록부에서 파생**되고, 각 항목이 등록부의
스캔 이름으로 `core.run_scan` 을 부르며, 태스크가 내부 인증 엔드포인트를 거치는지.

#137 이전에는 엔드포인트 8 · task 7 · beat 7 을 세 곳에 손으로 나란히 적었고, 이 파일의 기대
목록도 손으로 관리됐다 — 그래서 lifecycle 스캔이 조용히 스케줄에서 빠진 채 배포됐다. 지금은
등록부가 유일한 원천이고 이 테스트는 그 파생이 깨지지 않았는지만 본다(#140 으로 열일곱 스캔이
전부 등록부에 올라 손으로 쓴 항목은 하나도 없다).
"""

import inspect

from config.celery import app as celery_app
from core import tasks as core_tasks
from core.scans import SCAN_REGISTRY


def test_every_registered_scan_has_a_beat_entry_that_calls_run_scan_with_its_name():
    schedule = celery_app.conf.beat_schedule
    assert SCAN_REGISTRY, "등록된 스캔이 하나도 없다"
    for name, spec in SCAN_REGISTRY.items():
        entry = schedule.get(f"scan:{name}")
        assert entry is not None, f"등록부의 스캔 {name!r} 이 beat 스케줄에 없다 — 파생이 깨졌다"
        assert entry["task"] == "core.run_scan"
        assert entry["args"] == [name]
        assert entry["schedule"] == spec.interval_seconds > 0


def test_beat_schedule_is_exactly_the_registry():
    """스케줄에 등록부 밖의 항목이 없다 — 손으로 쓴 항목은 하나도 없다."""

    assert set(celery_app.conf.beat_schedule) == {f"scan:{name}" for name in SCAN_REGISTRY}


def test_every_scan_that_used_to_have_its_own_endpoint_is_registered():
    """#137 이전에 앱마다 따로 있던 열일곱 스캔이 전부 등록부에 있다 — 이관 중 하나가 조용히
    빠지는 것이 #23 사고의 정확한 모양이다."""

    expected = {
        "scheduled-state-demo",
        "contest-close",
        "contest-judging-end",
        "handover-release",
        "identity-dormancy-purge",
        "retained-identity-purge",
        "deadline-reminder",
        "judging-end-reminder",
        "distribution-final-warning",
        "award-result-notice-recovery",
        "distribution-result-notice-recovery",
        "notification-dispatch-deferred",
        "notification-reclaim-stuck",
        "submission-scoring",
        "payment-refund-request",
        "payment-refund-reconcile",
        "distribution-create",
        "distribution-share-payout",
    }
    assert expected <= set(SCAN_REGISTRY), expected - set(SCAN_REGISTRY)


def test_run_scan_task_calls_the_scan_endpoint_with_the_internal_token():
    source = inspect.getsource(core_tasks.run_scan)
    assert "/api/internal/scans/" in source
    assert "call_internal" in source
    helper = inspect.getsource(core_tasks.call_internal)
    assert "X-Internal-Token" in helper
    assert "INTERNAL_API_TOKEN" in helper


def test_tick_is_not_scheduled_by_beat():
    """/tick 은 등록부 전부를 한 바퀴 도는 수동용이다 — beat 가 부르면 30초 타임아웃 안에 못 든다."""

    assert not any(e["task"] == "core.call_scheduler_tick" for e in celery_app.conf.beat_schedule.values())
    assert not hasattr(core_tasks, "call_scheduler_tick")
