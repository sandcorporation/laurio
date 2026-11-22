# 개발 환경 — 이벤트 서비스·워크트리 스택

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**이벤트 서비스는 `backend`와 같은 이미지를 ASGI로 띄우는 별도 프로세스다**
(ADR-0046) — 강의실이 새로고침 없이 화면을 갱신하는 SSE 엔드포인트
(`/api/classroom/events/stream`) 하나만 연다. 기존 API(`backend`)는 그대로
동기 gunicorn/`runserver`다. 강의실 BFF는 이 경로만 `CODEMIT_EVENTS_BASE_URL`
(`classroom/lib/auth/backend.ts`)로 이 서비스에 보내고 나머지는 전부
`backend`로 보낸다. 신호 자체는 `EVENT_BUS_ADAPTER_MODE`(dev·CI 기본값
`core.events_redis.RedisEventBus`, pytest 기본값은 `fake`)가 고르는 Redis
pub/sub 위에 산다 — Celery 브로커(DB 0)·Operator 세션(DB 1)과 같은 Redis
인스턴스의 DB 2다.

**prod 배포에도 이 서비스가 있다**(#380). `docker/compose.prod.yaml`이 `events` 서비스를 backend·celery-worker와
같은 `x-backend-env`(STORAGE_*·PAYMENT_* 등 이 프로세스가 실제로
쓰지 않는 값도 포함 — URLconf·settings.py가 backend와 완전히 같은 코드라서다)로
띄운다. `EVENT_BUS_ADAPTER_MODE`가 fake로 남으면 다른 `*_ADAPTER_MODE`와 같은
원칙으로 부팅 자체를 거부한다(`config/settings.py`의 `IS_DEPLOYED_ENVIRONMENT`
가드 + `core.checks.check_event_bus_adapter_mode`, #83과 같은 두 갈래) — 두 env
예시 파일이 실물 값(`core.events_redis.RedisEventBus`)을 채워 둔다.
`deploy.sh`는 `backend/` 변경에 이 서비스를 backend·celery-worker(beat 포함)·grader와
함께 바꿔 끼우고(넷이 **같은 이미지**를 쓴다, 2026-09-17 — 그 전에는 이미지가 넷이라
하나만 갈면 나머지가 옛 이미지에 남았다), 같은 방식(Host 헤더를 붙인 `/api/health`)으로
헬스 체크한다.

**저장소 밖의 TLS 리버스 프록시는 이 스트림을 버퍼링하면 안 된다.** SSE는 응답을
끊지 않고 계속 흘려보내는데, 프록시가 응답을 통째로 모았다가 한 번에 내보내면
(nginx의 `proxy_buffering` 기본값이 그렇다) 화면이 신호를 몇 초~몇 분 늦게
받거나 연결이 곧바로 끊긴 것처럼 보인다 — 코드가 아니라 그 앞단 설정의 문제라
이 저장소 안에서는 재현도 수정도 안 된다. `classroom.<운영 도메인>`을
서빙하는 프록시가 `/api/backend/classroom/events/stream` 경로(또는 그 도메인
전체)에 대해 버퍼링을 끄고, 유휴 연결을 짧게 끊지 않도록 타임아웃도 넉넉히
잡아야 한다 — 저장소 밖 오브젝트 스토리지의 버킷 생성과 같은 종류의 저장소 밖
수작업이다. 설정을
잊으면 강의실 실시간 갱신이 "가끔 늦게 온다" 또는 "아예 안 온다"로 보인다 —
화면이 폴링으로 물러나 기능 자체는 멈추지 않는다(ADR-0046).

**이벤트 서비스의 ASGI 진입점이 lifespan 을 직접 받는다**(2026-09-16,
`backend/config/asgi.py`). Django 의 ASGI 핸들러는 HTTP 가 아닌 scope 를 보면
`ValueError: ... not lifespan.` 을 던지고, uvicorn 은 그 기능만 끄고 계속 뜬다 —
서비스는 정상인데 **부팅마다 오류 하나가 남는다**. 오류 수집기를 붙이자마자 그
예외가 당시 배포 백엔드 프로젝트의 최다 이슈가 됐다(6건). 기동 명령에
`--lifespan off` 를 붙이는 대안은 compose 세 곳에 같은 말을 적어야 해서 버렸다.

**물러서는 배포(표식 단 마이그레이션·풀러 교체)에서는 backend 가 잠시 없다 — beat 의 tick 이
그때 죽는다.** (새 마이그레이션도 표식이 없으면 먼저 돌리고 겹쳐 바꿔 창이 없다 —
[배포](deploy.md)의 「backend·events 는 겹쳐 바꾼다」, ADR-0053.)
`deploy.sh` 가 backend 컨테이너를 내리고 올리는 사이 `core.run_scan` 의
내부 HTTP 호출이 `Connection refused` 로 실패했다(수집기를 붙인 첫날 3건). 스캔은
두 번 쏴도 한 번만 통과하므로(ADR-0003) 그 태스크가 **연결·타임아웃 실패만** 몇 번
물러서서 재시도한다 — 2xx 가 아닌 응답(서버가 대답은 했다)은 재시도하지 않고 그대로
실패로 남긴다. (강의실 채점은 #582 부터 내부 HTTP 를 부르지 않는다 — #584 부터는 Celery 도
아니고 `grader` 상주 프로세스가 한다, ADR-0059.)

**에이전트 채점 키 프록시 `llm-proxy`**(#998)는 dev compose 의 `agent` 프로필이라 기본 기동에 없다 —
`docker compose -f docker/compose.dev.yaml --profile agent up -d llm-proxy`(호스트 `CODEMIT_LLM_PROXY_PORT`, 기본
58002). `.env` 의 OpenAI 키는 잔고 0원이니 벤더 주소를 `LLM_PROXY_ANTHROPIC_BASE_URL`·`LLM_PROXY_OPENAI_BASE_URL`
로 흉내 서버에 돌린다. 호스트에서 바로 띄워도 된다: `uv run python manage.py llm_proxy --port <포트>`. 실행기만
붙는 내부 네트워크 `agent`(`internal: true`)가 dev·prod compose 둘 다에 있다. prod 에는 실행기를 부르는 쪽 내부 네트워크
`agent-call`(`celery-worker`·`agent-grader` 둘만, #1031)이 하나 더 있다 — 부르는 쪽은 `agent` 에 넣지 않는다.

**강의실 채점은 `grader` 서비스가 한다**(#584, ADR-0059) — dev compose 의 기본 기동에 있고(`docker
compose up -d` 에 들어간다), CI 의 e2e 스택도 띄운다. 제출·스캔은 「큐에 넣은 시각」만 찍고
`python manage.py grader` 가 0.5초마다 큐를 읽어 흉내 어댑터로 채점하므로 제출 뒤 곧바로(e2e 시험
하나 3초 안에) 끝난다. 로그는 `docker compose logs grader`(시도마다 `grader: submission=… status=…`
한 줄). grader 의 DB 연결은 정확히 1개(DB 스레드 하나)고, 소스 읽기 스레드·잠금 대기 상한·응답 상한·연결 타임아웃은 `CLASSROOM_GRADER_SOURCE_THREADS`(8)·`CLASSROOM_GRADER_LOCK_TIMEOUT_MS`(2000)·`SAFE_OUTBOUND_RESPONSE_MAX_BYTES`(2MB)·`SAFE_OUTBOUND_CONNECT_TIMEOUT_SECONDS`(10) 설정값이다. 마이그레이션보다 먼저 뜨면 큐를 읽다 실패해 간격을 늘려 다시 읽는다. **pytest 만**
`CLASSROOM_GRADER_INLINE` 이다 — 상주 프로세스가 없으니 큐에 넣는 자리에서 한 시도를 동기로 채점한다
(`classroom.grader.grade_inline`, 같은 임대·준비·결과 걸음에 벤더만 동기 길). 상주 grader 의 루프는
`classroom.grader.run_round()` 로 시험한다.

**그 밖의 Celery 태스크는 dev·CI 에서 eager 다**(#582) — `CELERY_TASK_ALWAYS_EAGER` 의 기본값이
배포가 아닌 곳에서 켜짐이라 `.delay()` 자리에서 태스크가 그대로 돈다(공모전 이미지 최적화 등).
`--profile celery` 의 worker(beat 를 `-B` 로 품는다, #859 — 배포와 같다)는 이 값을 `false` 로 받는다 — beat 가 쏜 태스크를 그 자리에서
eager 로 돌리면 `scripts/ci/celery-broker.sh` 가 보는 beat → worker 경로가 끊긴다. 배포 환경은 이 값이
켜지면 부팅을 거부한다.

호스트에서 `uv run pytest`를 돌릴 때 붙는 DB 포트 기본값도 `CODEMIT_DB_PORT`를 따라간다
(`backend/config/settings.py`). 컨테이너 안에서는 compose가 `POSTGRES_*`를 직접 주입한다.

**워크트리는 스택을 통째로 따로 띄운다.**

```bash
eval "$(sh docker/dev-env.sh)"
docker compose -f docker/compose.dev.yaml up -d
```

`docker/dev-env.sh` 가 체크아웃 경로에서 compose 프로젝트 이름과 **모든 포트**를 파생한다 —
DB·Redis·MinIO·이벤트 서비스·세 앱(#276부터 강의실이, #379부터 이벤트 서비스가 더해졌다)이
통째로 갈리므로 체인 둘이 서로의 데이터를 보지 않는다. 예전에는
스택 하나를 공유하고 시드 이름 접두어로 막았는데, 그 방식은 전역 건수나 단일 행(정책·시계)
앞에서는 성립하지 않는다.

**주 워크트리는 오프셋 0 이다** — 위 표의 포트가 그대로다. 판정 기준은 디렉터리 이름이
아니라 `git worktree list` 가 말하는 주 워크트리인가이고(다른 이름으로 클론해도 맞는다),
스크립트는 cwd 가 아니라 **자기 위치**를 기준으로 삼는다. 해시가 겹치면 나중에 뜨는 쪽이
포트 바인딩 실패로 **못 뜬다** — 조용히 남의 스택에 붙는 것보다 낫다.

**오프셋을 직접 고르려면** `CODEMIT_DEV_OFFSET=<0~9>` 를 준다(#1106) — 해시가 겹치거나 특정 포트가
필요할 때. 범위 밖이면 멈추고, 그 오프셋의 compose 프로젝트(`codemit-dev-N`)가 다른 체크아웃의
것이면(컨테이너 라벨 `com.docker.compose.project.working_dir` 로 판정) 멈춘다. 값이 없으면 위 규칙 그대로.

**주인 디렉터리가 이미 사라진 스택은 고아다**(#1186). 거절하지 않고 그 프로젝트의 컨테이너를
`docker compose -p <프로젝트> down` 으로 내린 뒤(**볼륨은 지우지 않는다**) stderr 로 한 줄 알리고 그 오프셋을 쓴다.
디렉터리가 있으면 위처럼 거절한다. `scripts/dev-server.sh reap`(5분 타이머)도 같은 판정(`docker/dev-stack-orphans.sh`)으로
워크트리가 사라진 `codemit-dev*` 스택의 컨테이너를 내린다.
**타이머가 없는 mac 은 `dev-env.sh` 가 시작 때 같은 판정으로 걷는다**(#1275) — `test.sh`(backend·e2e)와 dev 스택을
띄우는 모든 길이 `eval "$(sh docker/dev-env.sh)"` 로 시작하니 오프셋을 받는 길(직접 지정·해시·주 워크트리)과 상관없이
주인 디렉터리가 없는 `codemit-dev*` 스택의 컨테이너가 먼저 내려간다(볼륨은 남긴다, 알림은 stderr 한 줄). 전에는 직접
지정한 오프셋만 주인을 봤고 해시 길은 보지 않아, 주인 워크트리를 지운 뒤에도 그 db 가 남아 다음 작업자가 그 위에 붙었다.

**`-e2e` 스택은 일회용이라 주인 디렉터리가 있어도 걷는다**(#1192). `scripts/test.sh e2e` 는 띄우기 전에
`~/.codemit/dev-servers/<프로젝트>.owner`(자기 pid)를 남기고, 셸이 SIGKILL 로 죽어 EXIT trap 이 안 돌면 그 pid 의
`test.sh` 가 없다는 것이 고아 판정이다(표식이 없는 옛 스택은 한 시간 넘게 떠 있을 때만). `CODEMIT_E2E_KEEP=1` 은
`.keep` 을 남겨 12시간까지(`CODEMIT_E2E_KEEP_MAX_SECONDS`) 봐준다. 걷기는 `dev-server.sh reap`(work 의 5분 타이머)과
**`test.sh e2e` 시작 때**(타이머가 없는 mac)다. **티켓이 끝나면 `scripts/worktree-rm.sh <워크트리> [브랜치]`**
— 그 워크트리를 주인으로 둔 스택을 먼저 내리고(`-e2e` 는 볼륨까지, dev 스택 볼륨은 남김) dev 서버를 멈춘 뒤
워크트리·브랜치를 지운다. root 소유 파일이 남았으면 일회용 컨테이너로 지우고 이어 간다. dev 컨테이너가 pnpm 스토어를
워크트리 `.pnpm-store` 에 root 로 쓰던 것은 compose 가 `npm_config_store_dir=/pnpm/store` 로 막는다(#1220). 손으로 `git worktree remove` 만 하면 스택이 고아로 남는다.
`worktree-rm.sh` 는 **어느 체크아웃의 사본으로 불러도, 지울 워크트리 안에 선 채로도 돈다**(#1275) — 필요한 헬퍼를 임시 폴더로
옮겨 쓰고 git 은 `git-common-dir` 의 주 워크트리에서 부르니, mac 의 main 체크아웃이 묵어 스크립트가 없어도 작업자 워크트리의
사본(`scripts/worktree-rm.sh <그 워크트리>`)으로 끝낼 수 있다. 주 워크트리 자체는 지우지 않는다. 시험은 `python3 scripts/test_worktree_rm.py`.

**거절하면 뒤따르는 compose 도 돌지 않는다**(#1146). `eval "$(…)"` 는 명령 치환의 종료코드를 삼키므로,
거절 때 스크립트는 stdout 으로 `docker` 를 실패하는 함수로 가리고 `false` 로 끝나는 조각을 내보낸다 —
`;` 로 이어진 `docker compose` 도, `&&` 체인도, `set -e` 스크립트(`scripts/test.sh`)도 거기서 멈춘다.
stderr 는 까닭(어느 체크아웃이 그 오프셋을 쥐었나)과 고칠 길(빈 오프셋 고르기·묵은 워크트리 정리)을 말한다.
같은 셸에서 다시 `eval` 해 성공하면 가림이 풀린다. 이 옛 동작(빈 변수로 compose 가 기본 스택을 다시 만든다)이
#1124 의 사고였다. 시험은 `python3 scripts/test_dev_env.py`.
