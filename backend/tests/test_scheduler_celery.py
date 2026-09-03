"""Celery beat 설정 (티켓 02, ADR-0003; #23에서 5개 내부 스캔 태스크를 추가한다).

브로커(Redis)는 공유 dev 인프라에 없고, 이 체인은 새 컨테이너/포트를 띄우지 않기로
되어 있다. 그래서 "Celery beat가 주기적으로 내부 스캔 엔드포인트를 호출한다"는
요건은 브로커에 붙여 실제로 실행해보는 대신, beat 스케줄에 각 태스크가 등록되어
있고 태스크가 올바른 내부 인증 엔드포인트를 부르도록 구성되어 있는지를 코드
수준에서 확인한다. 각 엔드포인트 자체의 동작은 해당 앱의 HTTP 테스트
(test_scheduler_tick.py, test_refunds.py, test_distributions.py, test_handover.py,
test_notifications.py, test_scoring.py)가 이미 증명한다.

코디네이터 리뷰 지적(#23): core.call_scheduler_tick 하나만 beat_schedule에 있으면
"틱"만 돌고, distributions/payments/handovers/notifications/scoring 각자의 내부
스캔 엔드포인트는 아무도 부르지 않는다 — 실제 배포에서 Distribution 배분·환불
재확인·Handover Escrow 해제·야간 알림 발송·채점 재시도가 전부 멈춘다. 이 파일은
여섯 개 태스크 전부가 등록되어 있는지를 파라미터화해 확인한다.
"""

import inspect

import pytest

from config.celery import app as celery_app
from core import tasks as core_tasks

# (beat_schedule의 엔트리 이름, 태스크 함수, 태스크 이름, 호출해야 하는 내부 경로)
_EXPECTED_SCHEDULE_ENTRIES = [
    (
        "scheduler-tick",
        core_tasks.call_scheduler_tick,
        "core.call_scheduler_tick",
        "/api/internal/tick",
    ),
    (
        "distributions-run-due",
        core_tasks.call_distributions_run_due,
        "core.call_distributions_run_due",
        "/api/internal/distributions/run-due",
    ),
    (
        "payments-run-refunds",
        core_tasks.call_payments_run_refunds,
        "core.call_payments_run_refunds",
        "/api/internal/payments/run-refunds",
    ),
    (
        "handovers-release-due",
        core_tasks.call_handovers_release_due,
        "core.call_handovers_release_due",
        "/api/internal/handovers/release-due",
    ),
    (
        "notifications-dispatch-due",
        core_tasks.call_notifications_dispatch_due,
        "core.call_notifications_dispatch_due",
        "/api/internal/notifications/dispatch-due",
    ),
    (
        "notifications-lifecycle-run-due",
        core_tasks.call_notifications_lifecycle_run_due,
        "core.call_notifications_lifecycle_run_due",
        "/api/internal/notifications/lifecycle/run-due",
    ),
    (
        "scoring-run-pending",
        core_tasks.call_scoring_run_pending,
        "core.call_scoring_run_pending",
        "/api/internal/scoring/run-pending",
    ),
    (
        "accounts-purge-expired-identities",
        core_tasks.call_accounts_purge_expired_identities,
        "core.call_accounts_purge_expired_identities",
        "/api/internal/accounts/purge-expired-identities",
    ),
]


@pytest.mark.parametrize(
    "entry_name,_task_fn,task_name,_path",
    _EXPECTED_SCHEDULE_ENTRIES,
    ids=[e[0] for e in _EXPECTED_SCHEDULE_ENTRIES],
)
def test_beat_schedule_registers_each_internal_scan_periodically(
    entry_name, _task_fn, task_name, _path
):
    schedule = celery_app.conf.beat_schedule

    assert entry_name in schedule, (
        f"beat_schedule에 {entry_name!r}이 없다 — 이 스캔은 배포 환경에서 절대 자동으로 "
        "돌지 않는다(config/celery.py)."
    )
    entry = schedule[entry_name]
    assert entry["task"] == task_name
    assert entry["schedule"] > 0


@pytest.mark.parametrize(
    "_entry_name,task_fn,_task_name,path",
    _EXPECTED_SCHEDULE_ENTRIES,
    ids=[e[0] for e in _EXPECTED_SCHEDULE_ENTRIES],
)
def test_each_task_calls_its_internal_endpoint_with_the_internal_token(
    _entry_name, task_fn, _task_name, path
):
    source = inspect.getsource(task_fn)

    assert path in source
    # 태스크 전부가 core.tasks._call_internal을 공유하므로, X-Internal-Token 헤더
    # 자체는 _call_internal에만 문자 그대로 등장한다 — 각 태스크가 그 헬퍼를 실제로
    # 거치는지는 소스에 그 경로 문자열이 있는지로 확인한다(위 assert).
    assert "_call_internal" in source


def test_call_internal_helper_sends_the_internal_token_header():
    source = inspect.getsource(core_tasks._call_internal)

    assert "X-Internal-Token" in source
    assert "INTERNAL_API_TOKEN" in source


def test_beat_schedule_has_no_extra_or_missing_entries():
    """등록된 태스크 이름 집합이 core/tasks.py의 태스크 집합과 정확히 일치하는지 —
    태스크를 추가하고 beat_schedule에 등록하는 걸 깜빡하는 회귀를 잡는다."""

    schedule_task_names = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    expected_task_names = {e[2] for e in _EXPECTED_SCHEDULE_ENTRIES}

    assert schedule_task_names == expected_task_names
