"""Celery beat 설정 (티켓 02, ADR-0003).

브로커(Redis)는 공유 dev 인프라에 아직 없고, 이 체인은 새 컨테이너/포트를 띄우지
않기로 되어 있다. 그래서 "Celery beat가 주기적으로 틱을 호출한다"는 요건은 브로커에
붙여 실제로 실행해보는 대신, beat 스케줄에 그 태스크가 등록되어 있고 태스크가 내부
인증 틱 엔드포인트를 부르도록 구성되어 있는지를 코드 수준에서 확인한다. 틱 자체의
동작(rowcount 1 일 때만 통과 등)은 test_scheduler_tick.py 가 HTTP로 이미 증명한다.
"""

import inspect

from config.celery import app as celery_app
from core.tasks import call_scheduler_tick


def test_beat_schedule_registers_scheduler_tick_periodically():
    schedule = celery_app.conf.beat_schedule

    assert "scheduler-tick" in schedule
    entry = schedule["scheduler-tick"]
    assert entry["task"] == "core.call_scheduler_tick"
    assert entry["schedule"] > 0


def test_scheduler_tick_task_calls_the_internal_tick_endpoint():
    source = inspect.getsource(call_scheduler_tick)

    assert "/api/internal/tick" in source
    assert "X-Internal-Token" in source
