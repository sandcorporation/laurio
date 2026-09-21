"""배포 compose 의 backend 가 쓰는 gunicorn 설정(2026-09-21).

지금 여기에는 하나뿐이다: **죽은 워커의 지표 파일을 정리한다.** `core/metrics.py` 가
워커마다 값을 `PROMETHEUS_MULTIPROC_DIR` 에 파일로 쓰고 긁을 때 합산하는데, 워커가
재시작되면(gunicorn 은 워커가 죽으면 새로 띄운다) 죽은 워커의 게이지 값이 남아 합산을
오염시킨다. prometheus_client 문서가 권하는 대로 `child_exit` 에서 표시한다.

바인드·워커 수는 compose 의 명령줄에 그대로 둔다 — 설정이 두 곳으로 갈리지 않게.
"""

import os


def child_exit(server, worker):
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
