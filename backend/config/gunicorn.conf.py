"""배포 compose 의 backend 가 쓰는 gunicorn 설정(2026-09-21, 워커 종류는 #725).

prod·staging·PR CI 셋이 모두 `-c config/gunicorn.conf.py` 로 이 파일을 읽는다.
바인드·워커 수는 compose 의 명령줄에 둔다(곳마다 다르다 — prod·CI 4, staging 3).
워커가 **어떻게** 도는지는 여기 하나에 둔다 — 설정이 두 곳으로 갈리지 않게.

**gthread 워커(#725).** 예전 sync 워커는 연결 하나를 받으면 요청 머리가 올 때까지 그
연결에 묶여 다른 연결을 받지 못했다. BFF 의 undici 가 남긴 빈 연결 넷이면 워커 넷이 모두
묶여 그동안 아무도 응답을 못 받았다(prod 포함). gthread 는 연결을 스레드에 맡기고 주
루프는 계속 받으므로 빈 연결이 스레드 하나만 쥔다. gunicorn 26 은 새 연결이 데이터를
보내지 않으면 스레드를 최대 5초(코드 고정값) 쥐다가 풀어 폴러로 넘긴다 — 한 워커에
빈 연결이 `threads` 개 몰려야 그 워커가 받은 요청이 기다린다.

- `threads` — 스레드마다 Django DB 연결이 하나다(`CONN_MAX_AGE` 0 이라 요청이 끝나면
  닫는다). 워커 4 × 4 = 16 이 pgbouncer `max_client_conn` 200 안에 넉넉히 든다
  (셈은 `docs/ops/operations.md` 「요청 없는 연결이 워커를 묶는다」). 목적은 빈 연결이
  워커를 묶지 않는 것이지 처리량이 아니다.
- `timeout` — 기본값 30초를 적어 둔다. **gthread 에서는 뜻이 바뀐다**: sync 에서는 요청
  하나가 30초를 넘기면 워커를 죽였지만, gthread 의 주 루프는 요청과 상관없이 1초마다
  살아 있다고 알리므로 이 값은 주 루프가 멈춘 워커만 거둔다. 요청 안의 벤더 호출은
  제 타임아웃(20초)을 따로 든다.
- `keepalive` — sync 는 응답마다 연결을 닫았지만 gthread 는 연결을 살려 둔다. 서버가
  클라이언트보다 먼저 닫으면 클라이언트가 막 닫힌 연결에 요청을 실어 `other side closed`
  로 떨어진다. BFF 의 undici 는 쉬는 연결을 4초 뒤에 버리므로(Node 22 기본값) 서버는
  그보다 길게 둔다. 쉬는 연결은 스레드를 쥐지 않는다(폴러에 있다).
"""

import os

worker_class = "gthread"
threads = 4
timeout = 30
graceful_timeout = 30
keepalive = 5


def child_exit(server, worker):
    """죽은 워커의 지표 파일을 정리한다. `core/metrics.py` 가 워커마다 값을
    `PROMETHEUS_MULTIPROC_DIR` 에 파일로 쓰고 긁을 때 합산하는데, 워커가 재시작되면
    죽은 워커의 게이지 값이 남아 합산을 오염시킨다. prometheus_client 문서가 권하는
    대로 여기서 표시한다. 그 디렉터리가 없는 배포(staging)에서는 하는 일이 없다."""
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
