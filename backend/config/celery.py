"""Celery 앱 정의 + beat 스케줄.

브로커(Redis 등)는 아직 dev compose 에 올라와 있지 않다(다른 티켓/체인 소관). 이
모듈은 임포트 시점에 브로커에 연결하지 않으므로, 브로커 없이도 설정 자체는 임포트·
검증할 수 있다. 실제로 워커·beat 를 띄우는 것은 이 티켓의 범위가 아니다 — "Celery
beat 가 주기적으로 틱을 호출한다"는 요건은 이 스케줄 설정으로 충족한다.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("laurio")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "scheduler-tick": {
        "task": "core.call_scheduler_tick",
        "schedule": 60.0,  # 초 단위. ADR-0003: 스캔 주기만큼 전이가 늦어지는 건 무해하다.
    },
}
