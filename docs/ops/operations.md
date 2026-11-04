# 운영 — admin 없음·백업·감시·로그·오류 수집·GlitchTip 자동 진단

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**Django admin 은 없다**(#46, ADR-0019). `/admin/` 은 마운트되지 않고 각 앱의
`admin.py` 도 없다.

사람이 판단하는 행위는 `/api/operator/*` 로만 한다. 그 API 에는 이제 화면이 있다
(`operator/`, #63) — 이의 심판·지급·정책·산출물 종류·카테고리(#231)·무료 공모전
개최 권한(#414, ADR-0048)·운영자 계정이 각각 한 화면씩이다. 화면이 없는 조작만
운영자가 HTTP 로 직접 친다.

데이터는 이렇게 훑는다:

```bash
cd backend && uv run python manage.py shell      # ORM 으로 조회
docker compose -f docker/compose.dev.yaml exec db psql -U codemit -d codemit
```

**서버 DB 백업은 앱이 하지 않는다 — `sandcorp-backup` 컨테이너가 한다**(2026-11-01, #857). 저장소
`sandcorporation/sandcorp-backup` 의 README 가 일정·보관 위치·**복원 절차**를 말한다(oracle 이 매일 04:30 에
`codemit-prod-db-1` 을 `pg_dumpall` 해 OCI restic 과 home `/data/backups/oracle` 두 곳에 둔다). 앱의
옛 백업(celery beat `core.backup_database`, `DB_BACKUP_*`, `DatabaseBackup`)은 걷었고, 비공개 버킷
`codemit-prod` 의 옛 `db-backups/` 객체는 지우지 않고 그대로 둔다(삭제는 대표가 따로 정한다). backend
이미지에 `postgresql-client-17` 도 더는 없다. **손으로 쓰는 beat 항목은 `config/celery.py` 의
`SCHEDULED_JOBS` 한 자리뿐이다.** 이와 별개로 **prod 배포는 적용할 마이그레이션이 있을 때 migrate 직전에
한 번 더 덤프한다** — oracle 의 배포 디렉터리 `.jenkins-prod-dumps/` 에 최근 3개(custom 형식, 600)를
둔다([배포](deploy.md), #839). 그 덤프의 복원은 이렇게 한다:

```bash
pg_restore --clean --if-exists --no-owner -h <host> -U codemit -d codemit <덤프 파일>
```

첫 Operator 는 관리 명령으로 만든다 — `createsuperuser` 는 쓰지 않는다(ADR-0018·0019):

```bash
cd backend && uv run python manage.py create_operator <아이디> --superuser
```

**살아 있는지는 oracle 의 Prometheus 가 본다**(2026-09-21). 그 전에는 **prod 가 죽어도
아무도 몰랐다** — GlitchTip 은 오류가 **도착해야** 아는 장치라 프로세스가 죽거나 디스크가
차서 응답을 못 하면 조용하다. 감시 스택은 **이 저장소 밖**이다: oracle 의
`/server/prometheus`(별도 compose — Prometheus 30일·Grafana·node-exporter·cadvisor, work 같은
다른 호스트도 같이 보는 공용 스택)에 사람이 손으로 둔다. Jenkins·GlitchTip 과 같은 취급이다.

- **무엇을 보나**: blackbox 프로브 3개(prod 의 공개 앱 `/contests`·강의실 `/login`·
  운영자 앱) — `/contests` 는 서버 렌더링이 백엔드를 불러야 200 이라 **백엔드·DB 생존까지**
  본다. 호스트 지표는 세 호스트(oracle·home·work)의 node-exporter, 컨테이너 재시작은 oracle
  의 cadvisor(**prod 만** — home 는 CI 러너와 배포가 컨테이너를 늘 만들고 지워 재시작이
  정상이다).
- **언제 울리나**(`prometheus/alerts.yml`, 12개): 응답 없음 2분 · home 호스트 다운 2분 ·
  루트 디스크 85%(경고)/95%(위험) · 가용 메모리 10% 미만 5분 · 스왑 90% 이상, 그리고 아래
  「LLM 채점」의 `codemit-llm` 그룹 6개. `codemit-containers` 그룹(컨테이너 재시작)은 지금 규칙이
  비어 있다. prod 는 `critical` 이다(예전에는 staging 이 `warning` 이었다).
- **어디로**: Alertmanager 가 **빌드 알림과 같은 Discord 채널**로 보낸다(채널을 늘리면 안
  보는 채널이 생긴다). 웹훅은 `alertmanager/discord_webhook`(chmod 600)에만 있고 설정
  파일에는 없다 — 바꾸려면 그 파일 한 줄을 고친다(재시작 불필요, 보낼 때마다 읽는다).
- **감시자가 prod 위에 있다는 사각지대**는 GlitchTip(home) 의 uptime 모니터가 교차로 본다 —
  oracle 이 통째로 죽으면 Prometheus 도 같이 죽기 때문이다. 반대로 home 가 죽으면 위
  `HostDown` 이 잡는다. 서로가 서로를 본다.
- **한 화면에서 본다** — Grafana 대시보드 **「Codemit prod」**(`/d/codemit-prod`, 저장소 밖
  `/server/prometheus/grafana/dashboards/codemit-prod.json` 을 프로비저닝이 30초마다 다시 읽는다).
  줄 다섯이다: 서비스 생존(프로브·지금 울리는 경보) · prod 백엔드 요청(초당·상태코드·지연
  p50/95/99·5xx 비율·경로별 상위) · 호스트 자원 · prod 컨테이너(메모리·재시작) · prod 로그(서비스별
  줄 수·오류·**요청 id 로 찾기** — GlitchTip 오류의 `request_id` 태그 값을 맨 위 입력칸에 넣는다).
  호스트 일반 지표는 원래 있던 node-exporter·cadvisor 대시보드가 맡으므로 여기에는 codemit 에만
  있는 것을 둔다. **오류 패널은 우리 서비스만 본다** — 처음에 「exception」으로 넓게 걸었더니
  OpenSearch 의 JVM 기동 인자(`-XX:+ShowCodeDetailsInExceptionMessages`)가 걸려, Django JSON 의
  ERROR 이상·파이썬 `Traceback`·Celery `: ERROR/` 로 좁혔다.
- **닿는지 확인하는 법**: Alertmanager 에 시험 경보를 넣는다(`POST /api/v2/alerts`, 3분 뒤
  해소 메시지가 한 번 더 온다). 2026-09-21 에 그렇게 확인했다 — 발송 1·실패 0.

**컨테이너 로그는 무제한으로 쌓이지 않는다**(2026-09-21). 도커 기본 json-file 은 크기
제한이 없어 home 에는 이 저장소 밖의 컨테이너 로그가 319M·106M 쌓여 있었다. 두 배포
compose 의 서비스 11개 전부에 `x-logging`(20MB × 5개)을 걸었다 — **다음 배포의 컨테이너
교체부터** 적용된다. 두 호스트의 `/etc/docker/daemon.json` 에도 같은 기본값을 써 두었지만
**데몬이 다시 떠야 읽힌다** — 두 호스트 모두 `live-restore` 가 꺼져 있어 데몬 재시작이 곧
전 컨테이너 재시작이라 일부러 하지 않았다(다음 재부팅·도커 업그레이드 때 적용된다).
**prod 로그는 배포해도 남는다 — 30일**(2026-09-21). 컨테이너를 바꿔 끼우면 그 로그
파일도 지워지므로, 예전에는 배포 한 번이 사후 진단을 끊었다. 지금은 oracle 의 같은 감시
스택에 **Loki**(30일, 메모리 상한 1GB)와 수집기 **Alloy**(도커 소켓으로 `codemit-prod-*`
컨테이너만 따라간다)가 있어, 로그가 나오는 대로 Loki 로 간다. Grafana 의 Loki 데이터소스에서
`{service="backend"}`·`{container="codemit-prod-events-1"}` 처럼 찾는다(라벨은 `container`·
`service`·`env`). home 는 CI 러너가 컨테이너를 늘 만들고 지워 모으지 않는다.

**배포 환경에서 Django 가 찍는 로그는 한 줄 JSON 이고, 요청마다 id 가 붙는다**(2026-09-21).
gunicorn 자신의 줄(워커 기동 등)과 Celery 자신의 줄은 각자 포맷 그대로다 — 그 둘은 Django 의
LOGGING 을 지나지 않는다.
`config/settings.py` 의 LOGGING 이 배포 여부(`IS_DEPLOYED_ENVIRONMENT`)로 포매터를 고른다 —
prod 는 `core.json_logging.JsonFormatter`(`time`·`level`·`logger`·`message`·
`request_id`, 예외는 같은 줄의 `exc`), dev 는 지금처럼 사람이 읽는 한 줄 포맷이다. Loki 에서는
`{service="backend"} | json | request_id="…"` 로 한 요청의 줄만 뽑는다.

- **요청 id 는 세 곳에 같은 값이다**(`core/request_id.py`): 그 요청 동안의 **모든 로그 레코드**
  (필터가 아니라 레코드 팩토리가 붙여 어느 핸들러로 가든 빠지지 않는다), **GlitchTip 태그**
  `request_id`, **응답 헤더** `X-Request-ID`. 그래서 GlitchTip 오류 하나에서 태그 값을 복사해
  Loki 로 그 요청의 앞뒤 로그를 찾는다. 앞단이 모양이 맞는 `X-Request-ID`(영숫자·`._-`, 64자
  이하)를 주면 그대로 잇고, 아니면 새로 만든다 — 모양만 막아 로그 주입을 끊는다.
- **id 는 요청이 완전히 끝날 때(`request_finished`) 지운다** — 미들웨어가 돌아올 때 지우면,
  Django 가 4xx·5xx 경고(`django.request` 의 「Not Found」 등)를 **체인이 끝난 뒤에** 찍기
  때문에 사후 진단에서 제일 먼저 찾는 그 줄이 id 없이 나간다(실제로 테스트가 그렇게 잡았다).

**요청 없는 연결이 워커를 묶는다 — backend 는 gthread 워커로 돈다**(2026-10-15, #725).
예전 sync 워커는 연결 하나를 받으면 요청 머리가 올 때까지 그 연결에 묶여 다른 연결을 받지
못했다. BFF 의 undici 가 남긴 빈 연결(#723, `docs/ops/ci.md`)이 워커 수만큼 쌓이면 그동안
아무도 응답을 못 받았다(prod 포함). 지금은 `config/gunicorn.conf.py` 가 `worker_class =
"gthread"`·`threads = 4` 를 두고 prod·PR CI 둘이 모두 그 파일을 `-c` 로 읽는다(워커
수만 compose 에 — 둘 다 4). 빈 연결은 스레드 하나만 쥐고 주 루프는 계속 받는다.
`tests/test_gunicorn_idle_connections.py` 가 실제 gunicorn 으로 빈 연결을 워커 수만큼 쥔 채 다음
요청이 1초 안에 오는 것을, `--worker-class sync` 로 덮으면 묶이는 것을 함께 본다.

- **남는 틈**: gunicorn 26 은 새 연결이 데이터를 보내지 않으면 스레드를 **5초**(코드 고정값)
  쥐다가 폴러로 넘긴다. 워커는 스레드가 다 차도 연결을 계속 받아 줄 세우므로, 한 워커에 빈
  연결이 4개 몰리면 그 워커가 받은 요청은 그만큼 기다린다.
- **`timeout = 30` 의 뜻이 바뀌었다**: sync 에서는 요청 하나가 30초를 넘기면 워커를 죽였지만,
  gthread 의 주 루프는 요청과 상관없이 1초마다 살아 있다고 알리므로 이제는 주 루프가 멈춘
  워커만 거둔다. 요청 안의 벤더 호출(공모전 채점·요구사항 대화·채점 모델 시험 호출)은 제
  타임아웃 20초를 따로 들고, `call_internal` 은 30초에 부른 쪽이 끊는다. 요청 안의 SQL 문은
  `core/db_timeouts.py` 가 `statement_timeout` 25초·`lock_timeout` 5초로 끊는다(#745 — 문마다
  `SET LOCAL` 을 함께 실어 트랜잭션 모드 풀러에서도 그 문에만 걸린다. celery 태스크 본체·관리
  명령·마이그레이션에는 걸리지 않지만, **요청으로 도는 내부 HTTP 스캔(`/api/internal/scans/*`)과
  e2e 시드에는 걸린다** — 스캔이 잠금을 5초 넘게 기다리면 500 이고 태스크는 재시도하지 않아 다음
  beat 로 밀린다. 그게 정상인 스캔은 지금 없다(#747). 값은
  `CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS`·`CODEMIT_REQUEST_LOCK_TIMEOUT_MS`).
  끊긴 요청은 500 이고 GlitchTip 에 `OperationalError: canceling statement due to statement
  timeout`(잠금이면 `… due to lock timeout`)으로 잡힌다. 10초를 넘긴 요청 수는
  `sum(rate(codemit_http_request_duration_seconds_count[5m])) - sum(rate(codemit_http_request_duration_seconds_bucket{le="10.0"}[5m]))`
  — 히스토그램은 끝난 요청만 세므로, 끝나지 않고 걸린 요청은 여기에 안 보인다.
- **`keepalive = 5`**: sync 는 응답마다 연결을 닫았지만 gthread 는 살려 둔다. 서버가 BFF 의
  undici(쉬는 연결을 4초 뒤 버린다, Node 22 기본값)보다 먼저 닫으면 막 닫힌 연결에 요청이 실려
  `other side closed` 로 떨어지므로 서버가 더 길게 둔다. 쉬는 연결은 스레드를 쥐지 않는다.
- **세 앱의 `/healthz` 는 전역 fetch 로 backend 를 치지 않는다**: 프로브가 3초에 끊기면 undici 가
  끊긴 연결 자리에 다음 요청용 연결을 곧바로 새로 맺어 두고 그 연결은 요청 없이 4초 열려 있다
  (Node 22·26 모두 실제 소켓으로 쟀다, `connection: close` 머리는 fetch 가 무시한다). backend 가
  느릴수록 빈 연결이 늘어 더 느려지는 되먹임이라, 프로브는 `@codemit/bff-shared` 의
  `probeBackendHealth`(`node:http`, 연결 풀 없음)로 친다 — 끝나거나 끊기면 그 연결을 닫는다.
- **DB 연결 셈**: 스레드마다 Django 연결이 하나고 `CONN_MAX_AGE` 가 0 이라 요청이 끝나면 닫는다.
  모두 트랜잭션 모드 pgbouncer 를 거친다.

  | 쓰는 쪽 | prod | 근거 |
  | --- | --- | --- |
  | backend(워커 × 스레드) | 4 × 4 = 16 | 예전 sync 는 4 |
  | celery-worker(prefork) | 2 | `--concurrency 2`(#859, 전에는 미지정 → 코어 수 4). beat 는 이 안에서 `-B` 로 돈다 |
  | grader DB 스레드 | 1 | |
  | events(ASGI) | 따로 세지 않았다 | 스트림을 여는 요청만 DB 를 쓴다 |
  | **풀러 클라이언트 상한** | `max_client_conn` 200 | `docker/pgbouncer/docker-entrypoint.sh` |
  | **풀러 → DB 서버 연결** | `default_pool_size` 20 | PostgreSQL `max_connections` 기본 100 안 |

  클라이언트 쪽 최악(모두 동시에)은 prod 약 22 로 200 에 한참 못 미친다. 서버 연결 20 은
  트랜잭션 동안만 쓰이므로(`ATOMIC_REQUESTS` 없음, 쿼리마다 자동 커밋) 동시에 DB 안에 있는
  스레드가 20을 넘을 때만 풀러가 줄 세운다 — 오류가 아니라 대기다.
- **스레드 안전성**(2026-10-15 판정): 요청 경로의 가변 상태는 모두 Redis(호출 상한
  `classroom/mcp.py` 의 `cache.add`+`incr`, 조회수 `contests/view_tracking.py`)·잠금이 있는
  LocMem(채점 모델 시험 호출의 통과 기록)·스레드 로컬(`core/events.py` 의 커밋 뒤 발행)·요청마다
  만드는 객체(요구사항 대화 어댑터, `safe_outbound` 의 `requests.Session`)에 있다. 지표는
  prometheus_client 가 값마다 잠그고 multiprocess 파일은 pid 단위라 같은 워커의 스레드가 함께
  쓴다. Sentry 사용자 표시는 SDK 의 요청별 격리 범위(contextvars)에 들어간다. 모듈 수준 가변
  전역은 테스트 전용 `FakeEventBus._queues`(배포는 Redis 버스) 하나다.

**prod 백엔드의 요청량·지연·상태코드는 `/metrics` 로 나간다**(2026-09-21, `core/metrics.py`).
**대시보드용**이다 — 경보는 걸지 않는다(5xx 는 GlitchTip 이 이미 울린다).

- **내부 이름으로 온 요청에만 답한다** — Host 가 `INTERNAL_SERVICE_HOSTS`(`backend`·`events`)가
  아니면 404(존재를 알려주지 않는다). 공개 프록시는 공개 도메인을 Host 로 넘기고, 세 앱의 BFF
  허용목록에 이 경로가 없고, 백엔드 포트는 호스트 127.0.0.1 에만 열려 있다 — 세 겹 중 이
  파일이 마지막 하나를 지킨다. 감시 스택은 compose 네트워크 안에서 `backend:8000` 으로 긁는다 —
  그래서 oracle 의 prometheus 컨테이너가 **prod 네트워크(`codemit-prod_default`)에도 붙어 있다**.
  그 동안에는 prod 에서 `docker compose down` 을 하면 그 네트워크를 지우지 못한다는 경고가 난다
  (배포는 `up -d` 만 써서 영향이 없다). 배포 직후 요청이 가장 많은 경로는 헤더 알림 벨의
  `api/notifications/unread-count` 폴링이었다(2026-09-21 실측) — 백엔드 부하를 볼 때 첫 자리다.
- **gunicorn 워커 넷을 합산한다**(워커 안의 스레드는 pid 가 같아 한 파일을 함께 쓴다) — prod compose 가 backend 에만 `PROMETHEUS_MULTIPROC_DIR`
  를 주고 뜰 때마다 비우며, 죽은 워커 정리는 `config/gunicorn.conf.py` 의 `child_exit` 가
  한다(워커가 각자 카운터를 들면 긁을 때마다 무작위 워커 하나의 값이 와서 튄다). 워커 넷에
  40번 보낸 뒤 긁으면 세 번 모두 같은 합계가 나오는 것을 실측으로 확인했다.
- **라벨은 URL 패턴이다, 실제 경로가 아니다** — `resolver_match.route`(`api/contests/
  <int:contest_id>` 꼴)로 세고 맞지 않은 요청은 `unmatched` 하나로 모은다. 실제 경로를 쓰면
  공모전 수만큼 시계열이 생긴다.

**LLM 채점 호출은 지표·호출별 로그·경보로 본다**(2026-10-14, #585, `core/llm_metrics.py`). 벤더로 나가는
왕복은 `OpenAIScoringAdapter.score`(동기)·`score_async`(grader) 두 곳뿐이고 공모전·강의실이 둘 다
거기를 지나므로 계측도 거기 하나다.

- **지표**(prod 에서 긁는다). 라벨은 닫힌 집합이다 — 제품 `classroom`·`contest`, 모델(호환 서버의 자유
  문자열 모델은 `custom` 하나로 접는다), 결과. **클래스·제출·강사 id 는 라벨에 없다**(시험이 못 박는다):
  - `codemit_llm_calls_total{product,model,result}` — 결과는 `ok`·`timeout`·`rate_limited`·
    `quota_exhausted`·`auth`·`server_error`·`other`. 새로 판정하지 않고 기존 예외 계층을 옮긴다(401·403→
    `auth`, 429 `insufficient_quota`→`quota_exhausted`, 그 밖의 429→`rate_limited`, 5xx→`server_error`,
    타임아웃→`timeout`). **호환 서버의 읽기 타임아웃은 `other` 로 센다**(안전한 바깥 호출이 `response_failed` 로
    접어 던진다) — OpenAI 직접 호출의 타임아웃은 `timeout`.
  - `codemit_llm_call_duration_seconds{product,model}` — 히스토그램, 버킷 0.5~240초(강의실 벤더 한도 180초).
  - `codemit_llm_tokens_total{product,model,direction}` — `input`·`output`(벤더 `usage`).
  - `codemit_llm_in_flight{product}` — 지금 벤더 응답을 기다리는 호출 수(게이지). grader 에서는 비동기
    동시성 그대로다(전역 상한 64).
  - `codemit_llm_queue_wait_seconds{product="classroom"}` — 「큐에 넣은 시각」(`scoring_queued_at`, 즉시 채점·
    스캔이 찍는다) → grader 가 임대를 집은 시각. 공모전에는 큐 시각이 없어 이 지표가 없다.
- **여러 프로세스는 어디서 합산하나 — 호출이 도는 곳이 둘이고 각자 한 번에 긁힌다.**
  ① 강의실 채점은 **grader 한 프로세스(asyncio)** 안이다 → `manage.py grader` 가 `CLASSROOM_GRADER_METRICS_PORT`
  (prod compose 9102, 호스트에 열지 않음)로 작은 `/metrics` 를 열고 프로세스 하나의 값을 그대로 낸다 — 합산할
  것이 없다. ② 공모전 채점은 Celery 가 아니라 **내부 API 를 부른 gunicorn 워커**(`scoring/api.py` 의 스캔
  엔드포인트)에서 돈다 → 위 `/metrics` 의 `PROMETHEUS_MULTIPROC_DIR` 합산이 그대로 태운다. 게이지는 `livesum`
  이라 죽은 워커의 값은 더하지 않는다. Celery 워커는 벤더를 부르지 않아 노출이 없다.
- **호출별 로그**(Loki): 호출마다 `codemit.llm` 로거가 한 줄 JSON 을 남긴다 — `product`·`class_id`·`problem_id`·
  `submission_id`(공모전은 `contest_id`)·`model`·`reasoning_effort`·`duration_seconds`·`input_tokens`·
  `output_tokens`·`total_tokens`·`result`·`error_class`·`error_status`·`error_type`·`error_code`.
  grader 의 줄은 `{service="grader"} | json | logger="codemit.llm"`, 공모전은 `{service="backend"}` 로 찾는다.
  `result != "ok"` 는 WARNING. 오류 `type`/`code` 는 벤더가 고정된 값만 쓰는 열거형이고 **프롬프트·소스·응답
  본문·키·벤더의 `error.message` 는 어떤 필드에도 없다**(시험이 비밀 문자열이 줄에 없음을 못 박는다).
  예) 크레딧 소진 429 를 가려내려면 `| json | result="quota_exhausted"`.

**대시보드·경보·긁기 대상은 저장소 밖(oracle `/server/prometheus`)에 2026-10-14 에 적용했다** — 아래가 들어간
그대로다. 바꾸기 전 파일은 같은 자리에 `*.bak-20261014-*` 로 남겼다. 대시보드는 「prod 백엔드 요청」과 「호스트 자원」
사이의 「LLM 채점」 줄이고, 경보는 `alerts.yml` 의 `codemit-llm` 그룹(6개)이다. 고칠 때는 이 절과 그 파일을 같이 고친다.
**같은 여섯 규칙을 #830 부터 codemit 이 직접 검사해 디스코드로 보낸다**(아래 「운영 경보」) — `alerts.yml` 의
그룹을 걷는 것은 저장소 밖 일이라 대장이 맡는다. 걷기 전까지는 두 곳에서 울릴 수 있다.

1. **긁기 대상**(`prometheus.yml`) — grader 는 prod 네트워크의 `grader:9102` 다(prometheus 컨테이너가 이미
   `codemit-prod_default` 에 붙어 있다). 백엔드 대상은 이미 있어 공모전 지표는 따로 할 일이 없다. grader 는
   배포 때마다 새 컨테이너가 되므로 서비스 이름(`grader`)으로 긁는다.

   ```yaml
     - job_name: codemit-grader
       metrics_path: /metrics
       static_configs:
         - targets: ["grader:9102"]
           labels: { env: prod, service: grader }
   ```

   배포한 뒤 한 번 `curl -s http://grader:9102/metrics | grep codemit_llm_` (prometheus 컨테이너 안에서)로 줄이
   나오는지 본다.
2. **「Codemit prod」 대시보드 패널**(「LLM 채점」 줄, 패널 PromQL):
   - 결과별 호출률(누적 막대): `sum by (product, result) (rate(codemit_llm_calls_total[5m]))`
   - 응답 시간 p50 / p95: `histogram_quantile(0.5|0.95, sum by (le, product) (rate(codemit_llm_call_duration_seconds_bucket[5m])))`
   - 토큰률: `sum by (product, direction) (rate(codemit_llm_tokens_total[5m]))`
   - 동시 채점: `sum by (product) (codemit_llm_in_flight)`
   - 큐 대기 p95: `histogram_quantile(0.95, sum by (le) (rate(codemit_llm_queue_wait_seconds_bucket[5m])))`
3. **경보 규칙**(`prometheus/alerts.yml` 의 `codemit-llm` 그룹, 기존 Discord 채널로). 임계값 근거:

   ```yaml
   - name: codemit-llm
     rules:
       - alert: LLMTimeoutRatioHigh
         expr: |
           sum(increase(codemit_llm_calls_total{result="timeout"}[15m]))
             / sum(increase(codemit_llm_calls_total[15m])) > 0.2
           and sum(increase(codemit_llm_calls_total[15m])) >= 10
         for: 5m
         labels: { severity: warning }
         annotations: { summary: "LLM 채점 호출의 20% 이상이 타임아웃 (15분)" }
       - alert: LLMQuotaExhausted
         expr: sum(increase(codemit_llm_calls_total{result="quota_exhausted"}[10m])) > 0
         labels: { severity: warning }
         annotations: { summary: "채점 키의 크레딧이 소진된 호출이 있다 — 강사가 충전해야 풀린다" }
       - alert: LLMRateLimited
         expr: sum(increase(codemit_llm_calls_total{result="rate_limited"}[10m])) >= 5
         labels: { severity: warning }
         annotations: { summary: "벤더 빈도 제한 429 가 10분에 5건 이상" }
       - alert: LLMAuthRejected
         expr: sum(increase(codemit_llm_calls_total{result="auth"}[30m])) > 0
         labels: { severity: info }
         annotations: { summary: "채점 키 거부(401·403) — 해당 강사의 키 상태가 거부됨으로 옮겨졌다" }
       - alert: ClassroomScoringQueueSlow
         expr: |
           histogram_quantile(0.95, sum by (le) (rate(codemit_llm_queue_wait_seconds_bucket[10m]))) > 300
           and sum(rate(codemit_llm_queue_wait_seconds_count[10m])) > 0
         for: 10m
         labels: { severity: warning }
         annotations: { summary: "강의실 채점 큐 대기 p95 가 5분을 넘는다 (10분 지속)" }
       - alert: GraderMetricsDown
         expr: up{job="codemit-grader"} == 0
         for: 3m
         labels: { severity: warning }
         annotations: { summary: "grader 지표를 못 긁는다 — grader 가 죽었으면 강의실 채점이 멈춘다" }
   ```

   **임계값 근거.** 타임아웃은 한 건이 180초라 몇 건만 겹쳐도 비율이 튀므로 표본 10건 이상일 때만, 15분
   창에서 20% 와 5분 지속을 둔다(#581 의 타임아웃 몰림이 이 모양이었다). 크레딧 소진은 **한 건도 정상이
   아니다** — 그 클래스는 확인 간격(`QUOTA_RECHECK_INTERVAL`)마다 한 건씩만 다시 쳐서 경보가 반복돼도 시끄럽지
   않다. 빈도 제한은 `RATE_LIMIT_UNCOUNTED_ATTEMPTS`(60)번까지 실패에 세지 않아 조용히 쌓이므로 10분 5건에서
   먼저 본다. 큐 대기는 정상일 때 grader 폴링 간격(0.5초)과 동시성(64) 안쪽이라 초 단위이고, 벤더 한도가
   180초이므로 p95 300초는 「한 바퀴 이상 밀렸다」는 뜻이다. 모두 시작값이다 — 첫 일주일 값을 보고 조인다.

**같은 LLM 채점 지표가 1분 집계로 DB 에도 쌓여 운영자 콘솔 `/ops` 에 보인다**(2026-10-30, #827, 앱
`ops_metrics`). oracle 의 prometheus·grafana 스택을 콘솔로 옮기는 첫 단계라, 전환 기간에는 위 prometheus
계측을 **지우지 않고 나란히** 둔다.

- **기록.** 호출이 끝날 때(`llm_metrics._Call.finish` 뒤)와 grader 가 큐 대기를 잴 때, 그 분(UTC 분 시작
  epoch 초)의 Redis 해시 `ops:<종류>:<분>` 에 한 번의 왕복(Lua 하나)으로 더한다 — 동기 경로는 redis-py,
  grader 는 `redis.asyncio`. 종류는 `llm`(필드 `<product>|<model>|<result>|<n·ms·in·out·b<i>>`)과
  `llmq`(`<product>|<n·ms·b<i>·max_inflight>`)다. 라벨은 위와 같은 닫힌 집합이고 히스토그램 경계도 같은
  상수다. Redis 는 기존 인스턴스의 **DB 3**(`OPS_METRICS_REDIS_URL`, compose 가 준다), 키 TTL 은 사흘
  (`OPS_METRICS_KEY_TTL_SECONDS`). **Redis 가 실패해도 채점은 막히지 않는다** — 그 기록을 버리고 실패가
  이어지는 동안 `codemit.ops_metrics` 경고를 한 번 남긴다. 소켓 한도는 0.25초다.
- **옮기기.** celery beat 가 매분 `ops_metrics.flush_minutes` 를 돌려 **닫힌 분**(지금 분보다 앞선 분)의
  해시를 `LlmMinute`·`LlmQueueMinute` 행으로 옮긴다. 해시를 읽고 지우는 것이 원자적(`MULTI` 안의
  `HGETALL`+`DEL`)이라 두 번 돌아도 두 배가 되지 않고, DB 에는 더하므로 분이 닫힌 뒤 늦게 닿은 기록도 같은
  행에 합쳐진다. DB 쓰기가 실패하면 읽은 값을 해시에 되돌린다.
- **보관.** 매일 03:40(서울) `ops_metrics.purge_old_minutes` 가 90일(`OPS_METRICS_RETENTION_DAYS`)보다 오래된
  행을 지운다.
- **grader 생존 신호.** grader 가 30초마다 `ops:heartbeat:grader` 에 epoch 초를 쓴다(TTL 10분). 같은 때에
  지금의 동시 채점 수를 그 분의 최댓값 후보로 남긴다.
- **읽기.** `GET /api/operator/ops-metrics?range=1h|24h|7d`(운영자 전원) 가 결과별 호출 수·지연 p50/p95·토큰·
  큐 대기 p95·동시 채점 최댓값을 합계와 시간대 버킷(1분·15분·1시간)으로 낸다. 분위수는 버킷에서 prometheus
  `histogram_quantile` 과 같은 선형 보간으로 계산한다. 지금 분은 아직 옮기지 않아 기간의 끝은 지금 분의 시작이다.
- **요청 지표(#828).** `core.metrics.MetricsMiddleware` 가 prometheus 와 나란히 요청마다 메서드 · URL 패턴
  (`resolver_match.route`, 맞는 것이 없으면 `unmatched`) · 상태코드별 수와 지연 칸(prometheus 와 같은 경계)을
  `ops:req:<분>` 에 더한다. `/metrics` 는 세지 않는다. **요청 경로에는 Redis 왕복이 없다** — 프로세스 안 버퍼에
  더하고(미들웨어가 더하는 시간 약 2µs), 배경 스레드가 5초(`OPS_METRICS_REQUEST_FLUSH_SECONDS`)마다 분 하나에 Lua
  한 번으로 보낸다. 요청마다 보내면 왕복이 116~300µs 이고 Redis 가 패킷을 삼키면 0.25초가 요청마다 붙어서다.
  워커가 정상으로 내려가면 gunicorn `worker_exit` 훅이 남은 버퍼를 보내고, SIGKILL·OOM 이면 마지막 5초 이하를
  잃는다. 보내기가 실패하면 그 묶음을 버린다. 옮긴 행은 `RequestMinute`, API 의 `requests` 영역이 초당 요청·
  상태코드별 수·5xx 비율·지연 p50/p95 를 합계와 버킷으로, 경로별 상위 10(수와 p95)을 합계로 낸다 — DB 가
  `date_bin` 으로 접어 기간이 길어도 쿼리 둘이다.
- **운영 경보(#830, `ops_metrics.alerts`).** celery beat 가 매분 `ops_metrics.check_alerts` 를 돌린다(밀려 55초를
  넘긴 것은 버린다). 규칙과 「지속」(연속으로 참인 검사 수):

  | 규칙 | 조건 | 지속 |
  | --- | --- | --- |
  | `LLMTimeoutRatioHigh` | 15분 timeout ÷ 전체 > 20%(호출이 있을 때) | 5회 |
  | `LLMQuotaExhausted` | 10분 `quota_exhausted` > 0 | 1회 |
  | `LLMRateLimited` | 10분 `rate_limited` ≥ 5 | 1회 |
  | `LLMAuthRejected` | 30분 `auth` > 0 | 1회 |
  | `ClassroomScoringQueueSlow` | 10분 강의실 큐 대기 p95 > 300초(대기가 있을 때) | 10회 |
  | `GraderDown` | grader 생존 신호가 180초 넘게 없음(키가 없어도) | 1회 |

  **입력은 DB 집계 행 + 아직 옮기지 않은 Redis 분 해시다.** 「N분」 창은 지금 분(쓰는 중)과 그 앞의 N−1 개
  닫힌 분이다 — 지금 분을 넣어야 `> 0` 규칙이 첫 거부가 난 그 분에 울리고(flush 를 기다리면 1분 늦다),
  N−1 개만 더해야 부분인 지금 분과 합쳐 N분을 넘지 않는다. 분마다 DB 행과 Redis 해시를 **둘 다** 더해 flush
  가 아직 못 옮긴 분과 이미 옮긴 분에 늦게 닿은 기록을 함께 센다(`take` 가 원자적이라 두 번 세지 않는다).
  Redis 를 읽지 못하면 DB 만 본다(경고 로그). 상태는 규칙마다 `AlertState` 한 행(상태 firing/resolved ·
  연속 참 횟수 · 시작 · 마지막 확인 · 해소 · 값 · 기준 · 아직 못 보낸 알림)이다. 울리기 시작할 때
  `🔥 [Codemit] <규칙> 발생 — 값 · 기준 · <CODEMIT_OPERATOR_ORIGIN>/ops`, 해소될 때 `✅ [Codemit] <규칙> 해소 —
  <지속 시간> 지속` 을 **한 번씩** 보낸다 — 이미 울리는 규칙은 다시 보내지 않는다. 전송이 실패하면 경고 로그를
  남기고 다음 검사가 다시 보낸다. 「발생」이 닿기 전에 해소되면 둘 다 버린다. 웹훅(`OPS_ALERT_DISCORD_WEBHOOK_URL`)이
  비면 보내지 않고 상태만 기록한다. 겹쳐 돈 검사는 advisory 잠금을 못 잡아 건너뛴다. 지금 울리는 목록은 같은
  `GET /api/operator/ops-metrics` 의 `alerts`(기간과 무관)로 콘솔 `/ops` 맨 위 패널에 보인다.

**로그 소음 둘을 걷었다**(2026-09-21, Loki 로 처음 보였다). pgbouncer 가 트랜잭션 모드에서
연결·끊김마다 한 줄씩 **시간당 492줄**(prod 전체의 절반 가까이)을 찍어 `log_connections`·
`log_disconnections` 를 껐다(분당 stats 줄은 남긴다). 그리고 모을 정적 파일이 없어 `STATIC_ROOT`
가 만들어지지 않자 WhiteNoise 가 프로세스마다 `No directory at` 경고를 찍어, settings 가 빈
디렉터리를 만든다.

**오류는 자체 GlitchTip 으로 모인다**(2026-09-16). 예전에는 백엔드 로그가 컨테이너
stdout 에만 남고 세 앱에는 오류를 받을 자리조차 없어(`error.tsx` 도 없었다), 배포된
5xx 가 아무도 모르는 채로 며칠 났다. 지금은 Sentry SDK 로 보내는데 받는 쪽이
sentry.io 가 아니라 **우리가 띄운 GlitchTip**
(`https://glitchtip.honeycombpizza.link`, 저장소 밖에서 사람이 띄웠다)이다 — 수업
제출물·이름·이메일을 다루는 서버라 오류 본문이 바깥 업체로 나가지 않는 편이 낫다.
프로젝트는 **앱마다 하나**(backend·frontend·operator·classroom)고 DSN 도 그만큼 있다.

- **DSN 이 없으면 꺼진 채로 돈다** — dev·CI 는 주지 않는다. 그래서 테스트가 네트워크를
  치지 않고, 잊고 배포해도 부팅은 막히지 않는다(오류 수집이 없어도 서비스는 돌아야
  한다). `SENTRY_DSN_BACKEND`·`SENTRY_DSN_FRONTEND`·`SENTRY_DSN_OPERATOR`·
  `SENTRY_DSN_CLASSROOM` 을 `.env.prod` 가 채운다(`docker/prod.env.example` 에
  자리가 있다). 세 앱은 compose 가 그 줄을 실행 env `CODEMIT_PUBLIC_SENTRY_DSN` 으로 넣고,
  서버 초기화는 그것을 읽고 브라우저는 루트 레이아웃이 넘긴 같은 값을 쓴다(#711,
  `<앱>/lib/public-config.ts`) — 한 줄이라 브라우저와 서버가 갈리지 않고, 바꾸면 배포가
  컨테이너를 다시 띄우는 것으로 끝난다(이미지를 다시 굽지 않는다). 다시 띄울지는 `deploy.sh plan` 이
  떠 있는 컨테이너의 설정 해시와 견줘 정하고, 견주지 못하면 그 이유를 로그에 남기고 다시 띄운다(#727).
- **첫 요청에서 루트 레이아웃이 죽으면 브라우저 쪽은 보내지 않는다**(#727). `app/global-error.tsx` 는
  클라이언트 컴포넌트라 공개 설정을 실을 수 없어 브라우저 Sentry 가 DSN 없이 꺼져 있다 — 그 오류는
  서버 `onRequestError` 가 올리므로 잃는 것은 브라우저 쪽 사본뿐이다.
- **백엔드 이미지 하나로 도는 다섯 프로세스 전부가 켜진다** — `settings.py` 가 부르는
  `core.observability.configure_sentry()` 한 줄이라 gunicorn·events(ASGI)·celery
  worker·beat·관리 명령이 모두 같은 설정을 받는다.
- **보내지 않는 것**: 세션 리플레이와 성능 추적을 켜지 않았다(GlitchTip 은 리플레이를
  아예 받지 못하고, 리플레이는 화면을 통째로 녹화해 개인정보가 함께 나간다). 사용자
  식별은 **내부 id 하나**뿐이고(`accounts.middleware`·`core.operator_auth` 가 붙인다)
  이메일·IP·요청 본문·쿠키는 보내지 않는다. **세 앱에서는 그 약속을 `sendDefaultPii:
  false` 가 지키지 못했다**(#460, 2026-09-18) — 서버 쪽 `onRequestError` 경로로 올라온
  이벤트에는 요청이 그대로 붙어 `codemit_access`·`codemit_refresh` JWT 가 **평문으로**
  나갔다(refresh 수명 14일이라 그 값 하나로 로그인이 된다). 지금은
  `lib/observability/sentry-options.ts` 의 `beforeSend`(`scrubSensitiveRequestData`)가
  쿠키·요청 본문을 통째로 지우고, **헤더는 차단 목록**이다 — `CREDENTIAL_HEADERS`
  (`cookie`·`set-cookie`·`authorization`·`proxy-authorization`·`x-internal-token`·
  `x-operator-origin`, 대소문자 무시)만 지우고 나머지 헤더는 그대로 보낸다. 백엔드
  `core.observability._CREDENTIAL_HEADERS` 와 같은 목록이다. **차단 목록이라 자격증명을
  싣는 헤더를 새로 만들면 두 자리(세 앱의 사본과 백엔드)에 함께 더해야 한다** — 빠뜨리면
  그 값이 GlitchTip 에 평문으로 실린다. 세 앱의 여섯 진입점이 전부
  `buildSentryOptions` 를 지나므로 그 한 자리가 서버·브라우저 양쪽을 덮고, 두 앱의
  `sentry-options.test.ts` 가 그 동작을 고정한다(운영자 앱은 테스트 파일이 없다).
  **백엔드는 스택 프레임의 지역 변수를 보내지 않는다**(#590, 2026-10-06) — Python SDK 의
  기본값은 프레임마다 지역 변수를 싣는데, 그 길로 강사 OpenAI 키(채점 경로의 `raw_key`·
  `headers`), `X-Internal-Token`(`call_internal`), 이용자 로그인 토큰(요청 객체)이 평문으로
  나갔다(GlitchTip 오류 67~91, 사람이 지웠다). 이름 목록으로 골라 지우지 않고
  `include_local_variables=False` 로 통째로 끄며, `core.observability.before_send` 가
  쿠키·요청 본문·인증 헤더(`Authorization`·`X-Internal-Token` 등, SDK 기본 필터는
  `X-Internal-Token` 을 모른다)와 프레임 변수를 보내기 직전에 한 번 더 지운다.
  잃은 진단 정보는 채점·스캔·제출 진입점이 **식별자만**(클래스·문제·제출 번호, 채점
  모델, 스캔 이름) 태그·컨텍스트로 메운다(`tag_error_scope`) — 그리고 `request_id` 태그로
  Loki 로그를 찾는다. `backend/tests/test_observability_secrets.py` 가 운영과 같은 설정에
  전송만 흉내 내 「보내질 이벤트에 키·토큰이 없다」를 고정한다. 세 앱의 Node SDK 는
  지역 변수를 기본으로 싣지 않는다(`includeLocalVariables` 기본 꺼짐). **의도한 4xx 도 보내지 않는다** — 422·404·
  403 은 우리가 일부러 내는 응답이라, 그걸 다 보내면 진짜 5xx 가 소음에 묻힌다
  (`core.observability.drop_expected_error`, `backend/tests/test_observability.py` 가
  그 규칙을 고정한다). **남의 코드가 던진 것도 보내지 않는다**(#471, 2026-09-20) —
  브라우저 확장의 콘텐츠 스크립트가 던진 예외를 전역 핸들러가 잡아 강의실 프로젝트로
  보냈고, 하루 만에 prod 미해결 목록이 그 예외 하나로 통째로 찼다(GlitchTip 오류
  62·63, 합쳐 14건). 그 프레임은 `app:///` 로 시작하지만 `/_next/` 아래가 아니다 —
  `app:///` 는 SDK 가 오리진을 떼어낸 흔적이지 우리 번들이라는 뜻이 아니다
  (`chrome-extension://<id>/…` 도 같은 모양이 된다). 지금은 `beforeSend` 가
  **스택이 전부 `/_next/` 밖인 브라우저 이벤트**를 버린다 — 스택이 아예 없거나
  이름 없는 프레임이 섞인 것은 **남긴다**(교차 오리진의 `Script error.` 를 잃지
  않으려고 좁게 막았다). 서버 이벤트는 이 판정을 받지 않는다: 그 프레임은
  `.next/server`·`node_modules` 라 함께 보면 우리 서버 오류가 통째로 버려진다 —
  그래서 여섯 진입점이 `buildSentryOptions` 에 자기가 어느 쪽인지(`"browser"`·
  `"server"`)를 적는다.
- **어느 커밋에서 났는지가 release 태그다** — `deploy.sh` 가 배포하는 커밋 SHA 를
  `SENTRY_RELEASE` 로 내보내고, compose 가 백엔드 환경변수와 세 앱의 `CODEMIT_PUBLIC_SENTRY_RELEASE`
  로 넘긴다(#711 — 앱의 release 도 이제 실행 env 다). 그래서 위 「최신 이벤트의 release 가 수정을
  포함하는가」 판정이 배포 커밋으로 선다. #707 이 이미지에 「빌드 문맥을 마지막으로 바꾼 커밋」을
  굽던 임시 결정은 거뒀다 — release 가 빌드 인자가 아니니 문맥 해시와 엮이지 않는다. 코드가 안 바뀐
  앱은 `deploy.sh` 가 다시 띄우지 않으므로 그 앱의 release 는 그 앱을 마지막으로 띄운 배포 커밋이다.
  소스맵은 올리지 않는다(프론트 스택은 압축된 이름으로 보인다).
- **닿는지 확인하는 법**: 설정이 틀려도 조용히 아무 일도 안 일어나는 것이 오류 수집의
  기본 실패 모양이라, 배포 뒤 한 번 쏴 보고 GlitchTip 에서 눈으로 본다.

```bash
# home 안에서 ssh oracle
ssh oracle 'docker exec codemit-prod-backend-1 python manage.py sentry_smoke'
```

**모델 단가 표 대조 알림은 GlitchTip 경고로 간다**(2026-10-28, #798). 매일 04:10(서울) beat 가
`classroom.check_price_drift` 를 돌려 `classroom/scoring_cost.py` 의 `PRICES` 를 LiteLLM 단가 파일과
견주고, (a) 최근 7일 채점에 쓰였는데 표에 없는 모델 (b) 상대 차이 1% 초과 (c) 파일을 못 받음·형식 바뀜이면
`PriceDriftAlert` 경고 하나를 보낸다(지문 `["price-drift", 종류]`, 태그 `alert=price-drift` — 같은 종류는 이슈
하나로 묶인다). 다 맞으면 로그 한 줄뿐이다. 오류 수집기가 꺼진 dev·CI 에서는 바깥에 나가지 않는다. **표는
자동으로 고치지 않는다** — 사람이 공식 가격 페이지를 보고 고친다. 자동 진단은 예외 이름으로 이것을 거른다.

**그 오류를 에이전트가 집어 진단한다**(2026-09-18). Orca automation 「GlitchTip prod 오류
진단」이 매분 `scripts/glitchtip_pick.py` 를 precheck 로 돌려 **prod 의 미해결·미클레임
오류 하나**를 고르고(프로젝트 slug 가 `codemit-` 인 것만 — 같은 GlitchTip 조직에 2026-10-16 부터
`daypage`·`daypage-frontend` 도 있어 한때 남의 오류로 세션이 떴다, `GLITCHTIP_PROJECT_PREFIX`), 집힌 것이 있을 때만 이 머신에 세션을 띄운다(워크트리는 실행마다
새로, `origin/main` 기준). 세션이 따르는 절차는 `.claude/skills/glitchtip-triage/` 다 —
재현 루프를 먼저 만들고, **재현되지 않으면 고치지 않고 멈춘다**.

- **고르는 쪽과 판단하는 쪽을 가른다.** 이슈 제목·스택트레이스는 공개 DSN 으로 누구나
  넣을 수 있는 값이다. 무엇을 집을지와 GlitchTip 쓰기는 스크립트가 끝내고, 세션에는
  읽기 전용 토큰(`GLITCHTIP_TOKEN`)만 준다 — 인젝션된 텍스트가 이슈 상태를 바꾸거나
  코멘트를 남길 길이 없다. 쓰기 토큰은 `GLITCHTIP_TOKEN_FOR_AUTOMATION`(스코프
  `event:write` 하나, 루트 `.env`)이고 `project:read` 를 **일부러 안 줬다**.
- **다만 읽기 토큰은 한 자리를 흘린다.** `list_alerts`(REST 로는
  `/projects/{org}/{project}/alerts/`)가 **Discord 웹훅 URL 을 평문으로 돌려준다** —
  읽기 토큰으로는 열리고 쓰기 토큰으로는 403 이다(둘 다 실측, 2026-09-18). 스코프를 더
  가른 토큰을 만들지 않고, 스킬의 「하지 않는 것」이 그 경로를 명시적으로 금지하는 쪽을
  골랐다(세션이 쓰는 경로는 `issues/{id}` 아래 셋뿐이다). 토큰을 더 쪼개려면 `event:read`
  만 가진 세 번째 토큰을 GlitchTip 화면에서 만들어 `GLITCHTIP_TOKEN` 을 그것으로 바꾼다.
- **읽기 토큰은 `~/.claude/settings.json` 의 `env` 에 있다**(저장소 밖, chmod 600) — 그래야
  automation 이 띄우는 세션에도 붙는다. 셸 프로필에 두면 비대화형 셸에서 안 읽힌다.
  `.mcp.json` 은 그 값을 `${GLITCHTIP_TOKEN}` 으로 **참조만** 한다(GlitchTip 6.2.6 의 내장
  MCP, 도구 17개) — 그래서 그 파일은 커밋돼도 비밀이 없다. MCP 가 안 붙어도 세션은 같은
  일을 curl 로 한다.
- **「손 댔다」는 GlitchTip 코멘트다.** 이슈 목록 응답의 `numComments` 가 그 값이라 목록
  API 한 번으로 갈리고, 사람이 같은 사실을 GlitchTip 화면에서 본다. 새 상태 상자를 만들지
  않았다. **판정은 내용이 아니라 개수다** — 쓰기 토큰으로는 코멘트를 달 수만 있고 읽을
  수 없다(`GET issues/{id}/comments/` 가 `Permission denied`, 실측). **그런데 이슈를
  지울 수는 있다** — `DELETE issues/{id}/` 가 이 토큰으로 204 였다(2026-10-06, #590 에서
  비밀이 실린 이슈 11개를 지울 때 실측). 스코프는 `event:write` 하나뿐인데도 그렇다 —
  코멘트를 달려면 그 스코프가 있어야 하므로 「코멘트만 쓰는」 토큰은 없다. 그래서 토큰을
  그대로 두고, 그 토큰을 쥐는 것이 세션이 아니라 스크립트 둘(`glitchtip_pick.py` 는
  코멘트, `glitchtip_resolve.py` 는 해결 표시와 코멘트 — 둘 다 지우는 호출이 없다)이라는
  데 기댄다 — 세션에는 여전히 읽기 토큰만 준다. 루트 `.env` 의 이 값은
  이슈를 지울 수 있는 값으로 다룬다. 그래서 **코멘트가
  하나라도 있으면 집지 않는다**: 사람이 메모를 달아 둔 오류를 자동화가 가져가지 않는 것이
  오히려 맞다. 대가는 무심코 단 코멘트가 그 오류를 영구히 빼는 것이고, 되돌리려면 사람이
  화면에서 지워야 한다(`event:admin` 이 필요하고 이 토큰에는 일부러 없다 — 실제로 한 번
  그렇게 막혔다).
- **예외 하나 — 고친 코드에서 재발한 것은 다시 집는다**(2026-09-22). 위 규칙은 재발을
  생각하지 않고 정했다: 자동 진단이 고치고 CI 가 닫은 오류가 고친 코드에서 또 나면
  GlitchTip 이 스스로 미해결로 되살리는데, 클레임 코멘트가 남아 **자동화가 영영 다시 보지
  않았다**(오류 64). 지금은 main 에 그 오류의 `GlitchTip:` 수정 커밋이 있고 **최신
  이벤트의 release 가 그 최신 수정을 포함하면** 재발로 보고 다시 집는다 — 포함하지 않으면
  수정이 배포되기 전의 옛 코드에서 난 것이라 재발이 아니다(그걸 재발로 보면 배포 대기
  5~10분 사이에 이미 고친 오류를 또 집는다). 수정 커밋이 없으면(사람의 메모·사람에게
  넘긴 것) 원래 규칙대로 건너뛴다. 같은 재발을 매분 또 집지 않도록 「이 발생 시각에서
  이미 다시 집었다」를 `~/.codemit/glitchtip-regressions.json` 에 적는다 — 새 이벤트가
  오면 시각이 바뀌어 또 집힌다. **재발한 그 이벤트가 production 이어야 한다** — 이슈의
  환경 집합은 「prod 에서 난 적이 있는가」라, 처음 판은 (그때 있던) staging 배포 창의 이벤트를 prod
  재발로 집었다(오류 74, 2026-09-22). 세션은 클레임 파일의 `regression_of`(지난 수정 커밋)를
  받아 **처음부터가 아니라 그 수정이 무엇을 놓쳤는지부터** 본다.
- **동시 하나는 잠금 파일이 지킨다**(`~/.codemit/glitchtip-lock`). 세션이 끝낼 때 지우고,
  죽었으면 45분에 저절로 풀린다. `orca automations runs` 의 status 값을 보지 않는 이유는
  그 문자열 목록이 어디에도 문서화돼 있지 않아서다 — 추측하면 가드가 **항상 통과하고도
  조용하다**.
- **환경 판정은 집합이다.** 같은 예외가 (staging 이 있던 때) staging·prod 에서 함께 나면 GlitchTip 이 이슈
  하나로 묶고 태그에 두 값을 다 담는다(실측: issue 1). 「첫 값이 production 인가」로 보면
  순서에 따라 prod 오류가 조용히 빠진다.
- **우리가 일부러 던지는 예외는 집지 않는다.** `SentrySmokeError`(`manage.py
  sentry_smoke`)가 도착한 것은 **오류 수집이 닿는다는 성공 신호**다 — 그걸 집으면 세션
  하나가 「사고가 아니다」라고 스스로 적힌 예외를 재현하려 애쓴다. 판정은
  `metadata.type`(예외 클래스 이름)으로 한다, 제목 문자열이 아니다 — 그 메시지는
  한국어라 바뀌면 조용히 샌다. 목록은 `DELIBERATE_EXCEPTION_TYPES` 한 자리다.
  `PriceDriftAlert`(#798, 아래 「모델 단가 표 대조」)도 같은 목록에 있다.
- **해결 표시는 PR 병합이 한다**(2026-10-02). 세션은 커밋 메시지 마지막 줄에
  `GlitchTip: <id>` 를 적고 **분기를 push 해 PR 을 연다**(`main` 에 직접 넣지 않는다). Jenkins
  `codemit/ci-pr` 가 home 검사로 줄 세우고 열차 `codemit/ci-train` 이 초록 묶음을 `main` 에 병합하고, **곧바로 그 PR 범위**
  (`merge-base..HEAD`)의 줄을 읽어 이슈를 resolved 로 돌린다(`Jenkinsfile.train` 의 병합 단계,
  자격증명 `glitchtip-automation-token`) — 「고친 것 같다」와 「고쳤다」를 가르는 자리다.
  범위가 PR 하나로 정확히 닫히므로 옛 방식의 두 문제가 없다: push 와 표시 사이의 5~10분
  공백(그래서 두던 `glitchtip-ack` 예고 코멘트)과, 연달아 push 할 때 취소된 실행이 범위를
  놓치던 것(오류 75 — 그래서 범위를 「직전에 그 잡이 성공한 실행 이후」로 잡았다,
  `glitchtip_resolve.py` 의 `auto` 모드가 그 흔적이다).
- **배경 세션은 「지금」을 말하는 문서를 고칠 수 없다.** 평소 티켓이라면 「티켓을 닫는
  기준」이 `CLAUDE.md`(`docs/ops/`)·`CONTEXT.md`·`docs/features/` 를 같은 커밋에서 고치라고 하는데,
  아무도 보고 있지 않은 세션에는 그 규칙을 적용하지 않는다 — 그 셋(과 `docs/adr/`)이
  틀렸을 때 대신 참을 말해 줄 것이 저장소에 없다. 그런 변경이 필요하면 세션은 **코드만
  분기에 push 하고 `ready-for-human` 티켓**으로 넘긴다(고칠 문장의 초안은 티켓 본문에
  적는다 — 적는 것은 되고 커밋하는 것은 안 된다). 재현하지 못한 오류도 `needs-info`
  티켓을 연다 — 클레임 때문에 다시 집히지 않으므로 티켓이 그 진단이 사람에게 닿는
  유일한 길이다.
- **그 게이트를 `.githooks/pre-commit` 이 기계로도 막는다.** 브랜치가 `auto-` 로
  시작하거나(Orca automation 이 실행마다 만드는 브랜치가 `auto-<이름>-run-<n>-<시각>`
  이다, 실측) `CODEMIT_UNATTENDED=1` 이면 그 네 경로가 staged 된 커밋을 거절한다.
  `--no-verify` 로 넘어가므로 벽이 아니라 감속방턱이다 — 인젝션에 대한 벽은 읽기 전용
  토큰과 경로 울타리이고, 이 검사가 잡는 것은 **정직한 생각없는 수정**이다.
- **precheck 가 청소도 한다 — 그리고 그 청소가 한 번 도는 세션을 죽였다**(#459).
  automation 은 세션이 뜨는 실행마다 워크트리와 브랜치(`auto-<이름>-run-<n>-<시각>`)를
  만들고 끝나도 치우지 않는다 — 안에 `node_modules`·`.venv` 가 각각 들어서므로 몇 건만
  쌓여도 이 머신의 디스크를 먹는다. 매분 도는 것이 precheck 하나뿐이라 그것이
  `origin/main` 에 머지된 `auto-*` 워크트리를 걷는데, **첫 판은 「머지됨」 판정을
  `merge-base --is-ancestor` 하나로 했다** — 막 만들어져 아직 커밋이 없는 분기는 팁이
  곧 `origin/main` 이라 그 판정을 통과했고, 진단 중인 세션이 첫 커밋 전에 다음 분
  precheck 에 워크트리째 사라졌다. 지금은 문이 셋이다:
  **(1)** 잠금이 살아 있으면 청소를 아예 하지 않는다(청소가 잠금 확인 **뒤로** 갔다),
  **(2)** 제 커밋이 없는 분기는 「아무것도 안 했다」로 보고 건드리지 않되
  `--lock-ttl-minutes`(기본 45분)보다 오래 식은 것만 걷는다(재현 실패로 커밋 없이 끝난
  워크트리가 영원히 남지 않게), **(3)** 머지 안 된 것은 그대로 남긴다 — 게이트에 걸려
  사람에게 넘긴 분기가 정확히 그 모양이다.
  사람 워크트리(`chain-*`·`int-*`)는 접두어가 달라 대상이 아니다. `--no-tidy` 로 끈다.
  **분기 이름은 마지막 경로 조각으로 본다**(2026-10-19) — Orca 가 `farrar142/auto-…` 처럼 사용자
  접두어를 붙인 뒤로 전체 이름이 `auto-` 로 시작하는지만 보던 판정이 하나도 맞지 않아 다섯 개가
  쌓여 있었다.
  **「머지됨」은 sha 가 아니라 변경으로 본다**(2026-10-03, `_branch_state`) — Jenkins 가 PR 을
  rebase 병합해 `main` 의 커밋 sha 가 분기와 달라서, 옛 `merge-base --is-ancestor` 판정으로는
  병합된 자동 진단 분기가 하나도 걷히지 않았다. 지금은 `git cherry` 로 분기 커밋이 전부 같은
  변경으로 `main` 에 들어갔는지 본다(`scripts/test_glitchtip_pick.py` 가 고정한다).
- **precheck 는 주 체크아웃의 스크립트를 돈다 — 그 체크아웃은 저절로 앞서 나가지 않는다.**
  automation 의 precheck 가 `/home/sandring/workspace/codemit/scripts/glitchtip_pick.py` 를 절대
  경로로 부르고 토큰도 그 체크아웃의 `.env` 에서 읽는다. 2026-10-02 부터 `main` 은 PR 로만
  들어가 주 체크아웃에서 커밋하는 사람이 없으므로, 이 스크립트를 고친 PR 이 병합돼도 **주
  체크아웃을 `git pull` 하기 전까지 스케줄러는 옛 스크립트를 돈다.** (세션 쪽 스킬은 실행마다
  `origin/main` 에서 새 워크트리를 만들어 늘 최신이다.)
- **GlitchTip 을 눈으로 읽을 때는 `scripts/glitchtip_get.py` 를 쓴다 — `curl` 로 치지
  않는다.** GlitchTip 의 오류 응답은 `{"detail": "Permission denied"}`·`{"detail":
  "Not Found"}` 라서, 그대로 파싱해 필드를 찾으면 **빈 값이 나오고 그것을 「값이 없다」로
  읽게 된다.** 이 저장소에서 실제로 세 번 그렇게 잘못 읽었다(코멘트가 비어 있다 → 실은
  권한 거부, 쿠키가 사라졌다 → 실은 이슈가 삭제됨). 이 도구는 **2xx 가 아니면 필드를
  보여주지 않고 상태와 본문만 적고 죽는다** — 「값이 없다」와 「물어볼 수 없었다」가 같은
  모양으로 나오지 않는다. 자격증명 자리(`cookies`·`data`·`cookie` 헤더)는 값을 찍지
  않고 **있다는 사실만** 알린다. 읽기 전용 토큰만 쓰고 알림 규칙 경로는 지원하지 않는다.

```bash
scripts/glitchtip_get.py issues            # 미해결 목록 (--all 로 해결된 것까지)
scripts/glitchtip_get.py event 60          # 최신 이벤트 요약 (--raw 로 전문)
scripts/glitchtip_get.py tags 60           # 환경·release
```

- **무엇이 집힐지 눈으로 보려면** 필터를 풀어 dry-run 한다(클레임도 잠금도 남기지 않고,
  청소도 하지 않는다):

```bash
scripts/glitchtip_pick.py --dry-run --any-status --any-environment
```
