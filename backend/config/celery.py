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


def sync_beat_schedule() -> dict:
    """beat 스케줄은 **등록부에서 파생**된다(#137). `core.scans.register_scan` 이 스캔을 더할
    때마다 이 함수를 불러 스케줄을 다시 만든다 — 스케줄을 손으로 쓰는 자리가 없으므로
    「등록했는데 안 도는」 상태가 표현 불가능하다."""

    from core.scans import beat_schedule

    app.conf.beat_schedule = beat_schedule()
    return app.conf.beat_schedule


# 임포트 시점에는 비어 있다 — 이 모듈은 Django 앱 레지스트리가 준비되기 전(config 패키지
# 임포트)에 읽히므로 등록부를 여기서 건드릴 수 없다. 각 앱의 ready() 가 `register_scan` 으로
# 더할 때마다 위 함수가 스케줄을 다시 만든다 — beat 프로세스는 django.setup() 뒤에야 읽는다.
app.conf.beat_schedule = {}
