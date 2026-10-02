# Codemit

## 개발 환경

Python + uv, Django + django-ninja, PostgreSQL. 백엔드는 `backend/`, 컨테이너 구성은 `docker/`.

```bash
docker compose -f docker/compose.dev.yaml up          # 전체 스택
docker compose -f docker/compose.dev.yaml up -d db redis   # 테스트용 인프라
scripts/test.sh backend tests/test_x.py              # 테스트(로컬은 400개까지, 전체는 PR CI)
```

**공개 포트가 표준이 아니다.** compose 기본값이 5432·8000·6379·3000을 통째로 비켜 잡아
뒀다 — 표준 포트를 쓰는 다른 프로젝트와 한 머신에 얹기 위해서다. 지금 개발 머신에는
그런 프로젝트가 없지만 기본값은 그대로 둔다(옮기면 아래 표의 환경변수와 문서·스크립트가
같이 흔들린다).

| | 호스트 | 컨테이너 | 환경변수 |
| --- | --- | --- | --- |
| PostgreSQL | `55432` | 5432 | `CODEMIT_DB_PORT` |
| backend | `58000` | 8000 | `CODEMIT_API_PORT` |
| Redis | `16379` | 6379 | `CODEMIT_REDIS_PORT` |
| 공개 앱(`frontend/`) | `53000` | 3000 | `CODEMIT_WEB_PORT` |
| 운영자 앱(`operator/`, #63) | `53001` | 3000 | `CODEMIT_OPERATOR_WEB_PORT` |
| 강의실 앱(`classroom/`, #276) | `53002` | 3000 | `CODEMIT_CLASSROOM_WEB_PORT` |
| 이벤트 서비스(`events`, #379, ADR-0046) | `58001` | 8001 | `CODEMIT_EVENTS_PORT` |
| 검색 엔진(`search`, dev `search` 프로필, #450) | `19200` | 9200 | `CODEMIT_SEARCH_PORT` |
| 연결 풀러(`pgbouncer`, dev `pgbouncer` 프로필, #453/#457) | `16432` | 6432 | `CODEMIT_PGBOUNCER_PORT` |

**이벤트 서비스는 `backend`와 같은 이미지를 ASGI로 띄우는 별도 프로세스다**
(ADR-0046) — 강의실이 새로고침 없이 화면을 갱신하는 SSE 엔드포인트
(`/api/classroom/events/stream`) 하나만 연다. 기존 API(`backend`)는 그대로
동기 gunicorn/`runserver`다 — SSE 연결 하나가 그 워커 풀을 붙잡지 않게
스트림만 갈랐다. 강의실 BFF는 이 경로만 `CODEMIT_EVENTS_BASE_URL`
(`classroom/lib/auth/backend.ts`)로 이 서비스에 보내고 나머지는 전부
`backend`로 보낸다. 신호 자체는 `EVENT_BUS_ADAPTER_MODE`(dev·CI 기본값
`core.events_redis.RedisEventBus`, pytest 기본값은 `fake`)가 고르는 Redis
pub/sub 위에 산다 — Celery 브로커(DB 0)·Operator 세션(DB 1)과 같은 Redis
인스턴스의 DB 2다.

**staging·prod 배포에도 이 서비스가 있다**(#380). `docker/compose.staging.yaml`·
`docker/compose.prod.yaml`이 각각 `events` 서비스를 backend·celery-worker·
celery-beat와 같은 `x-backend-env`(STORAGE_*·PAYMENT_* 등 이 프로세스가 실제로
쓰지 않는 값도 포함 — URLconf·settings.py가 backend와 완전히 같은 코드라서다)로
띄운다. `EVENT_BUS_ADAPTER_MODE`가 fake로 남으면 다른 `*_ADAPTER_MODE`와 같은
원칙으로 부팅 자체를 거부한다(`config/settings.py`의 `IS_DEPLOYED_ENVIRONMENT`
가드 + `core.checks.check_event_bus_adapter_mode`, #83과 같은 두 갈래) — 두 env
예시 파일이 실물 값(`core.events_redis.RedisEventBus`)을 채워 둔다.
`deploy.sh`는 `backend/` 변경에 이 서비스를 backend·celery-worker·celery-beat와
함께 바꿔 끼우고(넷이 **같은 이미지**를 쓴다, 2026-09-17 — 그 전에는 이미지가 넷이라
하나만 갈면 나머지가 옛 이미지에 남았다), 같은 방식(Host 헤더를 붙인 `/api/health`)으로
헬스 체크한다.

**저장소 밖의 TLS 리버스 프록시는 이 스트림을 버퍼링하면 안 된다.** SSE는 응답을
끊지 않고 계속 흘려보내는데, 프록시가 응답을 통째로 모았다가 한 번에 내보내면
(nginx의 `proxy_buffering` 기본값이 그렇다) 화면이 신호를 몇 초~몇 분 늦게
받거나 연결이 곧바로 끊긴 것처럼 보인다 — 코드가 아니라 그 앞단 설정의 문제라
이 저장소 안에서는 재현도 수정도 안 된다. `classroom.laurio.honeycombpizza.link`를
서빙하는 프록시가 `/api/backend/classroom/events/stream` 경로(또는 그 도메인
전체)에 대해 버퍼링을 끄고, 유휴 연결을 짧게 끊지 않도록 타임아웃도 넉넉히
잡아야 한다 — storage.honeycombpizza.link의 버킷 생성과 같은 종류의 저장소 밖
수작업이다(위 「staging 은 떠 있다」의 TLS 종단 프록시 문단 참고). 설정을
잊으면 강의실 실시간 갱신이 "가끔 늦게 온다" 또는 "아예 안 온다"로 보이고,
화면은 스트림이 끊기거나 막히면 폴링으로 물러나도록 설계돼 있어 기능 자체가
멈추지는 않는다(ADR-0046 결과 — "신호는 진실의 출처가 아니다").

**이벤트 서비스의 ASGI 진입점이 lifespan 을 직접 받는다**(2026-09-16,
`backend/config/asgi.py`). Django 의 ASGI 핸들러는 HTTP 가 아닌 scope 를 보면
`ValueError: ... not lifespan.` 을 던지고, uvicorn 은 그 기능만 끄고 계속 뜬다 —
서비스는 정상인데 **부팅마다 오류 하나가 남는다**. 오류 수집기를 붙이자마자 그
예외가 staging 백엔드 프로젝트의 최다 이슈가 됐다(6건). 기동 명령에
`--lifespan off` 를 붙이는 대안은 compose 세 곳에 같은 말을 적어야 해서 버렸다.

**새 마이그레이션이나 풀러가 든 배포에서는 몇 초 backend 가 없다 — beat 의 tick 이 그때
죽는다.** (그 밖의 배포는 겹쳐 바꿔 창이 없다 — 아래 「backend·events 는 겹쳐 바꾼다」.)
`deploy.sh` 가 backend 컨테이너를 내리고 올리는 사이 `core.run_scan`·`classroom.score_attempt` 의
내부 HTTP 호출이 `Connection refused` 로 실패했다(수집기를 붙인 첫날 3건). 스캔은
두 번 쏴도 한 번만 통과하므로(ADR-0003) 두 태스크가 **연결·타임아웃 실패만** 몇 번
물러서서 재시도한다 — 2xx 가 아닌 응답(서버가 대답은 했다)은 재시도하지 않고 그대로
실패로 남긴다.

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

## 배포 (dev / staging / prod)

세 compose 파일이 분리되어 있다 — 시크릿·어댑터 바인딩이 환경을 넘어 섞이지 않는다:

| | 파일 | `CODEMIT_DEPLOYMENT_TARGET` | 어댑터 | TLS·secure 쿠키 하드닝 |
| --- | --- | --- | --- | --- |
| dev | `docker/compose.dev.yaml` | (미설정) | 전부 Fake (MinIO만 예외) | 없음 |
| staging | `docker/compose.staging.yaml` | `staging` | 전부 real(토스 샌드박스, 스토리지는 자체 MinIO 등) | 없음 |
| prod | `docker/compose.prod.yaml` | `production` | 전부 real(토스 실물, 스토리지는 OCI Object Storage — 버킷 `codemit-prod`·`codemit-prod-public-images`) | 있음 |

어댑터 바인딩표(ADR-0007)는 각 compose 파일 상단 주석에 있다. 시크릿은
`docker/staging.env.example`/`docker/prod.env.example`을 복사해 `docker/.env.staging`/
`docker/.env.prod`로 채운다 — 둘 다 `.gitignore`가 막아 커밋되지 않는다.

**staging 은 떠 있다** — `https://laurio.honeycombpizza.link`(공개 앱),
`operator.laurio.honeycombpizza.link`(운영자 앱), `storage.honeycombpizza.link`(브라우저가
직접 PUT 하는 MinIO), `classroom.laurio.honeycombpizza.link`(강의실 앱, #277 —
`docker/compose.staging.yaml`의 `classroom` 서비스는 `${CODEMIT_CLASSROOM_WEB_PORT:-3002}`에
평문 HTTP로만 듣는다, 그 앞단에 이 도메인을 그 포트로 넘겨주는 TLS 종단 리버스 프록시가
저장소 밖의 수작업으로 있어야 실제로 열린다 — storage.honeycombpizza.link의 버킷 생성과
같은 종류의 바깥 작업이다). **그 MinIO 안에 버킷이 둘이다**(#233, ADR-0032) — 제출물이 사는
비공개 버킷과, 공모전 이미지만 사는 **익명 읽기 버킷**(`codemit-staging-public-images`)이다.
서버가 아니라 버킷을 가른다: 공개 읽기 정책이 버킷 단위라 이미지 쪽 설정을 잘못해도
소스에 닿지 못한다. 버킷 생성·정책·CORS 는 이 저장소 밖의 수작업이다. 어댑터가 전부
실물 구현이다: `PortOneV2VerificationAdapter`(#85) ·
`TossPGAdapter`(#87) · `TossPayoutAdapter`·`TossSellerAdapter`(#57) ·
`OpenAIScoringAdapter`(#88) · `OpenAIRequirementChatAdapter` ·
`GitHubAPIAdapter`(#193) · 알림 3채널(`AligoAlimtalkAdapter`·`AligoSmsAdapter`·
`AligoLmsAdapter`) · `RedisEventBus`(#380, ADR-0046 — 벤더 연동이 아니라 우리
자신의 Redis 위에서 도는 코드라 다른 일곱과 달리 "아직 미구현"인 적이 없었다) ·
`OpenSearchContestSearch`(#450/#451, 부모 #444 스펙 — `RedisEventBus`와 같은
이유로 벤더가 아니라 compose 가 직접 띄우는 `search` 서비스 위에서 도는 코드,
접속 주소는 `OPENSEARCH_URL=http://search:9200`).
각 dotted path 는 `docker/staging.env.example` 에 그대로 적혀 있다.

**staging·prod는 공모전 켜짐·유료 공모전 꺼짐이다**(#271/#413, ADR-0037을
ADR-0048이 amend). 처음에는 공모전을 통째로 껐지만(방향이 강의실로 틀어져서),
이제 돈을 다루지 않는 **무료 공모전**만 다시 열었다 — 결제·본인확인·환불·배분·
지급·인수인계 같은 유료 경로는 여전히 운영하지 않는다. 그래서 스위치가 둘이다:

- **공모전** — `CODEMIT_CONTEST_PRODUCT_ENABLED`(기본값 켜짐, `CODEMIT_DEPLOYMENT_
  TARGET`과 무관한 독립 값). staging·prod도 이제 기본 켜짐이다(dev·CI는 원래부터
  켜진 채).
- **유료 공모전** — `CODEMIT_PAID_CONTEST_PRODUCT_ENABLED`(같은 원칙의 독립 값).
  `docker/compose.staging.yaml`·`docker/compose.prod.yaml`만 기본을 `false`로
  겹쳐 쓴다 — dev·CI는 건드리지 않으므로 둘 다 켜진 채다(기존 유료 공모전
  테스트가 계속 초록인 이유).

코드도 데이터도 하나도 지우지 않았다 — Score의 PROTECT 때문에 지울 수도 없고(아래
「테스트」 절의 「채점이 한 번 돈 뒤에는」), 닫는 것은 표면뿐이다:

- **백엔드가 거절한다(진짜 문).** 공모전 스위치가 꺼지면 목록·상세·홈 큐레이션·
  내가 개최한 목록·조회수 기록, Contest 수정, 요구사항 AI grill, 공모전 이미지가
  전부 404다(403이 아니다 — 존재를 알려주지 않는다). 유료 공모전 스위치만 꺼지면
  (공모전은 켜진 채) 추가로 견적, 본인확인이 필요한 유료 개최·재개최, 유료
  심사기간 연장, 공모전 결제가 404다 — 무료 개최(`POST /api/contests/free`)·
  공개(`POST /api/contests/{id}/publish`, #415)는 이 스위치가 꺼져도 열려 있다
  (개최 권한만 본다). `GET /api/contests/categories`·`deliverable-types`는 예외다 — 주소는
  `/contests/` 아래지만 주소만으로는 어느 제품의 것인지 갈리지 않는 공용 참조
  데이터다. 운영자 표면(`/api/operator/*`)은 두 스위치와 무관하게 그대로 연다.
- **공개 앱이 감춘다.** 공모전 스위치가 꺼지면 헤더의 「공모전」·「공모전 개최」·
  「무료 공모전 개최」(#415), 헤더 계정 메뉴의 「내 공모전」(#375, 콘솔 현관은
  없다), `/contests/**`·`/console/contests/**` 전체가 빠지거나 404다. 유료
  공모전 스위치만 꺼지면 「공모전」 링크와 「무료 공모전 개최」 CTA는 남고
  「공모전 개최」(유료) CTA만 빠진다 — `/console/contests/new`가 전부 본인확인·
  견적·결제로 이어지는 유료 흐름이기 때문이다. 「무료 공모전 개최」가 가리키는
  `/console/contests/new-free`는 개최 권한이 결제를 대신하므로 유료 스위치와
  무관하게 열려 있다(staging·prod의 기본값이 정확히 이 조합이다). 앱과
  백엔드가 어긋나면 링크는 보이는데 앞이 404인 것이 고른 실패 모양이다
  (`CODEMIT_OPERATOR_ORIGIN`과 같은 종류의 어긋남).
- **유료 전용 스캔이 등록부에서 사라진다.** 유료 공모전 스위치가 꺼지면 환불
  둘·배분 둘·지급 관련 둘·인수인계(`payment-refund-request`·`payment-refund-
  reconcile`·`distribution-create`·`distribution-share-payout`·`payout-awaits-
  you`·`seller-registration-recovery`·`handover-release`) — `/api/internal/tick`·
  `/scans/{name}`·beat 스케줄 어디에도 안 나온다. 채점·저장소 가시성·알림·휴면·
  신원 파기·**Contest 상태 전이**(`contest-close`·`contest-judging-end` — 무료
  공모전도 마감·심사종료·수상을 거친다)는 공모전 스위치만 보고 그대로 돈다.

**한 곳에 모은 목록**은 `backend/core/contest_switch.py` 모듈 docstring이다 —
다시 켤 때 읽을 자리. **되돌리는 법**: `.env.staging`/`.env.prod`에
`CODEMIT_PAID_CONTEST_PRODUCT_ENABLED=true` 한 줄을 추가하고, **저장소 변수**
`STAGING_`/`PROD_CODEMIT_PAID_CONTEST_PRODUCT_ENABLED` 도 `true` 로 바꾼 뒤 CI 를 다시
돌려 배포한다 — frontend 는 그 값을 빌드 인자로 굽고, 굽는 곳이 CI 라 원본이 저장소
변수다(아래 「이미지는 CI 가 굽는다」, `docker/frontend.Dockerfile`). ADR을 새로 쓰지 않는다 — 되돌리기가 환경변수 한
줄이라 「되돌리기 어렵다」에 해당하지 않는다(방향 전환 자체의 근거는 ADR-0037·
ADR-0048에 있다).

**그래도 가드는 그대로다.** `core.adapters.check_adapter_mode`(`django.core.checks` 로
등록되어 `django.setup()` 이후 `manage.py migrate`/`check`/`runserver` 부팅 파이프라인에서
평가된다, #83)가 **열세 값**(`VERIFICATION_ADAPTER_MODE`·`PAYMENT_ADAPTER_MODE`·
`PAYOUT_ADAPTER_MODE`·`SELLER_ADAPTER_MODE`·`LLM_ADAPTER_MODE`·
`CLASSROOM_SCORING_ADAPTER_MODE`(#340, ADR-0043 — 강의실 채점 전용, `LLM_ADAPTER_MODE`와
별개다)·`LLM_REQUIREMENT_CHAT_ADAPTER_MODE`·`GITHUB_ADAPTER_MODE`(#193)·
`NOTIFICATION_ALIMTALK_ADAPTER`·`NOTIFICATION_SMS_ADAPTER`·`NOTIFICATION_LMS_ADAPTER`·
`EVENT_BUS_ADAPTER_MODE`(#380, ADR-0046 — 강의실 실시간 신호)·
`SEARCH_ADAPTER_MODE`(#451, 부모 #444 스펙 — 공모전 검색, 실물은
`contests.search_opensearch.OpenSearchContestSearch`)이
배포 환경에서 fake 이거나 임포트되지 않으면 부팅 자체를 거부한다 — 컨테이너가 뜬 채로 첫 요청에서야 죽는 것보다 정직하게 못 뜨는 편이다.

`config/settings.py`의 `IS_DEPLOYED_ENVIRONMENT`(staging+production)가 fake 어댑터
바인딩을 부팅 시점에 거부하고, `IS_PRODUCTION_DEPLOYMENT`(production만)가 추가로
`manage.py check --deploy`가 요구하는 HSTS·SSL 리다이렉트·secure 쿠키·강한
`SECRET_KEY`를 강제한다. staging은 검증용 서브 호스트라 운영자가
`POST /api/internal/tick`을 수동으로 쏠 수 있다(tick 은 스캔 등록부 `core/scans.py` 의 스캔
**전부**를 등록 순서로 한 바퀴 돈다 — 전이·채점·환불·배분·지급·알림. 스캔 하나만 돌리려면
`POST /api/internal/scans/{name}`, #137/#140) — 두 파일 모두 `INTERNAL_API_TOKEN`이 없으면
부팅 자체가 거부된다.

**tick 은 시간을 앞당기지 않는다.** 예전 문장은 「tick 을 쏴서 21일 시나리오를 몇 초에
재현할 수 있다」였는데 그건 사실이 아니다 — tick 은 인자를 받지 않고(`core/api.py`),
`/scans/{name}` 의 `params` 는 **fake 어댑터 시나리오 선택 전용**이며(환불의 `simulate` 등,
staging 은 실물 어댑터라 해당 없음), 배포 환경의 시계는 실제 시계다(ADR-0003). tick 이 하는
일은 **「지금 시점에서 이미 밀린 일을 beat 를 기다리지 않고 즉시 처리한다」**이지 미래로
가는 것이 아니다.

그래서 며칠 걸리는 시나리오를 몇 초에 보려면 **데이터의 시각을 과거로 옮긴다.** 데모 시드가
그렇게 되어 있고(9/2 에 심으면서 마감을 8/25~9/26 으로 흩뿌린다), #186 의 환불 검증도 그렇게
했다 — Contest 의 `deadline_at` 을 한 시간 전으로 옮기고 tick 을 한 번 쏘니 `contest-close` 와
`payment-refund-request` 가 같은 `as_of` 안에서 연달아 돌아 토스에 실제 취소까지 갔다.
이걸 모르고 tick 만 쏘면 「아무것도 안 움직인다」로 보인다.

**내부 API 는 컨테이너 안에서 치고, Host 헤더를 붙인다.** staging·prod 의 backend 는 호스트
포트를 열지 않는다(#485 — 아래 「backend·events 는 겹쳐 바꾼다」) — `docker exec
codemit-staging-backend-1 …` 안에서 `127.0.0.1:8000` 으로 친다. 그때 Host 가
`ALLOWED_HOSTS` 에 없으면 Django 가 **400** 을 낸다 — gunicorn 은 멀쩡한데 400 만 온다.
`DJANGO_ALLOWED_HOSTS` 의 첫 항목을 쓴다(배포 헬스 체크가 이미 그렇게 한다).

**운영자 앱(`operator/`)도 두 compose 파일에 뜬다**(#70). 공개 앱(`frontend`)과
같은 3스테이지 이미지(`docker/operator.Dockerfile` — dev/builder/runner)를 쓰고,
배포 compose는 `target: runner`를 명시적으로 고른다. 필수 설정은
`CODEMIT_OPERATOR_ORIGIN`과 `CODEMIT_API_BASE_URL`— 배포 환경에서 둘 중 하나라도
비면 `operator/instrumentation.ts`가 첫 요청을 받기 전에 `process.exit(1)`로
프로세스를 끊는다(`throw`만으로는 Next가 그 에러를 삼켜 컨테이너가 Up인 채로
이유 없는 500만 낸다는 게 공개 앱 쪽에서 이미 확인된 사실이다).

**`CODEMIT_OPERATOR_ORIGIN`은 백엔드와 운영자 앱이 같은 `.env.staging`/`.env.prod`
줄 하나를 나눠 읽는 값이다** — 백엔드의 `OperatorOriginMiddleware`가 기대하는
오리진과 운영자 앱이 나가는 요청에 붙이는 오리진이 어긋나면 로그인을 포함한
모든 운영자 변경 요청이 조용히 403이 된다(fail-closed라 보안 구멍은 아니지만
원인을 찾기 어렵다 — 이 저장소가 이미 두 번 겪은 실패). 공개 앱의 오리진과
반드시 다른 서브도메인을 쓴다 — 같은 오리진을 공유하면 공개 앱이 뚫렸을 때
운영자 세션 쿠키까지 노출될 길이 생긴다.

**커밋이 prod 까지 가는 길은 넷이다**(2026-10-02):

1. **브랜치 → PR → `main`.** Jenkins `codemit-pr`(Multibranch, `Jenkinsfile.pr`)가 브랜치마다
   전체 시험을 돌리고(아래 「CI 는 Jenkins 에서 돈다」), 초록이면 그 브랜치의 열린 PR 을 `main`
   에 **rebase 병합**한다(초안·`hold` 라벨은 빼고, `scripts/ci/automerge.py`). **`main` 에 직접
   push 하지 않는다** — 그러면 시험 없이 이미지가 구워져 staging 까지 간다.
2. **`main` → `staging`.** GitHub Actions(`.github/workflows/images.yaml`, 호스티드 러너)가
   이미지 열둘과 부팅 가드 셋을 돌리고, 다 초록이면 `staging` 을 그 커밋으로 **fast-forward**
   한다(저장소 **배포 키**, secret `PROMOTE_DEPLOY_KEY` — Actions 토큰은 워크플로 파일을 바꾼
   커밋을 push 하지 못한다, 2026-09-17).
3. **`staging` → staging 배포.** 웹훅이 Jenkins `laurio` 잡(`Jenkinsfile`)을 부른다.
4. **staging 초록 → `production` → prod 배포.** 그 잡이 끝에서 `production` 을 같은 커밋으로
   fast-forward 하고(`scripts/ci/fast_forward.py`, Jenkins 자격증명 `github-sandcorporation-token`),
   웹훅이 `codemit` 잡(`Jenkinsfile.production`)을 부른다.

`staging`·`production` 은 머지 커밋을 만들지 않으므로 언제나 `main` 의 어느 커밋 그 자체다.
늦게 끝난 옛 커밋은 건너뛰고, 브랜치가 `main` 에서 갈라져 있으면 밀어붙이지 않고 빨갛게
멈춘다. **두 브랜치에 직접 커밋하지 않는다.** (예전에는 main 의 Actions CI 가 시험까지 돌리고
초록이면 `promote-production.yaml` 이 `production` 을 앞당겼다 — staging 을 거치지 않았다.)

prod 배포의 `Jenkinsfile.production` 은 `production` 브랜치
빌드일 때만 `deploy.sh prod <명령>` 을 단계별로 부르는 얇은 껍데기이고, **sub 의 Jenkins(staging 과 같은 컨트롤러)에
붙은 에이전트 `oracle`** 에서 돈다(라벨 `oracle`). 에이전트는 Oracle A1 호스트의 `jenkins-desktop-agent`
컨테이너(root·호스트 docker 소켓, 이미지 정의는 호스트 `/server/jenkins`)이고, 이제 **이미지를 굽지
않고 ghcr 에서 받기만 한다**(아래). 비상용 로컬 빌드(`DEPLOY_IMAGE_SOURCE=build`)를 쓸 때만 그 이미지에
buildx 가 있어야 한다 — 없으면 Dockerfile 의 `RUN --mount` 에서 네 빌드가 전부 죽었다(2026-09-14 빌드
#4~#6, 지금은 `deploy.sh` preflight 가 먼저 멈춘다). 호스트 `/var/jenkins_home/workspace` 가 컨테이너
`/home/jenkins/agent/workspace` 로 붙어 있어, 노드의 Remote root directory 는 컨테이너 경로
`/home/jenkins/agent`, 잡 이름은 `codemit` 이어야 호스트의 `/var/jenkins_home/workspace/codemit` 에 둔
`docker/.env.prod`(chmod 600)·배포 표식을 쓴다. 잡·노드·`.env.prod` 는 저장소 밖에서 사람이 만든다.

**이미지는 GitHub Actions 가 굽는다 — staging·prod 서버는 받기만 한다**(2026-09-17, 러너는
2026-10-02 부터 호스티드). 예전에는 배포마다 각 서버가 다시 구웠다 — prod(oracle)는 배포마다
제 CPU 로 Next 빌드 셋을 돌렸다. 지금은 `main` 에 들어온 커밋마다 여섯 이미지를
ghcr(`ghcr.io/sandcorporation/codemit-*`, 비공개)에 올린다(`images.yaml`):

| 잡 | 러너 | 태그 |
| --- | --- | --- |
| `images-staging` | `ubuntu-latest`(amd64) | `codemit-backend:<sha>-amd64`, 세 앱 `:<sha>-staging`, `codemit-search:<sha>-amd64`(#450/#451), `codemit-pgbouncer:<sha>-amd64`(#453/#458) |
| `images-prod` | `ubuntu-24.04-arm`(arm64) | `codemit-backend:<sha>-arm64`, 세 앱 `:<sha>-prod`, `codemit-search:<sha>-arm64`(#450/#451), `codemit-pgbouncer:<sha>-arm64`(#453/#458) |

잡은 서비스마다 하나(matrix, staging 6 + prod 6)이고 각자 제 아키텍처로 굽는다 — 에뮬레이션이
없다. 캐시는 레지스트리(`codemit-buildcache`)에 있어 VM 이 매번 새것이어도 맞는다. 예전에는
셀프호스티드 mac(그 전에는 sub)이 구웠다 — sub 는 테스트 잡과 staging 스택이 SATA SSD 하나를
나눠 써 빌드를 얹자 디스크 대기가 14~84% 로 치솟았고, 호스티드는 그때 결제 문제로 못 썼다.
**arm64 호스티드를 못 쓰게 되면** 저장소 변수 `ARM_RUNNER_LABELS` 에 다른 러너 라벨을 JSON 으로
적는다(예: `["self-hosted","ARM64","mac-arm"]`).

- **backend·search 는 환경을 가리지 않아 아키텍처로만 가른다**(#450/#451 — search 는
  Next 앱이 아니라 `NEXT_PUBLIC_*` 처럼 굳는 값이 없다). 세 앱은 `NEXT_PUBLIC_*` 가 굳으므로
  환경마다 따로 굽는다 — 그 값의 원본은 서버 env 가 아니라 **저장소 변수 `STAGING_*`·
  `PROD_*`** 다(조직이 free 요금제라 비공개 저장소의 environment 기능을 못 써 접두어로
  가른다). 값을 바꾸면 CI 를 다시 돌려야 이미지에 반영된다.
- **서버는 배포 에이전트 컨테이너에 한 번 저장해 둔 ghcr 로그인으로 받는다**(read:packages
  classic PAT). 두 컨테이너(sub 의 `jenkins`, oracle 의 `jenkins-desktop-agent`) 모두
  `/root/.docker` 가 named volume 이라 컨테이너를 다시 만들어도 남는다(oracle 은 2026-09-17
  에 `jenkins_docker` 를 붙였다). 로그인이 없으면 `deploy.sh preflight` 가 멈추고, PAT 가
  만료되면 pull 에서 멈춘다. ghcr 는 git SSH 키로 인증할 수 없다.
- 사람 작업(PAT·Jenkins 토큰·저장소 변수)은 `scripts/ghcr-setup-wizard.sh` 가 단계별로
  안내한다(그 안의 mac 러너·`deploy-staging` 단계는 2026-10-02 이전 구조의 것이다). ghcr·CI 가 막혔을 때의 비상구는 서버에서
  `DEPLOY_IMAGE_SOURCE=build sh ./deploy.sh <대상>` — 예전처럼 그 자리에서 굽는다.

**staging 배포는 `staging` 브랜치가 부른다**(2026-10-02). Jenkins 잡(`/var/jenkins_home/jobs/laurio`)은
**Pipeline** 이고(`<flow-definition>`, `scriptPath: Jenkinsfile`), 브랜치 지정은 `*/staging`,
트리거는 GitHub 웹훅(`GitHubPushTrigger`)이다. `images.yaml` 이 이미지를 다 올린 **뒤에** 그
브랜치를 움직이므로 웹훅이 잡을 부르는 순간 이미지는 ghcr 에 있다. 늦게 도착한 옛 커밋은
`deploy.sh plan` 이 「더 새 커밋이 이미 배포돼 있다」로 건너뛰고, 배포 표식도 뒤로 옮기지
않는다. 초록이면 끝에서 `production` 을 같은 커밋으로 앞당긴다(위 넷째 길). 예전에는 main 의
CI 가 `buildWithParameters` 로 `DEPLOY_SHA` 를 채워 불렀다(그때 브랜치 지정은 `*/main`).

**실제로 굽는 것은 `Jenkinsfile` 이 단계마다 부르는 `deploy.sh` 의 명령이다.** 두
Jenkinsfile 이 「(staging 은 대상 확인 →) Preflight → 변경 계획 → 이미지(서비스별 병렬 pull) →
교체 → 확인 → 배포 표식 → 정리」를
각각 한 단계로 보여주고, 단계 본문은 `sh ./deploy.sh <대상> <명령>` 한 줄이다 — `plan` 이
`.jenkins-<대상>-plan` 에 `KEY=value` 로 적은 계획을 파이프라인이 읽어 이미지 단계의 `when` 을
정한다. 논리는 여전히 `deploy.sh` 에만 있고, 사람이 손으로 돌릴 때는 `deploy.sh <대상>`
(= `all`) 한 번이면 전부 돈다. 예전에는 한 단계로 통째로 불러 Jenkins 화면에 「배포」 하나만
보였다. 더 예전에는 잡이 freestyle 이라 `Jenkinsfile` 이 읽히지 않았고, 그걸 모르고
Jenkinsfile 만 고쳤다가 빌드가 `cannot open ./deploy.sh` 로 통째로 실패한 적이 있다.

**빌드가 끝나면 디스코드로 결과가 간다**(2026-09-18). 두 Jenkinsfile 의 `post { always }`
가 성공·실패·중단을 가리지 않고 한 줄을 보낸다 — 대상(staging/prod)·결과·빌드 번호·커밋
12자·소요 시간·빌드 주소다. 배포는 사람이 화면을 보고 있지 않을 때 도는 일이라 끝났다는
사실이 사람에게 닿는 자리가 없었고, 실패는 더 그랬다(2026-09-17 staging 배포가 정리
단계에서 빨갛게 끝난 것을 한참 뒤에 알았다).

**웹훅 주소는 저장소에 없다** — Jenkins 자격증명(Secret text) `discord-deploy-webhook`
이 들고 있고 파이프라인은 이름으로만 부른다. 그 값을 아는 사람은 그 채널에 아무 말이나
올릴 수 있어서 커밋에 남기지 않는다. **알림이 실패해도 빌드 결과는 그대로다** —
`catchError` 와 `|| true` 가 그것을 보장하므로, 자격증명이 없는 Jenkins 에서도 배포는
그대로 돈다.

**「다른 프로젝트가 빌드된 뒤에」 트리거(`triggers { upstream(...) }`)는 쓰지 않는다** — prod
잡은 staging 잡의 **커밋**을 따라가야 하는데, upstream 트리거는 prod 잡이 자기 브랜치의 끝을
배포하게 한다. 그래서 staging 잡이 `production` 브랜치를 그 커밋으로 옮기고, prod 잡은 자기
브랜치의 웹훅으로 돈다.

**배포 끝에 호스트의 도커 디스크를 비운다**(`deploy.sh <대상> prune`, 2026-09-17). 커밋마다
ghcr 에서 새 태그를 받으니 옛 커밋 이미지가 쌓이고, oracle 에는 ghcr 이전에 굽던 빌드 캐시가
남아 있었다(정리 전 sub 이미지 78GB·빌드 캐시 107GB·루트 86%, oracle 이미지 76GB·캐시 47GB).
이 저장소의 ghcr 이미지 중 **이번 커밋 것이 아닌 것**과, 태그 잃은 이미지, 사흘 넘게 안 쓴
빌드 캐시만 지운다 — 돌고 있는 컨테이너가 쓰는 이미지는 도커가 거절해 남고, 다른 프로젝트의
이미지는 건드리지 않는다(`image prune -a` 를 쓰지 않는다). 정리는 무엇이 실패해도 0 으로
끝나 배포를 실패로 만들지 않는다. 되돌리기는 ghcr 에서 다시 받는다.

**그 정리는 호스트 디스크만 비운다 — ghcr 쪽은 따로 지운다**(2026-09-20, Jenkins 잡
`codemit-ghcr-prune` — `Jenkinsfile.ghcr-prune`·`scripts/ci/ghcr_prune.py`, 2026-10-02 에 Actions
에서 옮겼다). 레지스트리에 쌓이는 옛 버전을 아무도 걷지 않아 **쓰기가 403 으로 막혔다**:
09-18 까지 초록이던 이미지 잡이 09-20 부터 전부 ghcr 토큰 교환에서 403 을 받아 **배포가 이틀
멈췄다**. 그때 실측이 이미지 여섯 99 버전 · 빌드 캐시(`codemit-buildcache`) **176 버전**이다 —
캐시 쪽은 대부분 태그 없는 블롭이라 화면에서 보이지도 않는다. **읽기는 그대로 됐다** — 쓰기만
막히는 것이 용량 초과의 모양이다. 지금은 매일 새벽 4시(서울)와 손으로 도는 잡이 패키지마다
최근 것만 남기고 지운다(이미지 12·캐시 10, 파라미터로 바꾼다, `DRY_RUN` 도 있다). **레지스트리
쓰기가 막혀도 이 삭제는 된다.** 토큰은 Jenkins 자격증명 `ghcr-prune-token` — **classic PAT**
(`read:packages`·`delete:packages`)여야 한다(fine-grained 토큰은 패키지 API 에 닿지 못한다).
**되돌릴 수 없지만 돌고 있는 서비스는 영향이 없다**: 배포된 이미지는 이미 그 호스트에 있고,
지워서 잃는 것은 그 커밋으로 pull 해 되돌리는 길뿐이다(최근 몇 커밋은 남는다).

**backend·events 는 겹쳐 바꾼다 — 배포 중에도 요청이 끊기지 않는다**(#485, 2026-09-22).
예전에는 컨테이너를 내리고 새로 올려, 배포마다 공개 앱이 13~16초 동안 500 을 냈다(staging
실측, GlitchTip 64·74·75 — BFF 재시도 예산 약 15.8초보다 길었다). 지금은 `deploy.sh` 의
`rolling_replace` 가 서비스를 잠시 둘로 늘려(`--scale 2 --no-recreate`) 새 것이
`/api/health` 에 답한 뒤에야 옛 것을 멈추고, 새 것의 이름을 옛 이름(`…-backend-1`)으로
되돌린다 — 그래서 `docker exec codemit-staging-backend-1` 은 배포 뒤에도 그대로다. 새 것이
150초 안에 답하지 않으면 새 것만 지우고 배포가 실패로 끝난다 — **옛 것은 계속 요청을
받는다.** celery-worker·beat 는 지금처럼 내리고 올린다(beat 는 하나여야 하고 태스크는 Redis
에서 기다린다).

- **물러서는 배포가 셋이다** — 배포 범위에 `backend/*/migrations/` 변경이 있을 때(겹친 몇
  초 동안 옛 코드가 새 스키마 위에서 돌면 없는 컬럼을 찾는다), 풀러를 바꿀 때(넷을 먼저
  내린다 — 「풀러를 바꿔 끼울 때는」), 겹칠 옛 컨테이너가 없을 때. 그때는 예전처럼 내리고
  올려 몇 초 창이 생긴다. `deploy.sh plan` 이 어느 쪽인지와 이유를 출력한다.
- **그래서 호스트 포트가 없다** — 같은 서비스 둘이 한 호스트 포트를 잡을 수 없다. 쓰는 곳이
  없었다: 배포 헬스 체크는 컨테이너 안에서 치고 세 앱은 `backend:8000` 으로 간다. staging 의
  `api.laurio.honeycombpizza.link`(저장소 밖 npmplus → 호스트 8000)는 남은 로그 사흘 동안
  인증서 확인 말고는 스캐너뿐이었다 — 포트가 닫히며 끊긴다.
- **실측**(세 호스트의 compose 2.33·5.1·5.5, 장난감 서비스): 둘인 동안 DNS 가 둘을 번갈아
  돌려주고, 옛 것을 멈추는 7초 동안 699번 중 연결 거부 1번 — BFF 가 연결 거부를 다시
  보낸다.

`deploy.sh` 는 **바뀐 것만 바꿔 끼운다** — 이미지 태그가 커밋마다 달라서 계획 없이 `up` 하면
바뀌지 않은 서비스까지 전부 다시 뜨기 때문이다(CI 는 매 커밋 여섯 이미지를 다 올리므로 어느
서비스든 받을 이미지는 있다). 기준점은 `.jenkins-staging-deployed`
(gitignore, 빌드 디렉터리에 남는다 — 시크릿과 같은 전제). 그 파일이 없거나 그것이
가리키는 커밋이 저장소에 없으면 전부 바꿔 끼운다. 경로 → 서비스 팬아웃은 1:1 이 아니다:
`backend/` 는 **backend + celery-worker + celery-beat + events**(#380, ADR-0046)를
함께 간다(넷이 한 이미지 이름을 쓴다, 2026-09-17 — 예전에는 공유 `image:` 태그가 없어
**이미지가 넷**이었고, `build backend` 만 하면 나머지 셋이 옛 이미지에 남아 배포가 초록으로
끝난 채 스캔·강의실 실시간 신호만 옛 코드로 돌았다),
`packages/` **아래 무엇이든** 과 `pnpm-lock.yaml`·`pnpm-workspace.yaml`·루트
`package.json` 은 **frontend + operator + classroom**(#277)을 함께 간다 — 어느 앱이 어느
패키지를 쓰는지로 가르지 않는다(`deploy.sh` 의 경로 규칙 하나다). `docker/search.Dockerfile`
은 **search**(#450/#451) 하나만 간다 — backend 코드와 무관하게 nori 플러그인을 넣은
OpenSearch 이미지 자체만 바뀐다. `docker/pgbouncer.Dockerfile`·`docker/pgbouncer/`
는 **pgbouncer**(#453/#458) 하나만 간다 — 연결 풀러 이미지 자체만 바뀐다. 없는
컨테이너는 변경 여부와 무관하게 받아서 띄운다 — 「없음」은 「최신」이 아니다.

**이벤트 서비스가 없어도 배포는 실패로 끝나지 않는다 — 다만 헬스 체크는 있다.**
`events` 는 `backend`·`celery-worker`·`celery-beat` 와 같은 무게로 받고 바꿔
끼우지만, 그 프로세스가 죽으면 강의실 화면만 폴링으로 물러난다(ADR-0046 결과 —
스트림은 진실의 출처가 아니다). 그래도 `deploy.sh` 는 다른 서비스와 똑같이
`/api/health` 로 응답을 확인한다 — 옛 코드가 조용히 계속 도는 것과, 프로세스가
아예 죽어 있는 것은 다른 문제이고 후자는 배포 실패로 다뤄야 하기 때문이다.

**동시 시청자의 천장은 자원이 아니라 열 수 있는 파일 개수였다**(2026-09-18).
실시간 신호 스트림 하나가 이벤트 서비스에서 서술자 둘(브라우저 소켓 + Redis
구독)을, 강의실 앱에서도 둘(브라우저 소켓 + 이벤트 서비스로 나가는 소켓)을
쓴다. 컨테이너 기본 soft 한도가 1024 라 staging 실측에서 **약 505개**에서
`Too many open files` 로 막혔다(1500개를 붙여 잰 값 — 그때도 이벤트 서비스는
CPU 0.2%·메모리 180MB 로 거의 놀고 있었다). 두 서비스의 `nofile` soft 를
65536 으로 올려 두었다(검색 서비스가 이미 쓰던 값, hard 는 원래 524288).

**같은 날 잰 처리량**(staging, 컨테이너 직접, CI 유휴): 백엔드 API 는 동시 4에서
**602 rps**(동기 gunicorn 워커가 넷이라 그 지점이 정점이고, 그 뒤로는 처리량이
유지된 채 지연만 는다), 공개 앱의 서버 렌더링은 **약 135 rps**(Next 프로세스가
하나다 — 사람이 쓰는 경로에서는 여기가 백엔드보다 먼저 막힌다). prod 는 코어 4의
arm64 라 같은 페이지 한 건이 staging 11ms 대 prod 41ms 였다.

**검색이 없어도 배포는 실패로 끝나지 않는다 — 다만 헬스 체크는 있다**(#450/#451,
부모 #444 스펙과 같은 원칙). `backend`·`celery-worker`·`celery-beat`·`events`
넷은 `search` 를 시작 순서로만 기다린다(compose의 `depends_on: service_started`
— 헬스가 아니다) — 검색이 죽어 있어도 그 넷은 뜨고, 목록 API 는 DB 검색으로
물러난다(`contests.search.search_contests`). 그래도 `deploy.sh health search`
는 OpenSearch 자신의 클러스터 헬스 엔드포인트로 응답을 확인한다 — 옛 색인이
조용히 계속 도는 것과 프로세스가 아예 죽어 있는 것은 다른 문제다. 검색이나
backend 를 바꿔 끼운 뒤에는 `deploy.sh reindex`(`manage.py
rebuild_contest_search_index`)가 전체 재색인을 한 번 강제한다 — 매일 도는
`contest-search-reindex` 스캔의 하루 제한을 기다리지 않는다.

**연결 풀러(pgbouncer)가 죽으면 검색·이벤트 서비스와 반대로 배포가 실패로
끝난다 — 그리고 그래야 맞다**(#453/#458). `backend`·`celery-worker`·
`celery-beat`·`events` 넷은 이제 DB 를 직접 가리키지 않고 `pgbouncer` 를
가리킨다(`POSTGRES_HOST=pgbouncer`) — search 처럼 시작 순서만 기다리는
`service_started` 가 아니라 `db` 와 같은 `service_healthy` 로 그 넷의
`depends_on` 에 걸려 있다. **DB(`db`) 자신은 살아 있어도 풀러가 죽어 있으면
그 넷은 애초에 뜨지 못한다** — 이 넷이 실제로 여는 것은 DB 연결이 아니라
풀러 연결이기 때문이다. `deploy.sh health backend`(그리고 `events`)가
평소처럼 `/api/health` 로 확인하는 것이 곧 풀러가 붙어 있다는 확인이다
(#453 사용자 스토리 13) — 그 경로 자체가 DB 까지 왕복해야 200 을 낸다.
풀 모드는 트랜잭션이고, 그 제약(서버측 커서가 깨지는 것)을 dev pgbouncer
프로필로 실제로 재현해 확인한 결과는 위 「Postgres 앞 연결 풀러」 절과
`config/settings.py`의 `DISABLE_SERVER_SIDE_CURSORS` 주석에 있다 — staging·
prod compose 는 그 환경변수(`CODEMIT_DB_DISABLE_SERVER_SIDE_CURSORS=true`)를
기본으로 켠다. **되돌리는 법**: 네 프로세스의 `POSTGRES_HOST`를 다시 `db`로
(그리고 위 환경변수를 다시 `false`로) 돌리면 앱이 DB를 직접 가리키던
이전 상태로 즉시 돌아간다 — 풀러 컨테이너 자체를 지울 필요는 없다.

**풀러를 바꿔 끼울 때는 그 넷을 먼저 내린다**(2026-09-22, #481~#484). 예전
순서(넷이 풀러에 붙은 채 풀러부터 교체)는 그 순간 날아가던 질의를 전부
`server closed the connection unexpectedly` 로 끊어 prod 사용자에게 500 을
냈다 — 9-21 배포에서 공모전 목록 한 화면의 요청 셋이 같은 밀리초에 그렇게
죽었다(GlitchTip 70~73). 지금 `deploy.sh` 는 넷을 `stop`(SIGTERM — 받던 요청은
끝낸다) → 풀러 교체 → `health pgbouncer` → 넷을 다시 올린다. 풀러가 끝내 안
뜨면 배포가 실패로 끝나고 넷은 **내려간 채** 남는다(풀러 없이는 어차피 DB 에 닿지
못한다). backend 를 바꾸지 않는 배포면 내린 그 컨테이너를 `start` 로 되살린다 —
다시 만들지 않으므로 이미지가 그대로다.

**실제로 돌려 본 결과**(2026-09-22, 풀러만 바꾼 `6c63063` 이 staging·prod 둘 다에
배포됐다): 순서는 설계대로였고 backend 넷은 같은 컨테이너·같은 이미지로 되살아났으며,
**backend 의 `OperationalError`(70~73)는 두 곳 모두 다시 나지 않았다.** 다만 **실패
창이 사라지지는 않았다** — staging 공개 도메인을 0.5초마다 찔러 보니 **약 13초** 동안
`/contests` 가 500 이거나 5초 넘게 응답하지 않았다(앞단이 502 를 내는 것이 아니라,
살아 있는 Next 가 백엔드에 닿지 못해 500 을 낸다). 그리고 그 실패는 **공개 앱의
`TypeError: fetch failed` 로 GlitchTip 에 오른다**(staging 74·prod 75 가 그렇게
되살아났다) — BFF 의 재시도(`a458d03`)가 덮는 시간보다 창이 길다. 즉 이 순서가 바꾼
것은 「반쯤 처리된 질의가 끊기는 것」과 오류가 오르는 자리이지, 사용자가 보는 실패의
길이가 아니다.

**헬스 체크는 Host 헤더를 붙여야 한다.** 루프백으로 치면 Host 가 `127.0.0.1` 이
되는데 그건 `ALLOWED_HOSTS` 에 없어 Django 가 400 을 낸다 — gunicorn 이 멀쩡히
떠 있어도 배포가 실패로 끝난다(빌드 #5 가 세 이미지를 다 굽고 다섯 컨테이너를 다
띄운 뒤 그렇게 죽었다). 스크립트는 `DJANGO_ALLOWED_HOSTS` 의 첫 항목을 쓴다 —
`events` 의 `/api/health` 확인도 같은 규약을 따른다(URLconf 가 `backend` 와
완전히 같은 코드다).

**Jenkins 는 staging 배포 호스트에 있다 — 개발 머신이 아니다.** 아래 `docker exec
jenkins` 와 `/server/jenkins/...` 는 그 호스트에서만 유효하다(개발 머신에서 치면
컨테이너도 경로도 없다).

Jenkins 컨테이너는 호스트 docker 소켓을 물고 root 로 돈다. 빌드 로그는
`docker exec jenkins sh -c 'tail /var/jenkins_home/jobs/laurio/builds/<N>/log'`.
워크스페이스는 컨테이너의 `/var/jenkins_home/workspace/laurio` 이자 호스트의
`/server/jenkins/workspace/laurio` 다 — **경로가 다르므로** compose 에 상대경로
바인드 마운트를 넣으면 호스트 데몬이 엉뚱한 곳을 본다. 지금은 named volume 뿐이다.

**마이그레이션이 앱마다 단일 initial 로 다시 만들어졌다**(#364, 부모 #358).
예전에는 `appeals` 하나만 그랬지만(#44), 과제를 걷으며 **열일곱 앱 전부**를 같은
모양으로 정리했다 — prod 는 한 번도 배포된 적이 없고 staging 은 DB 를 통째로 다시
만들었으므로 잃을 이력이 없었다. 106개 파일이 27개가 됐다(순환 참조가 있는 앱은
Django 가 둘로 가른다).

**그래서 옛 마이그레이션을 이미 적용한 DB 는 못 쓴다.** Django 는 그 DB 를 "적용
완료" 로 보고 조용히 지나가고, 테이블이 없다는 오류가 한참 뒤 런타임에 난다.
그런 DB 가 있다면 볼륨째 다시 만든다:

```bash
docker compose -f docker/compose.dev.yaml down -v
docker compose -f docker/compose.dev.yaml up -d
```

**Celery 는 dev 기본 기동에 없다**(#40). beat 가 60초마다 쏘는 스캔이 마감 전이·채점·
배분·환불을 실제로 진행시켜, e2e 가 심은 데이터를 테스트 도중에 다른 상태로
옮겨버리기 때문이다. 스캔 경로를 돌려보고 싶을 때만 프로필로 켠다:

```bash
docker compose -f docker/compose.dev.yaml --profile celery up -d
```

**공모전 검색의 실물 어댑터(OpenSearch, #450, 부모 #444 스펙)도 dev 기본 기동에
없다.** `SEARCH_ADAPTER_MODE` 기본값은 fake(DB 포함 검색, `contests.search.
FakeContestSearchAdapter`)라 실물 없이도 `/api/contests?q=...`가 그대로 돈다 —
`search` 프로필은 실물 어댑터(nori 한국어 분석기, `docker/search.Dockerfile`)를
직접 확인하고 싶을 때만 켠다:

```bash
docker compose -f docker/compose.dev.yaml --profile search up -d
SEARCH_ADAPTER_MODE=contests.search_opensearch.OpenSearchContestSearch \
  OPENSEARCH_URL=http://127.0.0.1:${CODEMIT_SEARCH_PORT:-19200} \
  uv run python manage.py rebuild_contest_search_index
```

단일 노드·JVM 힙 1GB·컨테이너 메모리 한도 2GB(`mem_limit`)이고 보안 플러그인은
끈다. **호스트의 `vm.max_map_count`가 262144 이상이어야 뜬다**(OpenSearch
공식 권장값, 커널 전역이라 컨테이너 안에서 올릴 수 없다) — `sysctl
vm.max_map_count`로 먼저 확인한다. `tests/test_contest_search_opensearch_live.py`
(`@live_vendor`, `OPENSEARCH_URL`이 있을 때만 돈다, CI는 건너뛴다)가 이 실물
어댑터를 실제로 친다 — 한국어 조사가 달라도 찾아지는지, 제목 가중이 설명보다
높은지, 재색인(`rebuild`) 중에도 검색이 끊기지 않는지(별칭 원자적 교체) 확인한다.

**Postgres 앞 연결 풀러(pgbouncer, #453/#457)도 dev 기본 기동에 없다** — search 와
같은 관용구로 프로필 뒤에 둔다. dev 의 backend·celery·events 는 이 프로필을 켜도
기본으로는 여전히 `db` 를 직접 가리킨다(POSTGRES_HOST=db) — 이 프로필은 "풀러
뒤에서 Django 가 무엇이 되고 안 되는가"를 직접 확인하는 자리이지, dev 의 기본
접속 경로를 바꾸는 것이 아니다(배포에 실제로 앞에 두는 것은 #458 의 몫이다):

```bash
docker compose -f docker/compose.dev.yaml --profile pgbouncer up -d
```

**풀 모드는 트랜잭션이다**(`docker/pgbouncer/docker-entrypoint.sh` — `[databases]`
는 `*` 와일드카드라 요청한 dbname 을 그대로 실제 Postgres 로 넘긴다, 인증은
`auth_type = plain` 이고 뒷단 자격증명은 `POSTGRES_USER`/`POSTGRES_PASSWORD`
그대로다). 트랜잭션 모드에서 실제로 재현해 확인한 것 — **서버측(named)
커서가 깨진다**: `QuerySet.iterator()` 를 그대로 돌리면 트랜잭션이 끝나는
순간 커서가 물려 있던 물리 연결이 다른 클라이언트에게 넘어가
`ProgrammingError: portal "_django_curs_..." does not exist` 로 죽는다.
`config/settings.py` 의 `DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"]`
(환경변수 `CODEMIT_DB_DISABLE_SERVER_SIDE_CURSORS`, dev 기본은 풀러가 없으므로
`false`)를 `true` 로 켜면 같은 코드가 통과한다 — 켠 채로도 재현해 확인했다.
준비된 문장(prepared statement)은 Django 가 psycopg3 백엔드에서 이미 기본으로
끄고 있어(연결 풀러 호환을 위해서라고 Django 자신의 주석이 밝힌다) 따로 손댈
것이 없다. `server_reset_query_always = 1`(entrypoint 의 `DISCARD ALL`)은
pgbouncer 문서가 트랜잭션 모드의 표준값으로 권하는 것을 그대로 따른 것이고
(임시 테이블·세션 SET 이 다음 클라이언트에 새는 것을 막는다), 직접 재현해
확인한 것은 위 커서 하나뿐이다. `tests/test_pgbouncer_live.py`
(`@live_vendor`, `CODEMIT_PGBOUNCER_PORT` 가 있을 때만 돈다, CI 는 건너뛴다)가
이 풀러를 거쳐 실제로 마이그레이션(일회용 DB 를 새로 만들어 처음부터
DDL 을 낸다)·쓰기·읽기가 되는 것을 확인한다.

## 운영

**Django admin 은 없다**(#46, ADR-0019). `/admin/` 은 마운트되지 않고 각 앱의
`admin.py` 도 없다 — admin 은 모델 행을 직접 편집할 수 있어서, `Appeal`·
`AppealRuling` 을 그 화면에서 고칠 수 있는 한 감사 추적에 우회로가 남는다.

사람이 판단하는 행위는 `/api/operator/*` 로만 한다. 그 API 에는 이제 화면이 있다
(`operator/`, #63) — 이의 심판·지급·정책·산출물 종류·카테고리(#231)·무료 공모전
개최 권한(#414, ADR-0048)·운영자 계정이 각각 한 화면씩이다. 화면이 없는 조작만
운영자가 HTTP 로 직접 친다.

개발 중 데이터를 훑던 수단도 함께 사라졌다. 대신 이렇게 한다:

```bash
cd backend && uv run python manage.py shell      # ORM 으로 조회
docker compose -f docker/compose.dev.yaml exec db psql -U codemit -d codemit
```

**DB 는 매일 새벽 2시(서울) 오브젝트 스토리지로 백업된다.** beat 의 `backup:database` 가
워커에서 `pg_dump --format=custom` 을 돌려 비공개 버킷 `db-backups/YYYY/MM/DD/` 에 올리고,
14일(`DB_BACKUP_RETENTION_DAYS`)이 지난 것은 지운다(`core/backups.py`). 스캔 등록부 밖에서
**손으로 쓰는 beat 항목은 `config/celery.py` 의 `SCHEDULED_JOBS` 한 자리뿐이다.** DB 가
`postgres:17` 이라 pg_dump 도 17 이어야 해서 backend 이미지가 PGDG 에서 `postgresql-client-17` 을
설치한다 — 서버 메이저를 올리면 이 줄도 같이 올린다. **Celery 가 없는 dev 기본 스택에서는 돌지
않는다.** 복원은 이렇게 한다:

```bash
pg_restore --clean --if-exists --no-owner -h <host> -U codemit -d codemit codemit-YYYYMMDD-HHMMSS.dump
```

첫 Operator 는 관리 명령으로 만든다 — 계정 관리 화면이 없기 때문이다.
`createsuperuser` 는 쓰지 않는다(Operator 와 참가자가 서로소라는 불변식을 모른다):

```bash
cd backend && uv run python manage.py create_operator <아이디> --superuser
```

**살아 있는지는 oracle 의 Prometheus 가 본다**(2026-09-21). 그 전에는 **prod 가 죽어도
아무도 몰랐다** — GlitchTip 은 오류가 **도착해야** 아는 장치라 프로세스가 죽거나 디스크가
차서 응답을 못 하면 조용하다. 감시 스택은 **이 저장소 밖**이다: oracle 의
`/server/prometheus`(별도 compose — Prometheus 30일·Grafana·node-exporter·cadvisor, sub2 같은
다른 호스트도 같이 보는 공용 스택)에 사람이 손으로 둔다. Jenkins·GlitchTip 과 같은 취급이다.

- **무엇을 보나**: blackbox 프로브 6개(prod·staging × 공개 앱 `/contests`·강의실 `/login`·
  운영자 앱) — `/contests` 는 서버 렌더링이 백엔드를 불러야 200 이라 **백엔드·DB 생존까지**
  본다. 호스트 지표는 세 호스트(oracle·sub·sub2)의 node-exporter, 컨테이너 재시작은 oracle
  의 cadvisor(**prod 만** — sub 는 CI 러너와 배포가 컨테이너를 늘 만들고 지워 재시작이
  정상이다).
- **언제 울리나**(`prometheus/alerts.yml`, 7개): 응답 없음 2분 · sub 호스트 다운 2분 ·
  루트 디스크 85%(경고)/95%(위험) · 가용 메모리 10% 미만 5분 · 스왑 90% 이상 · prod 컨테이너
  15분에 3회 재시작. prod 는 `critical`, staging 은 `warning` 이다.
- **어디로**: Alertmanager 가 **빌드 알림과 같은 Discord 채널**로 보낸다(채널을 늘리면 안
  보는 채널이 생긴다). 웹훅은 `alertmanager/discord_webhook`(chmod 600)에만 있고 설정
  파일에는 없다 — 바꾸려면 그 파일 한 줄을 고친다(재시작 불필요, 보낼 때마다 읽는다).
- **감시자가 prod 위에 있다는 사각지대**는 GlitchTip(sub) 의 uptime 모니터가 교차로 본다 —
  oracle 이 통째로 죽으면 Prometheus 도 같이 죽기 때문이다. 반대로 sub 가 죽으면 위
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
제한이 없어 sub 에는 이 저장소 밖의 컨테이너 로그가 319M·106M 쌓여 있었다. 두 배포
compose 의 서비스 11개 전부에 `x-logging`(20MB × 5개)을 걸었다 — **다음 배포의 컨테이너
교체부터** 적용된다. 두 호스트의 `/etc/docker/daemon.json` 에도 같은 기본값을 써 두었지만
**데몬이 다시 떠야 읽힌다** — 두 호스트 모두 `live-restore` 가 꺼져 있어 데몬 재시작이 곧
전 컨테이너 재시작이라 일부러 하지 않았다(다음 재부팅·도커 업그레이드 때 적용된다).
**prod 로그는 배포해도 남는다 — 30일**(2026-09-21). 컨테이너를 바꿔 끼우면 그 로그
파일도 지워지므로, 예전에는 배포 한 번이 사후 진단을 끊었다. 지금은 oracle 의 같은 감시
스택에 **Loki**(30일, 메모리 상한 1GB)와 수집기 **Alloy**(도커 소켓으로 `codemit-prod-*`
컨테이너만 따라간다)가 있어, 로그가 나오는 대로 Loki 로 간다. Grafana 의 Loki 데이터소스에서
`{service="backend"}`·`{container="codemit-prod-events-1"}` 처럼 찾는다(라벨은 `container`·
`service`·`env`). **staging 은 모으지 않는다** — sub 는 CI 러너와 배포가 컨테이너를 늘 만들고
지워 거기서는 `docker logs` 로 본다(그래서 staging 은 여전히 배포하면 이전 로그가 사라진다).

**배포 환경에서 Django 가 찍는 로그는 한 줄 JSON 이고, 요청마다 id 가 붙는다**(2026-09-21).
gunicorn 자신의 줄(워커 기동 등)과 Celery 자신의 줄은 각자 포맷 그대로다 — 그 둘은 Django 의
LOGGING 을 지나지 않는다.
`config/settings.py` 의 LOGGING 이 배포 여부(`IS_DEPLOYED_ENVIRONMENT`)로 포매터를 고른다 —
staging·prod 는 `core.json_logging.JsonFormatter`(`time`·`level`·`logger`·`message`·
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
- **gunicorn 워커 넷을 합산한다** — prod compose 가 backend 에만 `PROMETHEUS_MULTIPROC_DIR`
  를 주고 뜰 때마다 비우며, 죽은 워커 정리는 `config/gunicorn.conf.py` 의 `child_exit` 가
  한다(워커가 각자 카운터를 들면 긁을 때마다 무작위 워커 하나의 값이 와서 튄다). 워커 넷에
  40번 보낸 뒤 긁으면 세 번 모두 같은 합계가 나오는 것을 실측으로 확인했다. staging 은 긁지
  않으므로 그 설정이 없다.
- **라벨은 URL 패턴이다, 실제 경로가 아니다** — `resolver_match.route`(`api/contests/
  <int:contest_id>` 꼴)로 세고 맞지 않은 요청은 `unmatched` 하나로 모은다. 실제 경로를 쓰면
  공모전 수만큼 시계열이 생긴다.

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
  `SENTRY_DSN_CLASSROOM` 을 `.env.staging`/`.env.prod` 가 채운다(두 env 예시 파일에
  자리가 있다). 세 앱의 값은 `NEXT_PUBLIC_*` 로 **브라우저 번들에 굳으므로** 바꾸면
  이미지를 다시 굽는다 — `NEXT_PUBLIC_TOSS_CLIENT_KEY` 와 같은 제약이다. **브라우저 쪽
  값은 CI 가 저장소 변수 `STAGING_`/`PROD_SENTRY_DSN_<앱>` 으로 굽고, 서버 쪽 초기화가
  읽을 런타임 ENV 는 `.env` 줄에서 온다** — 둘을 같이 바꾼다(갈리면 브라우저와 서버가
  다른 곳에 보고한다).
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
  쿠키·요청 본문을 지우고 **헤더는 이름을 아는 것만 남긴다** — 새 헤더의 기본값이
  「보낸다」이면 다음 누출이 조용히 또 생기기 때문이다. 세 앱의 여섯 진입점이 전부
  `buildSentryOptions` 를 지나므로 그 한 자리가 서버·브라우저 양쪽을 덮고, 두 앱의
  `sentry-options.test.ts` 가 그 동작을 고정한다(운영자 앱은 테스트 파일이 없다). **의도한 4xx 도 보내지 않는다** — 422·404·
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
  `SENTRY_RELEASE` 로 내보내 compose 가 백엔드 환경변수로 넘기고, 세 앱은 CI 가 **그 앱
  이미지에 들어가는 코드를 마지막으로 바꾼 커밋**을 빌드 인자로 굽는다(HEAD 로 구우면 커밋마다
  Next 빌드 캐시가 깨졌다 — 이미지 태그는 여전히 HEAD sha 다).
  소스맵은 올리지 않는다(프론트 스택은 압축된 이름으로 보인다).
- **닿는지 확인하는 법**: 설정이 틀려도 조용히 아무 일도 안 일어나는 것이 오류 수집의
  기본 실패 모양이라, 배포 뒤 한 번 쏴 보고 GlitchTip 에서 눈으로 본다.

```bash
ssh sub 'docker exec codemit-staging-backend-1 python manage.py sentry_smoke'
```

**그 오류를 에이전트가 집어 진단한다**(2026-09-18). Orca automation 「GlitchTip prod 오류
진단」이 매분 `scripts/glitchtip_pick.py` 를 precheck 로 돌려 **prod 의 미해결·미클레임
오류 하나**를 고르고, 집힌 것이 있을 때만 이 머신에 세션을 띄운다(워크트리는 실행마다
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
  수 없다(`GET issues/{id}/comments/` 가 `Permission denied`, 실측). 그래서 **코멘트가
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
  환경 집합은 「prod 에서 난 적이 있는가」라, 처음 판은 staging 배포 창의 이벤트를 prod
  재발로 집었다(오류 74, 2026-09-22). 세션은 클레임 파일의 `regression_of`(지난 수정 커밋)를
  받아 **처음부터가 아니라 그 수정이 무엇을 놓쳤는지부터** 본다.
- **동시 하나는 잠금 파일이 지킨다**(`~/.codemit/glitchtip-lock`). 세션이 끝낼 때 지우고,
  죽었으면 45분에 저절로 풀린다. `orca automations runs` 의 status 값을 보지 않는 이유는
  그 문자열 목록이 어디에도 문서화돼 있지 않아서다 — 추측하면 가드가 **항상 통과하고도
  조용하다**.
- **환경 판정은 집합이다.** 같은 예외가 staging·prod 에서 함께 나면 GlitchTip 이 이슈
  하나로 묶고 태그에 두 값을 다 담는다(실측: issue 1). 「첫 값이 production 인가」로 보면
  순서에 따라 prod 오류가 조용히 빠진다.
- **우리가 일부러 던지는 예외는 집지 않는다.** `SentrySmokeError`(`manage.py
  sentry_smoke`)가 도착한 것은 **오류 수집이 닿는다는 성공 신호**다 — 그걸 집으면 세션
  하나가 「사고가 아니다」라고 스스로 적힌 예외를 재현하려 애쓴다. 판정은
  `metadata.type`(예외 클래스 이름)으로 한다, 제목 문자열이 아니다 — 그 메시지는
  한국어라 바뀌면 조용히 샌다. 목록은 `DELIBERATE_EXCEPTION_TYPES` 한 자리다.
- **해결 표시는 PR 병합이 한다**(2026-10-02). 세션은 커밋 메시지 마지막 줄에
  `GlitchTip: <id>` 를 적고 **분기를 push 해 PR 을 연다**(`main` 에 직접 넣지 않는다). Jenkins
  `codemit-pr` 가 시험을 돌려 초록이면 PR 을 `main` 에 병합하고, **곧바로 그 PR 범위**
  (`merge-base..HEAD`)의 줄을 읽어 이슈를 resolved 로 돌린다(`Jenkinsfile.pr` 의 병합 단계,
  자격증명 `glitchtip-automation-token`) — 「고친 것 같다」와 「고쳤다」를 가르는 자리다.
  범위가 PR 하나로 정확히 닫히므로 옛 방식의 두 문제가 없다: push 와 표시 사이의 5~10분
  공백(그래서 두던 `glitchtip-ack` 예고 코멘트)과, 연달아 push 할 때 취소된 실행이 범위를
  놓치던 것(오류 75 — 그래서 범위를 「직전에 그 잡이 성공한 실행 이후」로 잡았다,
  `glitchtip_resolve.py` 의 `auto` 모드가 그 흔적이다).
- **배경 세션은 「지금」을 말하는 문서를 고칠 수 없다.** 평소 티켓이라면 「티켓을 닫는
  기준」이 `CLAUDE.md`·`CONTEXT.md`·`docs/features/` 를 같은 커밋에서 고치라고 하는데,
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
  **(2)** 팁이 `origin/main` 과 같은 분기는 「아무것도 안 했다」로 보고 건드리지 않되
  `--lock-ttl-minutes`(기본 45분)보다 오래 식은 것만 걷는다(재현 실패로 커밋 없이 끝난
  워크트리가 영원히 남지 않게), **(3)** 머지 안 된 것은 그대로 남긴다 — 게이트에 걸려
  사람에게 넘긴 분기가 정확히 그 모양이다.
  사람 워크트리(`chain-*`·`int-*`)는 접두어가 달라 대상이 아니다. `--no-tidy` 로 끈다.
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

## 테스트

운영에서 Operator 세션은 실제 Redis 에 산다(#43, ADR-0018). **다만 테스트는 그렇지
않다** — 세션 캐시가 LocMem 이라 pytest 에는 `db` 하나면 된다(아래 「테스트는 서로를
밟지 않는다」). 인프라는 compose 가 주고 pytest 는 호스트에서 붙는 구조는 그대로다.

**HTTP가 유일한 시임이다.** 테스트는 마운트된 django-ninja API를 전체 요청 스택(URLconf +
미들웨어 + 라우터)을 통해 호출한다. 모델 메서드나 서비스 클래스를 직접 부르지 않고, 라우터를
직접 호출하는 `ninja.testing.TestClient`도 쓰지 않는다 — 미들웨어를 건너뛰기 때문이다.

시간은 시임이 아니라 주입 가능한 의존성이다(티켓 02, ADR-0003).

**`backend` pytest를 dev 컨테이너 안에서 돌리지 마라.** `docker compose -f
docker/compose.dev.yaml exec backend uv run pytest`(또는 컨테이너 안 셸에서 직접)로
돌리면 12건 안팎이 실패한다 — 회귀가 아니라 어댑터 불일치다. 테스트는
`STORAGE_BACKEND=fake`(기본값)를 기대하는데, dev compose의 backend 서비스는
`STORAGE_BACKEND=s3`로 실제 MinIO를 물려서 띄운다(업로드 e2e가 실물 스토리지를
쳐야 하기 때문 — FE-09, #34). 항상 호스트에서 돌린다:

```bash
scripts/test.sh backend tests/test_x.py   # 호스트에서 돈다 — 포트는 dev-env.sh 가 고른다
```

dev compose의 `db` 서비스는 호스트 포트로 이미 노출돼 있으므로 호스트의 `uv run
pytest`가 그 DB에 직접 붙는다 — 컨테이너를 거칠 이유가 없다.

**`seed_e2e_*` 관리 명령도 마찬가지다 — 호스트에서 돌린다.** 같은 어댑터 불일치이고,
증상이 훨씬 헷갈린다: 시드는 제출물 소스를 **Fake 스토리지**에 쓰는데 컨테이너의
backend 는 `STORAGE_BACKEND=s3` 로 MinIO 를 물고 있어, 채점 스캔이 그 소스를 못 찾아
(`source_not_found`) Score 를 남기지 않는다. 그러면 시드가 다음 줄에서
**「아직 채점되지 않은 Submission은 이의제기할 수 없습니다」**로 죽는다 — 스토리지
이야기는 어디에도 안 나온다. 실제로 이 오류를 스토리지가 아니라 채점 결함으로 한 번
쫓았다.

```bash
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py seed_e2e_operator_appeal
```

**`seed_demo_contests` 는 반대다 — 스토리지를 실물로 물려 돌린다**(#253). 이 시드는
제출물 소스를 스토리지에 **실제로 쓰고**, 그 뒤 컨테이너의 backend(=MinIO)가 그것을
읽어 채점한다. fake 로 돌리면 오브젝트가 명령과 함께 사라져 채점이 소스를 못 찾고,
결국 상한에 걸려 **「플랫폼이 채점하지 못했다」 0%** 만 남는다(ADR-0031) — staging 에서
데모 14건이 통째로 그 상태였다. 시드가 fake 를 감지하면 경고하지만, 처음부터 이렇게
돌린다:

```bash
cd backend && CODEMIT_DB_PORT=55432 \
  STORAGE_BACKEND=s3 STORAGE_BUCKET=codemit-dev \
  STORAGE_ENDPOINT_URL=http://127.0.0.1:19000 \
  STORAGE_PUBLIC_ENDPOINT_URL=http://127.0.0.1:19000 \
  STORAGE_ACCESS_KEY=codemit STORAGE_SECRET_KEY=codemit-secret STORAGE_REGION=us-east-1 \
  uv run python manage.py seed_demo_contests
```

**그리고 채점이 한 번 돈 뒤에는 다시 심을 수 없다.** `Score.submission` 이 PROTECT 라
데모 Contest 삭제가 `ProtectedError` 로 막히고, append-only 우회는 배포 환경에서
거부된다(#240) — 즉 staging 에서는 재시드가 통째로 불가능하다. 시드가 스스로 「멱등하다」고
적어 둔 계약이 그 지점에서 깨져 있다.

**강의실 데모는 `seed_demo_classroom` 이 심는다 — 그리고 이쪽은 다시 심을 수 있다.**
한 강사 계정에 화면의 갈래가 전부 보이는 한 벌을 만든다(진행중 클래스 둘·보관된 것
하나, 초안과 열린 문제, 내보내진 참여자, 시도가 쌓인 제출과 통과·미통과가 섞인 채점,
예산 경고 임계를 넘긴 상태, 공개된 문제·클래스 템플릿). 출력에 가입 링크와 템플릿
공유 코드가 나온다.

**알림도 심는다**(#341) — 강사에게 예산 경고, 참여자에게 시도마다 채점 완료.
채점을 실제로 돌리지 않아 스캔이 알림을 만들 기회가 없었던 자리를, `ClassroomScore`
를 만드는 그 자리마다 스캔(`classroom.scoring`)이 부르는 것과 같은 알림 함수를
불러 채운다 — 문구·링크(#329)가 스캔이 실제로 만드는 것과 같은 모양이 된다.

```bash
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py seed_demo_classroom --email <계정>
# staging 에서는
ssh sub 'docker exec codemit-staging-backend-1 python manage.py seed_demo_classroom --email <계정>'
```

**채점을 돌리지 않고 `ClassroomScore` 를 직접 만든다** — 데모를 심는 데 강사의 OpenAI
키를 태울 이유가 없고, 통과·미통과를 의도대로 배치해야 화면의 모든 갈래가 보인다.
같은 이유로 클래스에 키를 넣지 않는다. 제출은 **저장소 형식만** 심는다 — 소스 형식은
값이 스토리지 object_key 라 실제 오브젝트를 함께 써야 하고, 그러지 않으면 화면이 없는
파일을 가리킨다(#253 이 겪은 실패다).

**재시드가 되는 이유는 `ClassroomScore` 를 먼저 걷기 때문이다.** 위 공모전과 똑같이
`ClassroomScore.submission` 이 PROTECT 라 클래스를 그냥 지우면 막힌다. 이 명령은
`[데모]` 로 시작하는 **그 강사의** 클래스에 달린 Score 만 QuerySet 으로 먼저 지운다
(append-only 가드가 인스턴스 `delete()` 에만 걸려 있다). 범위가 그 접두어로 닫혀
있다는 것이 이 우회의 근거 전부이므로 그 필터를 넓히면 근거가 사라진다 — 실데이터의
Score 는 어떤 경로로도 닿지 않는다. `--purge-only` 로 걷어내기만 할 수도 있다.

**e2e 가 남긴 것이 dev 화면을 덮으면 걷어낸다**(#183). Contest 는 스위트 시작에 저절로
걷히지만(`global-setup.ts` 가 세 정리를 순서대로 부른다 — 실행 토큰별 큐, 네임스페이스별
Contest, 그리고 기준데이터), 스위트를 한동안 안 돌렸다면 손으로 한 번 부른다:

```bash
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py prune_e2e_junk
```

이름이 `e2e`·`[e2e` 로 시작하는 Category·DeliverableType 을 지우고 플랫폼 정책을 기준값
(모델 필드 기본값)으로 되돌린다. **정책 변경 이력은 남긴다** — 감사 추적이다(ADR-0023).
다만 e2e 종류에 달린 변경 이력은 그 종류와 **함께 지운다**:
`DeliverableTypeChange.deliverable_type` 이 PROTECT 라 그러지 않으면 종류를 지울 수 없고,
실측에서 e2e 종류 127개 중 108개가 그런 이력을 달고 있었다. 살아남은 Contest 가 참조 중인
것은 건너뛰고 이름을 stderr 로 알린다. 청소가 스위트를 빨갛게 만들면 「테스트가 깨졌다」와
구별되지 않으므로, `global-setup.ts` 도 이 정리만은 실패를 삼키고 경고만 남긴다.

실측으로 산출물 종류 132개(진짜는 5개)·카테고리 24개(진짜는 4개)가 쌓여 개최 화면의
요구형태 목록이 통째로 묻혔고, 플랫폼 수수료율이 e2e 가 남긴 324bps 라 dev 에서 확인한 실수령액이 실제 정책과 달랐다.

**Contest 를 먼저 걷어야 기준데이터가 풀린다** — `Contest.category` 가 PROTECT 라서다.
`global-setup.ts` 의 순서가 그래서 그 순서다.

**스위트는 기본으로 병렬 실행된다**(#104). `pyproject.toml` 의 `addopts` 가 `-n auto` 를
준다 — 실측(이 머신, 당시 1192건 — 지금 2482건 통과·1건 skip(요청 id·배포 JSON 로그·prod 지표를 더한 로깅·모니터링 4단계까지, 2026-09-21). Assignment 가 #205~#212 로
1312건에서 1377건까지, staging 검증이 낳은 #214~#217 로 1388건까지, 저장소만으로
제출하고 채점 시점에 박제하는 #218~#220 으로 1407건까지, 채점 상한과 화면 열한 개
(#213·#221~#231)로 1463건까지, 종류 게이트(#232)로 1467건까지, 공모전 이미지
(#233~#236)로 1512건까지, staging 걷기가 낳은 #237~#239 로 1514건까지, append-only
가드와 다운로드 파일명(#240·#241)으로 1524건까지, 알림 문구 분리와 제출 수정 진입
(#244·#245)으로, 채점 사유 청중 분리(#246)와 제출 화면의 「다음 행동」 단일화(#247)로,
제출 화면이 점수와 다음 갈래를 함께 보여주는 것(#248)으로, 신원 파기 뒤에도 제출물을
읽을 수 있게 하고 그 「다음 행동」에 재확인 상태를 접은 것(#250)·자동 0% 의 판정 주체
(#251)·데모 신원 시드(#252)·데모 제출물이 실제로 쓰이고 채점되게 한 것(#253)으로,
Contest 전이 그래프를 한 곳에 선언하고 선언 밖을 정적으로 막고 다이어그램을 낸 것
(#255~#257)으로, 업로드 용량·영상 보존·스크린샷 개수의 정책 필드 자리를 만든 것(#263)
으로 1603건까지, 그 바이트 상한을 presigned POST 서명 조건에 실제로 묶고(#261) ·
시연 영상을 보존 기간 뒤 파기하고(#262) · 스크린샷을 자료 종류로 세우고(#264) · 심사
비교와 공개 프로필이 영상·스크린샷을 실제로 열게 한 것(#265)으로, 옛 자료의 다운로드
확장자를 되돌리는 백필과 과제 소스 파일명에 제출자 이름을 붙인 것(#268 후속)으로
1640건까지, 앱 경계를 테스트로 세운 것(#269)으로 1659건까지, 제출물을 공통 부모와
공모전 자식으로 쪼갠 것(#270)으로 1661건까지, 공모전 제품 스위치(#271)로 1678건까지,
`classroom` 앱을 세우고 경계표에 등록한 것(#275)으로 1679건까지, Class·Problem·
체크리스트(#278·#282·#283)로 1699건까지, 강사의 OpenAI 키(#284)와 가입 링크
발급·재발급(#279)으로, 클래스·문제별 채점 모델(#285)과 링크로 회원가입과 클래스
가입이 한 번에 끝나는 것(#280)으로, 참여자 명단과 내보내기(#281)로 1740건까지,
제출 — 소스나 저장소를 내고 시도가 쌓이는 것(#286)으로 1753건까지, 제출 즉시
비동기로 채점되는 것(#287)으로 1763건까지, 통과 판정과 참여자의 문제 목록
(#288)으로 1772건까지, 강사가 제출물을 열어 보되 그 열람은 기록하지 않는 것
(#291, ADR-0040)으로, 클래스와 문제의 복사(#292·#293)로, 보관(#294)으로,
채점 토큰 예산 경고와 정지(#295)로 1831건까지, 가입 링크를 다시 열면 이름을
또 묻던 것을 고쳐 이미 참여자면(내보내진 사람 포함) 곧장 문제 목록으로
보내는 것(#300)으로, 문제 만들기 화면에서 체크리스트를 함께 받고 바로 여는
것(#315)으로, 문제 하나를 템플릿으로 공개하고 가져오는 것과 그 신고·모더레이션
(#316·#318·#320)으로, 클래스를 통째로 템플릿으로 공개하고 가져오는 것(#319)으로
1931건까지, 도달성 점검이 찾은 넷(#328~#331)으로 1959건까지, 강의실을 여섯 시선으로
걸어 찾은 결함·보충 아홉(#333~#341)으로 1985건까지, 화면이 역할에 맞게 말하게 한 것과
위험 표시·알림 분리(#332·#342~#345)로 1994건까지, staging 을 보통 사람의 감각으로
써 보고 찾은 다섯(#346~#350)으로 2000건까지
여기까지 늘었다. 그리고 처음으로 **줄었다** — 과제를 접으며(#358) 그 전용 테스트와, 마이그레이션을 앱마다 단일 initial 로 접으며(#364) 옛 마이그레이션을 직접 세우던 되감기 테스트 일곱 파일이 함께 빠졌다) `-n 4` 84초 → `-n auto` 57초.
직렬로 보려면 `-n 0`.

**시험 하나는 CPU 1초를 넘지 못한다**(2026-10-02). `tests/conftest.py` 가 시험 본문(call
단계)의 CPU 시간 — 자식 프로세스 몫 포함 — 을 재서 넘으면 실패로 바꾼다. 한도는
`CODEMIT_TEST_CPU_LIMIT`(로컬 기본 1.0, CI 의 `test` 잡은 1.5, 0 이면 끈다). 벽시계가
아니라 CPU 로 재는 이유는 붐비는 러너에서 한도 근처의 시험이 빌드마다 번갈아 떨어지지
않게 하려는 것이고, 준비(픽스처)는 재지 않는다 — 여러 시험이 같은 비싼 준비를 하면 모듈
픽스처로 옮긴다. 넘으면 **한도를 늘리지 않고 원인을 줄인다.** 처음 걸었을 때 340건이
넘었고 원인은 셋이었다:

- **비밀번호 해시** — 운영자 계정을 만들고 로그인할 때마다 PBKDF2 가 돌았다. 테스트에서만
  `MD5PasswordHasher` 를 쓴다(`config/settings.py` 의 `_RUNNING_TESTS` 블록). 이것 하나로
  340건 → 59건, 전체 106초 → 66초.
- **부팅 검사의 파이썬 기동** — `test_deployment_config.py` 가 시험마다 `manage.py check` 를
  새 파이썬으로 돌렸다. 지금은 설정과 무관한 모듈을 미리 읽어 둔 forkserver 의 자식이
  돌리고(`tests/boot_process.py`, 자식의 CPU 는 시험 몫으로 센다), 이 저장소가 등록한
  부팅 검사에만 붙인 태그(`core.adapters.BOOT_CHECK_TAG`)로 URLconf 적재를 건너뛴다.
- **필요보다 큰 데이터** — 배치 상한(50)을 보려고 공모전 53개를 개최하던 시험은 상한을
  2로 줄여 본다.

0.7~1.0초 사이에 일곱 개쯤 있다 — 새 시험이 그 근처면 같은 방법을 먼저 본다.

**테스트는 서로를 밟지 않는다 — 손으로 갈라 줄 것이 없다.**

예전에는 체인마다 `CODEMIT_TEST_DB_NAME` 과 `SESSION_REDIS_URL` 의 인덱스를 손으로 달리
줘야 했고, 잊으면 조용히 서로를 떨어뜨렸다(`DROP DATABASE ... is being accessed`, 그리고
남의 로그인 세션이 통째로 지워져 나오는 401 무더기 — 둘 다 코드 회귀와 구분되지 않는다).
지금은 둘 다 자동이다:

- **테스트 DB 이름**이 체크아웃 경로에서 파생된다(`config/settings.py` 의
  `_default_test_db_name`). `CODEMIT_TEST_DB_NAME` 을 주면 그 값이 이긴다.
- **세션 캐시가 테스트에서는 LocMem 이다**(같은 파일의 `_RUNNING_TESTS`). 프로세스별로
  갈리므로 워커 격리도 체인 격리도 공짜다.

**그래서 pytest 에 Redis 가 필요 없다** — `db` 하나만 띄우면 된다. 예전 문장(「Operator
세션은 실제 Redis 에 산다, 그래서 테스트에도 redis 가 필요하다」)은 더 이상 사실이 아니다.
ADR-0018 은 **운영**에서 세션이 Redis 에 산다고 정한 것이고, 실물 Redis 위의 세션 동작은
운영자 로그인 e2e 가 실물 스택으로 계속 덮는다.

```bash
scripts/test.sh backend tests/test_x.py   # db 하나만 띄우고(스크립트가 한다) 그 위에서 돈다
```

**앱 경계는 테스트가 지킨다**(#269, ADR-0037). `tests/test_app_boundaries.py` 가 백엔드
소스를 AST 로 훑어 앱 사이의 참조를 본다. 규칙이 둘이고 **강도가 다르다**:

- **강의실 ↮ 공모전 가족은 양방향으로 막힌다 — 예외가 없다.** 최상단이든 함수 안이든,
  `import` 든 Django 가 import 없이 앱을 묶는 길(`ForeignKey("contests.Contest")` 꼴
  문자열·`apps.get_model`)이든 걸린다. 표시로 열 수 있는 문이 하나라도 있으면 마감에
  몰린 사람이 그 문을 쓴다.
- **공유층**(`accounts`·`core`·`policies`·`storage`·`notifications`·`submissions`,
  #270 이 마지막을 더했다)**이 기능 앱을 부르면 막히되, 같은 줄이나 바로 앞 줄의
  `APP-BOUNDARY-EXCEPTION: <이유>` 로 열린다** — **이유가 비면 표시 자체가
  실패한다**(`scripts/check_screen_language.py` 와 같은 관용구). 지금 **25줄**이 나오는데
  그중 **9줄은 검사 파일 자신**(독스트링·정규식·오류 문구·합성 픽스처)이고 실제 표시는
  **16곳**이다(2026-09-20 확인, #465·#470). 시드·백필 관리 명령이 달던 예외 13곳은
  그 명령을 내용이 속한 공모전 가족 앱(`appeals`·`contests`)으로 옮기며 전부
  사라졌다 — 등록부(`core.e2e_seeds`)가 명령의 위치를 모르므로 이름은 그대로다.
  공모전 수명주기 알림(`notifications.lifecycle` → `contests.lifecycle_notifications`)도
  같은 이유로 옮겨 3곳이 사라졌다. 남은 16곳은 대부분 순환을 끊으려 일부러 함수
  안에 넣은 지연 import 라, 지우지 않고 사유를 적어 세어지게만 했다 — 탈퇴·휴면
  신원 파기는 이제 `verification.purge.purge_identity` 한 곳만 부르지만(#470),
  그 호출 자체도 공유층(`accounts`)이 기능 앱(`verification`)을 부르는 것이라
  표시는 남는다(`accounts/dormancy.py`·`accounts/withdrawal.py`).
  `grep -rn "APP-BOUNDARY-EXCEPTION" backend/` 로 나오는 숫자가 경계의 건강
  지표다 — 늘면 공유층이 기능으로 오염되는 중이라는 뜻이다. **그 grep 은 지금
  27줄인데 실제 표시는 위 16곳이다** — 나머지는 검사기 자신이 들고 있는 문자열
  (`tests/test_app_boundaries.py`)과 같은 관용구를 설명하는 문장이라, 세려면
  검사기와 문서를 뺀다.

**`INSTALLED_APPS` 에 앱을 더하면 그 표에 분류를 적기 전까지 빨갛다.** 한 방향으로만
그렇다 — 표는 아직 설치되지 않은 앱(`classroom`)을 미리 이름 지을 수 있다.

`scripts/` 의 스크립트가 아니라 테스트인 이유는 **로컬 게이트**다(아래 「티켓을 닫는
기준」) — `scripts/` 검사는 그 셋 중 어디에도 안 걸려 push 해야만 결과를 안다. import
경계는 쓰는 순간 막혀야 뜻이 있다. 새 CI 잡도 늘지 않는다: 기존 `test` 잡이 돌린다.

**그리고 이것이 실제 사고를 하나 막는다.** 호스트 pytest 의 기본 세션 URL 은 dev compose
가 노출한 **바로 그 Redis 의 같은 인덱스**였다. 즉 `uv run pytest` 한 번이 떠 있는 dev
환경의 운영자 세션과 조회 카운터를 통째로 지웠다(`RedisCache.clear()` 는 FLUSHDB 다).
LocMem 으로 바뀌면서 그 경로 자체가 사라졌다.

**빠뜨린 필드는 구조 테스트가 막는다**(#480, spec #474, `tests/
test_banned_word_field_registration.py`) — 사용자가 적는 이름·제목·본문에 금칙어
(사칭·욕설)를 거절하는 장치(`core.banned_words`)가 어느 필드에 적용되는지는
`core.banned_word_rules.RULES` 한 표가 든다. 이 구조 테스트가 백엔드 입력 스키마
(django-ninja `Schema`, 이름이 `In`으로 끝나는 관례 — `payload:` 타입 주석이 전부 이
접미사를 쓴다)를 `ninja.Schema.__subclasses__()`로 훑어 문자열·문자열 목록 필드를 전부
모으고 그 표와 대조한다. **등록되지 않은 필드가 있으면 빨갛다** — 앞으로 사용자 입력을
받는 새 필드를 더하면, 금칙어 검사를 어떻게 할지 정하기 전까지 이 테스트가 막는다.
앱 경계 테스트(`tests/test_app_boundaries.py`)와 같은 관용구를 쓴다: 아직 설치되지 않은
스키마는 표에 없어도 되지만(스캔 대상이 아니므로), 스캔되는 스키마가 표에 없으면
안 된다는 한 방향의 강제다. `test_no_stale_registrations`가 반대 방향(표에는 있는데
더는 스캔되지 않는 죽은 항목)도 잡는다.

**면제는 이유가 있어야 한다.** `BannedWordRule(checks_impersonation=False,
checks_profanity=False, exempt_reason="...")` 로 적는다 — 둘 다 거짓인데
`exempt_reason`이 비어 있으면 실패한다(`scripts/check_screen_language.py`의
`SCREEN-LANGUAGE-EXCEPTION`과 같은 관용구). 이유 없는 면제는 잊힌 누락과 구별되지
않기 때문이다. 검사를 거는 쪽(`checks_impersonation`·`checks_profanity` 중 하나라도
참)은 반대로 `exempt_reason`을 비워야 한다 — 검사와 면제 이유가 동시에 있으면 어느
쪽이 실제 동작인지 코드를 읽어야만 안다. 면제 사유는 크게 셋이다: **운영자 표면**
(운영자 공지·이의 심판 사유·정책/기준데이터 변경 사유 — 운영진이 진짜 운영진이라
사칭이 성립하지 않고, 신고된 표현을 그대로 인용해야 할 때가 있다), **당사자만 읽는
글**(이의제기 사유·템플릿 신고 사유 — 운영자만 읽고, 권리를 행사하는 길이라 낱말로
막을 자리가 아니다), **자유 텍스트가 아닌 것**(식별자·URL·object key·자격증명·벤더
웹훅 페이로드·정해진 값 집합 중 하나로 고정된 값 등).

**#480 이 이 표를 완성하며 실제로 빠진 검사 여덟 줄(네 자리)도 찾았다** — 면제를
적으려 훑다가 이미 검사하는 필드와 같은 범주(공개 이름·공개 본문)인데 어느 티켓에도
없던 자리였다: 클래스 템플릿을 가져올 때 새로 붙이는 이름, 채점 지침 `"custom"` 문장
(만들 때·고칠 때), 공모전 요구사항 문구(만들 때 인라인·따로 추가·수정), 개최자·개발자
공개 소개글(`bio`). 면제 대신 실제 검사를 걸었다 — `core.banned_word_rules` 모듈
docstring 과 `tests/test_banned_word_gap_fields.py` 가 경위와 HTTP 검증을 남긴다.

## 프론트엔드

Next.js + React. 저장소 루트가 pnpm 워크스페이스다(운영자 앱 04 #62, ADR-0021) —
락파일은 루트의 `pnpm-lock.yaml` 하나뿐이고, 공개 앱(`frontend/`, 위치·패키지 이름
변경 없음)·운영자 앱(`operator/`)·강의실 앱(`classroom/`, #276)·공유 패키지 셋이
그 멤버다 — `packages/bff-shared`(서버 쪽: 경로 순회 방어·Origin 검증·허용목록 검사
함수·백엔드 전달 기계. 허용목록의 **내용**은 앱마다 자기 파일에 남는다),
`packages/bff-client`(브라우저 쪽, #146: 인증 구역 호출의 클라이언트·`ApiResult`·
`normalizeDetail`·`useBackendQuery`/`usePagedList`·생성 타입 `schema.gen.ts` — **강의실도
이제 이 패키지를 쓴다**(#462). 손으로 다시 쓴 클라이언트(`lib/backend/client.ts`)와
그 사본이 낳던 결함 — 세션이 끊긴 사람을 로그인으로 보내는 동작이 강의실에만 없던
것 — 을 함께 걷어냈다. 강의실은 자기 로그인이 없으므로(ADR-0038) `revive`
없이 운영자 앱과 같은 모양으로 쓴다 — 401 이면 곧장 이 앱 자신의 `/login`
으로 보내고, 그 화면이 공개 앱 로그인으로 다시 돌려보낸다), 그리고
`packages/markdown`(설명 마크다운 렌더러, ADR-0047 — 2026-09-16
에 강의실에서 옮겼다: 강의실의 문제 설명과 공개 앱의 공모전 설명이 **같은 허용 목록
스키마와 같은 화면 조각**을 쓴다. 본문은 서버 컴포넌트가 그리고 복사·파일로 저장 버튼만
클라이언트 조각이라 공개 표면의 SSR 이 깨지지 않는다, ADR-0015). 테스트 전용
`packages/route-audit`(#166)도 멤버지만 화면 코드는 아니다. 명령은 그대로다 — 워크스페이스가 생겨도 `pnpm --dir <앱>` 호출법은
바뀌지 않는다.

테스트 시임은 **앱마다 하나**다(ADR-0021, ADR-0017 개정) — 앱이 셋(#276부터 강의실이
더해졌다)이어도 그 아래로 내려가는 컴포넌트 테스트·모킹은 없다. `docker compose -f
docker/compose.dev.yaml up` 으로 세 앱이 다 뜬 스택을 띄운 뒤 `pnpm --dir frontend test`
로 Playwright 가 프로젝트 셋으로 세 앱을 한 번에 친다(공개 앱 스펙은
`frontend/e2e/*.spec.ts`, 운영자 앱 스펙은 `frontend/e2e/operator/*.spec.ts`, 강의실
스펙은 `frontend/e2e/classroom/*.spec.ts` — `playwright.config.ts` 가 프로젝트마다 다른
`testDir`·`baseURL` 을 준다). `CODEMIT_E2E_BASE_URL`/`CODEMIT_OPERATOR_E2E_BASE_URL`/
`CODEMIT_CLASSROOM_E2E_BASE_URL` 로 각 프로젝트의 `baseURL` 을 바꿀 수 있다(기본값은 위
포트 표와 같다). `pnpm --dir frontend typecheck`/`pnpm --dir operator typecheck`/
`pnpm --dir classroom typecheck` 는 스택 없이 돈다.

**강의실은 자기 로그인을 갖지 않는다**(ADR-0038, #276) — 회원은 공개 앱과 공유한다.
그래서 강의실 e2e 스펙은 강의실에서 로그인하지 않는다: 부모 도메인 쿠키 공유는
dev(localhost, 포트로 앱을 가른다)에서 재현할 수 없고, 실제 공유는 staging에서만
검증된다(#277). 강의실의 인증 구역을 걷는 스펙(과 dev에서 눈으로 확인할 때)은 공개
앱에 로그인해 받은 `codemit_access`/`codemit_refresh` 쿠키 값을 강의실 오리진에 수동으로
심는다(`frontend/e2e/classroom/lib/cross-app-session.ts`, Playwright의
`context.addCookies`) — 실제 브라우저가 두 쿠키를 부모 도메인으로 공유하는 것을
로컬에서 흉내 내는 유일한 길이다. **그래서 `frontend-e2e-classroom` CI 잡은 강의실만이
아니라 공개 앱도 띄운다** — 빼면 그 헬퍼가 `ECONNREFUSED 127.0.0.1:53000` 으로 죽는다
(#318 이 그 스펙을 더한 뒤 main 에서 여섯 번 연속 그렇게 빨갛게 났다).

**운영자 앱은 인증의 모양이 다르다**(#63, ADR-0018/0019). 공개 앱은 쿠키의 JWT를
`Authorization` 헤더로 바꿔 달지만, 운영자 앱은 Django 세션 쿠키
(`codemit_operator_session`, `backend/config/settings.py`)를 이름으로만 골라
중계한다 — 브라우저의 Cookie 헤더를 통째로 넘기지 않는다. e2e 가 로그인할
Operator 계정은 `backend/accounts/management/commands/seed_e2e_operator.py`
(멱등)로 만든다 — 사람이 쓰는 `create_operator` 부트스트랩 명령과 달리 반복
실행에 안전하다.

**dev 컨테이너의 `backend` 도 바깥 체크아웃을 서빙한다.** 프론트에 대해서만 적혀
있던 함정인데 백엔드도 같다 — `docker/compose.dev.yaml` 이 저장소 전체를 마운트하므로,
워크트리에서 **새 API 라우트를 더하면 58000 번 백엔드에는 그 라우트가 없다.** e2e 가
404 를 받고, 원인은 코드가 아니라 어느 체크아웃을 쳤느냐다. 두 에이전트가 각자 시행
착오로 이걸 다시 발견했다. 워크트리 코드를 치려면 백엔드도 임시로 띄운다:

```bash
cd <worktree>
./scripts/dev-server.sh start backend        # 포트를 출력한다
CODEMIT_API_BASE_URL=http://127.0.0.1:<그 포트> ./scripts/dev-server.sh start front
CODEMIT_E2E_BASE_URL=http://127.0.0.1:<앱 포트> CODEMIT_E2E_NAMESPACE=c2 \
  pnpm exec playwright test --project=public
./scripts/dev-server.sh stop-all
```

`STORAGE_BACKEND=s3` 는 도구가 알아서 준다 — dev compose 의 backend 가 그렇게 뜨기
때문이다(업로드 e2e 가 실물 MinIO 를 쳐야 한다). 빼면 업로드 스펙만 갈린다.

**워크트리에서 일한다면 e2e 가 당신 코드를 치지 않는다.** `playwright.config.ts`
에 `webServer` 가 없는 것은 의도다(ADR-0021 — 테스트가 앱의 수명을 소유하지
않는다). 그 결과 compose 로 뜬 `frontend` 컨테이너는 **바깥 체크아웃**을 마운트해
서빙하므로, 격리된 워크트리에서 프론트를 고치고 e2e 를 돌리면 **고치기 전 코드가
통과한다.** 병렬 체인 둘이 각자 이 사실을 재발견했다.

워크트리 코드로 검증하려면 그 워크트리에서 임시 Next 서버를 띄우고 baseURL 을
그쪽으로 돌린다 — 백엔드는 이미 떠 있는 것을 그대로 쓴다:

**`scripts/dev-server.sh` 로 띄우고 걷는다 — 손으로 `&` 와 `kill %1` 을 쓰지 않는다**
(2026-09-20). 포트는 이 워크트리의 `dev-env.sh` 값 +10 으로 스스로 고르므로 compose
스택과도, 다른 워크트리와도 부딪히지 않는다.

```bash
cd <worktree>
./scripts/dev-server.sh start front          # baseURL 을 출력한다
CODEMIT_E2E_BASE_URL=http://127.0.0.1:<그 포트> pnpm exec playwright test --project=public
./scripts/dev-server.sh stop-all             # 끝나면 반드시
```

**옛 처방(`... &` 뒤에 `kill %1`)은 에이전트에게 성립하지 않는다.** 잡 테이블은 그
셸에만 있는데 에이전트는 **Bash 호출마다 새 셸**이라, 나중 호출의 `kill %1` 은
아무것도 죽이지 않는다 — 지켜질 수 없는 규칙이었다. 2026-09-20 에 병렬 체인 다섯이
그렇게 남긴 호스트 `next dev` **14개가 15.0 GiB** 를 먹어 RSS 25/26 GiB·스왑 8 GiB 중
88 KB 만 남았고, sshd 가 `Maxstartups` 로 연결을 버려 **SSH 로 들어갈 수 없었다**
(커널 OOM 은 `oom_score_adj` 가 높은 chrome 만 죽였을 뿐 원인은 안 건드렸다).

그래서 이 도구는 **PID 파일**로 관리한다 — 어느 셸에서든 걷을 수 있다. 그리고 죽일 때
**나무 전체를 죽인다**: `pnpm exec next dev` 는 자식으로 진짜 `next-server` 를 낳으므로
부모만 죽이면 메모리를 쥔 쪽이 그대로 남는다(실측으로 3단계까지 함께 죽는 것을
확인했다). 다른 명령도 있다 — `list`(이 머신에 뜬 것 전부, **이 도구 밖에서 뜬 것까지**
보여준다)·`reap`(워크트리가 사라진 고아를 걷는다, 5분마다 타이머가 부른다)·`stop <대상>`.

**주 워크트리에서는 안 뜬다 — 그게 맞다.** dev 컨테이너가 이 체크아웃에 root 로 `.next`
를 써 두어 호스트 `next dev` 가 `EACCES` 로 죽는데, 주 워크트리는 애초에 컨테이너가
서빙하므로 호스트에서 띄울 대상이 아니다. 도구가 그 경우를 알아보고 이유를 적는다.

**이 머신에는 그 위에 메모리 한도도 걸려 있다** — 자세한 값과 근거는 커밋되지 않는
`CLAUDE.local.md` 에 있다(사용자 슬라이스만 제한하고 docker 는 `system.slice` 라 밖이다).

**로컬 시험의 입구는 `scripts/test.sh` 하나다**(2026-10-02, web-rpg 의 `deploy/test.sh` 와
같은 방식). `scripts/test.sh backend [pytest 인자]` · `scripts/test.sh e2e [playwright 인자]`.

- **기계 전체에서 동시에 둘까지 돈다** — 셋째는 빈 칸을 기다린다(`/tmp/codemit-test-slots`
  의 flock, 워크트리가 달라도 같은 칸을 센다). 이 머신은 여러 에이전트와 다른 프로젝트가
  나눠 쓴다.
- **한 칸은 호스트 코어의 1/3 을 고정해 쓴다**(12코어면 4) — pytest·Playwright 는 `taskset`,
  e2e 스택 컨테이너는 `docker update --cpuset-cpus`. 몫 제한(`--cpus`)이 아니라 코어를 못
  박는다: 몫이 차면 0.1초씩 통째로 멈춰 시험이 흔들린다(web-rpg 실측).
- **한 번에 400개를 넘게 돌리지 않는다** — pytest 는 `tests/conftest.py` 가 수집 단계에서,
  e2e 는 스크립트가 `--list` 로 미리 세어 거절한다. `CI` 환경변수가 있으면(=CI) 제한이 없고,
  로컬에서 정말 필요하면 `CODEMIT_FULL_TESTS=1`.
- **전체 시험은 브랜치 PR 의 CI 로 본다** — 아래 「티켓을 닫는 기준」.
- **e2e 는 CI 와 같은 프로덕션 이미지 스택**(`compose.dev` + `compose.ci`)을 이 워크트리 전용
  이름(`<dev-env 프로젝트>-e2e`)으로 굽고 띄우고, 끝나면 지운다. 되풀이할 때는
  `CODEMIT_E2E_KEEP=1` 로 남기고, 다 쓰면 `scripts/test.sh e2e-down`. 일꾼은 코어 둘에 하나다.

**e2e 시험 하나는 3초 안에 끝나고, 재시도하지 않는다**(2026-10-02, `playwright.config.ts`
의 `timeout: 3_000`·`retries: 0`). 재시도가 흔들리는 시험을 초록으로 덮고 있었다 — 강의실
「죽은 세션」 시험이 CI 에서 30초 타임아웃으로 떨어졌다가 재시도로 통과한 것이 로그에만
남았다. **흔들리는 시험은 지우지 않고 원인을 고친다**(그 시험의 원인은 앞 화면의 주기 조회가
쿠키를 죽인 직후 스스로 로그인으로 이동해 시험의 다음 이동과 부딪힌 것이었다). 넘으면 한도를
늘리지 않고 줄인다 — 이번에 쓴 방법:

- **준비는 화면이 아니라 API 로** — 개최 폼을 화면으로 채우던 결제 시험은 초안을
  `e2e/lib/contests-api.ts` 로 깐다(폼 자체는 시험 하나가 화면으로 걷는다). 로그인
  도우미(`establishDeveloperSession`·`establishOperatorSession`)는 열 화면을 받는다 —
  목적지로 바로 가거나(`path`) 아무 화면도 열지 않는다(`null`).
- **긴 시험은 나누되 단언은 버리지 않는다** — 결제 「개최 → 공개」를 「폼 → 결제 화면」과
  「결제 화면 → 공개」로 나눴다.
- **사건을 놓치지 않게 먼저 기다린다** — 응답 대기는 화면을 열기 **전에** 건다(공모전
  이미지 시험이 응답을 놓치고 15초를 채우던 것이 CI 의 17초였다).
- **서버 쪽 비용** — dev·CI 는 빠른 비밀번호 해셔를 쓴다(운영자 시드 1.06 → 0.08초,
  로그인 0.55 → 0.23초; 배포는 PBKDF2 그대로, `config/settings.py`). dev·CI 의 Postgres 는
  `synchronous_commit=off`(시드 하나가 커밋 대기로 1.5초를 썼다). CI 의 e2e 백엔드는
  `runserver` 가 아니라 gunicorn 넷이다(`compose.ci.yaml`). CI 의 e2e 잡 셋은 한 호스트에서
  노드를 통째로 쓰므로 일꾼은 코어의 1/3 이다(`scripts/ci/e2e.sh` 의 `PLAYWRIGHT_WORKERS`).

**e2e 시드는 입구에서 줄을 선다**(2026-09-18, CI #242). Playwright 는 시드를 스펙 파일마다
`beforeAll` 에서 부르고 `fullyParallel` 로 워커 여럿을 쓰는데, 시드들은 「기존 e2e 데이터를
지우고 다시 만든다」 구조라 **순차로만** 멱등하다 — 둘이 같이 지우고 같이 넣으면 한쪽이
유일 제약에 걸려 죽는다(실측: 동시 2번이면 3/3 으로 한쪽이 500,
`auth_user_username_key` 의 `e2e-seed-sponsor`). `POST /api/internal/e2e/seed/{name}` 이
이름별 `pg_advisory_xact_lock` 을 잡아 그 창을 닫는다. 시드 하나가 0.25초라 워커 여섯이
줄을 서도 최악 1.5초이고 호출부의 하한은 30초다. 호출부를 하나씩 고치지 않고 입구에 둔
이유는 같은 경쟁이 시드마다 다른 제약으로 되살아나기 때문이다(스폰서·심사 스폰서·개발자·
기준데이터가 모두 같은 「지우고 넣기」 모양이다). **매번 새 행만 만드는 시드는 등록부가
줄에서 뺀다**(`SeedEntry.serialized=False`, 2026-10-02 — 이의 시드 셋이 0.4·1.0·1.2초로 줄을
서서 시험 하나 3초 한도를 넘었다).

**그 실패는 한 번 진단이 불가능했다.** `frontend/e2e/lib/seed-http.ts` 가 오류 본문을
400자에서 잘라 역추적의 머리만 남기고 정작 원인 줄(psycopg 예외 클래스와 `DETAIL:`)을
버렸다 — 지금은 4000자다. 내부 토큰 뒤의 표면이고 배포 환경에서는 아예 거부되므로 길게
실어도 잃을 것이 없다.


프론트엔드 티켓 하나에 한 시간씩 쓰던 이유의 절반이 테스트 대기였다(실측: 티켓당 평균
51분 중 대략 절반). 그래서 개발 중의 확인을 e2e 에서 **브라우저로** 옮긴다.

**개발 중에는 에이전트가 Playwright 로 유저스토리를 직접 걸어본다.** 코드를 쓰고, 실제
브라우저로 그 화면을 열어 사람이 걸을 경로를 그대로 걷고, 걸은 경로를 글로 요약해 보고한다
(`mcp__playwright__browser_*`). **모킹이 아니고 새 시임도 아니다** — ADR-0017/0021 이 정한
바로 그 시임(실행 중인 앱)을 자동화 대신 손으로 미는 것이다. 그 ADR 들은 시임의 **위치**를
정하지 「언제 돌리는가」를 정하지 않는다.

**e2e 스펙은 개발 중에 쓰지 않는다.** 티켓이 끝날 때 1~2개만 남긴다. 무엇을 남기는지는
아래 「남길 것」이 정한다. 새로 쓴 스펙은 그 파일만 `scripts/test.sh e2e <파일>` 로 한 번
돌려 3초 안에 드는지 보고, 나머지는 PR 의 CI 가 돌린다.

### 남길 것 — ADR-0017 의 세 위험 + 핵심 흐름

ADR-0017 은 프론트에만 있는 위험을 셋으로 못 박았다. 여기 해당하면 **반드시** 남긴다:

1. **공개 페이지가 실제로 서버 렌더링되는가** — JS 를 끈 HTML 에 백엔드 값이 있는가.
   페이지 하나에 `"use client"` 가 붙는 것만으로 조용히 깨진다.
2. **인증 구역이 실제로 막히는가** — 미들웨어 가드. 다만 이것은 `matcher` 하나에 걸린
   함수 하나라, **전용 스펙에서 한 번만** 본다. 화면마다 반복하지 않는다.
3. **프록시 허용목록과 Origin 검증이 실제로 막는가** — 뚫리면 ADR-0016 이 무효다.
   백엔드에 대응 테스트가 **없다**.

그 밖에는 **핵심 흐름**만 남긴다: **돈이 움직이거나 보안이 새는 곳**(결제·지급·이의
심판과 원장·탈퇴·소스 열람)과 **앱마다 유저스토리 한 벌**.

**나머지는 남기지 않는다.** 「로그인된 상태에서 화면이 서버 값을 어떻게 그리는가」는 대개
백엔드 테스트가 같은 사실을 이미 고정하고 있다 — 실제로 여러 스펙이 자기 주석에 「백엔드가
실물로 검증한다」고 적어 두고 같은 값을 다시 단언하고 있었다.

### 티켓을 닫는 기준

로컬 게이트는 셋이다 — **바꾼 자리의 백엔드 시험**(`scripts/test.sh backend <파일…>`,
400개까지), **세 앱 `typecheck`**, **에이전트가 브라우저로 걸어본 결과**. **전체 시험은
브랜치 PR 의 CI 로 본다**(2026-10-02) — 브랜치를 push 하고 `main` 으로 PR 을 연다. Jenkins
`codemit-pr` 가 초록이면 **그 PR 을 스스로 `main` 에 rebase 병합한다** — 사람이 머지 버튼을
누르지 않고, `main` 에 직접 push 하지 않는다(시험 없이 이미지가 구워져 staging 까지 간다).
병합을 막으려면 초안으로 열거나 `hold` 라벨을 붙인다. 다음 티켓을 시작하기 전에 PR 의 결과
(빌드·`codemit/automerge` 상태)와 이어지는 이미지·staging 배포를 확인해 보고한다.

**push 를 빠뜨리면 CI 는 아무것도 보지 않는다.** 실제로 그런 적이 있다 — 하루 작업 20커밋이
푸시되지 않은 채 쌓였고, 그 사이 CI 잡 하나가 21시간 빨간 것도 아무도 몰랐다. e2e 를 CI 에
맡기는 이상 push 와 결과 확인이 그 규율의 절반이다.

**그리고 이 티켓이 `CLAUDE.md`·`CONTEXT.md`·`docs/features/` 의 어떤 문장을 거짓으로
만들었는지 확인하고, 만들었으면 같은 커밋에서 고친다.** 그 셋만 「지금」을 말하기로
했으므로(아래 「어느 문서가 「지금」을 말하는가」) 그것이 낡으면 대신 참을 말해 줄 문서가
없다. 이 파일은 이미 한 번 거짓말한 적이 있다 — 「tick 을 쏘면 21일 시나리오를 몇 초에
재현할 수 있다」가 그랬고, 한참 뒤에야 커밋 하나로 고쳐졌다.

**셋의 분업이 있다.** `CLAUDE.md` 는 저장소를 어떻게 굴리는가, `CONTEXT.md` 는 낱말이 무슨
뜻인가, `docs/features/` 는 **서비스가 무엇을 하는가**다. 같은 사실을 두 곳에 적지 않는다 —
적으면 갈라지고, 갈라진 쪽을 읽은 사람이 틀린다. 무엇이 바뀌면 `docs/features/` 의 어디를
고쳐야 하는지는 그 디렉터리의 `README.md` 가 표로 들고 있고, 세는 일을 손으로 하지 않도록
명령도 함께 적혀 있다.

가장 잘 썩는 것은 **수치와 목록**이다 — 포트 표, 어댑터 목록, 채점 예산, 실측 시간, 테스트
건수, 그리고 `docs/features/` 의 엔드포인트·스캔·화면 목록. 그것을 바꾸는 티켓이면 그 표를
같이 고친다.

| 언제 | 무엇 | 실측 (이 머신, 2026-09-04) |
| --- | --- | --- |
| red→green 반복 | 백엔드 테스트 파일 하나 | **12초** |
| red→green 반복 | 브라우저로 화면 하나 걸어보기 | **수 초** |
| 티켓 커밋 직전 | 바꾼 자리의 `pytest` | 수 초 ~ 수십 초 |
| 티켓 커밋 직전 | 세 앱 `typecheck` | 각 10~20초 |
| 브랜치 PR 의 CI | 전체 | 백엔드 + e2e |

로컬에서 `pnpm --dir frontend test`(전체)를 돌리지 않는다 — 로컬 e2e 는 `scripts/test.sh
e2e` 로 파일·프로젝트를 좁혀 돌린다. 그 스크립트들은 CI 가 쓴다.

**이번엔 전부 이 머신에서 다시 쟀다** — 옛 표의 e2e 수치는 이전 머신(WSL) 것이었다.

```bash
scripts/test.sh backend tests/test_payouts.py -q
scripts/test.sh e2e --project=public e2e/payout.spec.ts -g "상금 그대로가"
```

안쪽 고리에서 전체를 돌리면 **한 번의 red→green 이 4초가 아니라 7분**이 된다. 슬라이스
하나에 그 왕복이 여러 번 있으니 티켓 하나가 통째로 테스트 대기에 잠긴다.

**CI 가 돌리는 것 (참고용 수치).**

```bash
pnpm --dir frontend test            # 전체 (102건이던 시절 약 1.8분 — 지금 132건)
pnpm --dir frontend test:public     # 공개 앱만 (74건이던 시절 약 1.4분 — 지금 89건)
pnpm --dir frontend test:operator   # 운영자 앱만 (28건이던 시절 약 25초 — 지금 31건)
pnpm --dir frontend test:classroom  # 강의실만 (6건이던 시절 CI 첫 실행 1.7초 — 지금 20건)
```

**로그인은 공개 앱 하나뿐이고, 끝나면 온 곳으로 돌려보낸다**(#297 후속). 강의실은
자기 로그인이 없어(ADR-0038) 사람을 공개 앱으로 보내는데, `next` 는 **같은 오리진
상대 경로만** 허용하므로(`frontend/lib/auth/next-path.ts`) 그것만으로는 돌아올 수
없다 — 실제로 로그인한 사람이 공모전 콘솔에 버려졌다.

**그 검사를 느슨하게 하지 않았다.** 대신 오리진을 나르는 자리를 따로 뒀다:
`next_origin` 쿼리를 `frontend/lib/auth/sibling-origins.ts` 가 **설정에 적힌 우리
오리진 목록**(`CODEMIT_CLASSROOM_ORIGIN`)과 대조해 통과한 것만 OAuth 왕복 쿠키에
싣고, 콜백이 거기로 돌려보낸다. 사용자 입력이 고르는 것은 「이 목록 중 어느
것인가」뿐이다. 실패 경로(`oauth_unconfigured` 등)도 같은 값을 실어 보낸다 —
안 그러면 한 번 실패한 사람이 다시 성공해도 공개 앱에 남는다.

**`CODEMIT_CLASSROOM_ORIGIN` 은 공개 앱과 강의실이 같은 `.env` 줄을 나눠 읽는
값이다**(`CODEMIT_OPERATOR_ORIGIN` 과 같은 원칙). 어긋나면 복귀가 조용히 안 되고
사람은 공개 앱에 남는다 — fail-closed 라 보안 구멍은 아니지만 원인을 찾기 어렵다.

**런타임 설정을 읽는 화면은 정적으로 구워지면 안 된다**(#297). Next 는 `searchParams`·
`cookies`·`headers` 를 하나도 안 읽는 서버 컴포넌트를 **빌드 시점에 HTML 로 굽는다.**
그 화면이 `process.env` 를 읽으면 **빌드 머신의 값**(대개 비어 있음)이 박제되고, 폴백이
있으면 그 폴백이 배포에 그대로 나간다. 강의실 로그인 링크가 실제로 그렇게
`http://127.0.0.1:53000` 을 가리켰다(`x-nextjs-prerender: 1`, 1년 캐시).

**세 게이트가 전부 못 본다**: dev 는 매 요청 렌더라 안 보이고, CI e2e 는 그 스택에서
값이 비어 있어 **폴백이 「맞는 답」**이라 통과하고, deploy-guard 는 부팅 여부만 봤다.
프로덕션 이미지에 배포 설정을 물려야만 드러난다. 그래서 두 곳에서 잡는다 —
`classroom/lib/rendering/runtime-config.test.ts` 가 **구조**(런타임 환경변수에 닿는
page/route 는 `export const dynamic = "force-dynamic"` 을 선언해야 한다)를,
`classroom-deploy-guard` 잡이 **결과**(구운 이미지의 `/login` HTML 에 로컬호스트가
없는가)를 본다.

**강의실은 공개 앱과 같은 토큰·서체를 쓴다**(#298). `classroom/app/tokens.css` 는
`frontend/app/tokens.css` 의 **복사본**이고 Pretendard 파일도 그렇다. 공유 패키지로
빼지 않은 이유는 손으로 관리되는 목록 셋이 또 늘고 로컬 게이트가 그것을 못 보기
때문이다(#166). 대신 `classroom/lib/design/tokens.test.ts` 가 두 파일이 한 글자라도
갈리면 빨개진다 — 「복사했으니 언젠가 갈라진다」를 규율이 아니라 검사로 바꿨다.
**토큰이 같아도 화면이 그 밖의 이름을 부르면 갈라진다** — 그래서
`frontend/lib/ui/brand-guard.test.ts`(#370)가 세 앱과 `packages/markdown/src`(2026-09-16
— 두 앱의 설명 화면이 그 패키지로 옮겨 갔다)의 소스를 텍스트로 훑어 정의된 적
없는 색(`bg-accent` 등 — Tailwind 는 오류 없이 아무것도 안 만든다)과 토큰 반경을
우회하는 모서리(맨 `rounded`·`rounded-full`)를 막는다 — 예외는 알림 벨의 읽지 않은 수
배지 하나뿐이고(동그란 표식, 2026-09-13 결정) 그 목록이 검사 파일 안에 있다. 새 CI 잡이 아니라 공개 앱의
`test:unit` 에 얹혀 있다. 운영자 앱은 토큰 파일이 없어 사본 대조의 대상이 아니다.

**그 순수 함수 잡(`frontend-pure-unit-tests`)이 이제 다섯을 돈다** —
`packages/bff-shared`·`packages/markdown`·공개 앱·운영자 앱·강의실. 뒤의 둘이
2026-09-16 에 늘었다: 강의실의 `test:unit` 은 **CI 에서 한 번도 돌지 않고 있었고**
(그래서 위 토큰·로고 사본 대조와 런타임 설정 구조 검사가 실제로는 아무 문도 아니었다),
마크다운 허용 목록 검사도 강의실 안에 있던 동안 같은 처지였다.

**다크 테마도 이 토큰 파일 하나에만 산다**(#397, spec #396 「따뜻한 먹」). 여섯
색 각각이 `light-dark(라이트, 다크)`로 두 값을 갖고, 문서 루트(`<html>`)의
`color-scheme`이 어느 쪽을 쓸지 정한다 — `:root`의 기본값은 `light dark`(운영체제
설정을 그대로 따른다), `data-theme="light"`/`"dark"` 속성이 있으면(#398 토글이
붙인다) `color-scheme`도 그 값으로 고정돼 운영체제 설정을 덮는다. 컴포넌트는
`bg-paper`·`text-ink/60` 그대로 쓰고 테마별로 고치지 않는다 — 갈리는 자리가 이
파일 하나이려면 그래야 한다. Tailwind 의 `dark:` 변형도 같은 순서(명시 표시
우선, 없으면 시스템)를 따르게 `@custom-variant`로 재정의했지만, 실제로 그
변형을 쓰는 컴포넌트는 없다 — `frontend/lib/ui/brand-guard.test.ts`가 토큰 파일
밖의 `dark:` 를 막는다(로고의 옛 `dark:text-paper`가 다크 테마 없이 켜져 다크
기기에서 로고 획이 사라지게 한 것이 계기다, #396). `frontend/lib/design/
contrast.test.ts`가 두 테마 각각 여섯 조합(본문/바탕·본문/뜬 면·흐린 글자 60%/
뜬 면·주 버튼 글자/바탕·통과 초록/뜬 면·주의 빨강/뜬 면)의 WCAG AA(4.5:1) 대비를
`tokens.css`를 텍스트로 읽어 계산한다 — 색을 바꿔 대비가 모자라지면 이 테스트가
빨개진다.

**테마 토글은 헤더 알림 벨 옆의 쿠키 하나다**(#398, spec #396). 두 앱 헤더에
같은 모양의 `ThemeToggle`(비로그인 방문자에게도 보인다, `AccountMenu`처럼
세션을 확인하지 않는다)이 시스템·라이트·다크 세 상태를 고른다. 고른 값은
`codemit_theme` 쿠키 하나에 담기고, **로그인 쿠키와 같은 도메인 판정
함수**(`sessionCookieDomain`, `lib/auth/cookies.ts` — dev 는 빈 값(호스트
쿠키), 배포는 부모 도메인)를 그대로 써서 공개 앱·강의실이 공유한다(ADR-0038과
같은 원칙). 쓰기는 각 앱의 `app/api/theme/route.ts`(둘 다 `force-dynamic`,
`assertSameOrigin`만 지키고 인증은 요구하지 않는다)가 하고, 두 앱의
`app/layout.tsx`가 요청마다 이 쿠키를 읽어 문서 루트에 `data-theme`를 붙인
채 그린다 — 그래서 다크를 고른 뒤 새로고침·새 탭에서도 라이트가 비치지
않는다. 쿠키 해석(`parseThemePreference`)과 표시 결정(`themeAttribute`)은
두 앱의 `lib/theme/preference.ts`에 같은 모양의 순수 함수로 복사돼 있다(토큰·
쿠키 도우미와 같은 방식). **dev(localhost 포트 구분)에서는 교차 앱 쿠키
공유가 재현되지 않는다** — 로그인 쿠키와 같은 제약이라 같은 오리진 안에서의
유지만 확인했고, 교차 공유는 staging 확인 항목으로 남는다.

**문제 설명 에디터(Toast UI, 강의실만)도 같은 표시를 따른다**(#399). 이
라이브러리는 색을 CSS 변수가 아니라 `.toastui-editor-dark` 클래스로 켠다 —
그래서 `classroom/app/components/MarkdownEditor.tsx`가
`resolveEffectiveTheme`(`lib/theme/preference.ts`, #397 과 같은 순서)로 지금
다크인지 판정해 그 클래스를 에디터 컨테이너에 직접 붙였다 뗀다. 문서 루트
표시가 바뀌면 `lib/theme/theme-bus.ts`(알림 벨의 `read-bus.ts`와 같은
window 커스텀 이벤트 방식)로, 운영체제 설정이 바뀌면 `matchMedia`로 다시
판정한다. 색 자체(툴바·괘선·코드 블록·인용·표)는 여전히
`toastui-editor-overrides.css`의 토큰 변수(`var(--color-*)`)가 정한다 — 이
클래스는 라이브러리 안쪽(툴바 아이콘 스프라이트 등 클래스 없이는 못 바꾸는
자리)만 건드린다. 참여자가 보는 문제 설명(`ProblemDescription.tsx`)은 처음부터 토큰 색만 썼으므로 이 티켓에서 고칠 것이
없었다.

**로고도 토큰·서체와 같은 방식으로 복사한다**(#392, #391 「커밋 노드 C」). 원본은
`frontend/app/components/logo-mark.tsx`(SVG 심볼)와 그것을 그리는
`frontend/app/icon.tsx`·`frontend/app/apple-icon.tsx`(Next 아이콘 파일 컨벤션)다.
`classroom/app/`의 같은 세 파일은 복사본이고, `classroom/lib/design/logo-mark.test.ts`가
한 글자라도 갈리면 빨개진다. 운영자 앱은 아이콘만 있고(주의색 타일 — 탭에서 다른 두
앱과 구별하기 위해서다) 헤더 로고도 이 비교도 없다. **강의실 가드의 matcher 는 아이콘
경로(`/icon`·`/apple-icon`)도 인증 구역에서 뺀다**(`classroom/middleware.ts`) — 안 그러면
비로그인 탭이 아이콘을 요청할 때마다 `/login`으로 튕긴다.

**`test:classroom` 만 `--pass-with-no-tests` 를 붙인다.** 세 스크립트는 2단계다 —
`@exclusive` 아닌 것을 병렬로 돌리고, `@exclusive` 를 워커 하나로 다시 돈다. 그런데
강의실에는 아직 `@exclusive` 스펙이 없어 둘째 명령이 「No tests found」로 **exit 1**
한다(CI 가 실제로 그렇게 빨갛게 났다). 스크립트 모양은 그대로 두고 그 한 자리만
연다 — 나중에 강의실에 배타 스펙이 생기면 아무것도 안 고쳐도 돌아간다.

**293건이 102건이 됐다.** 남긴 기준은 위 「남길 것」이다. 지운 것의 대부분은 「로그인된
상태에서 화면이 서버 값을 어떻게 그리는가」였고, 그 사실들은 대개 백엔드 테스트가 이미
고정하고 있다 — 여러 스펙이 자기 주석에 「백엔드가 실물로 검증한다」고 적어 두고 같은 값을
다시 단언하고 있었다. 미들웨어 가드는 `matcher` 하나에 걸린 함수 하나인데 7개 스펙이 경로
문자열만 바꿔 같은 함수를 쳤다.

**그 대가를 알고 지웠다.** 지운 것들의 회귀는 이제 아무도 잡지 않는다 — 되돌리려면 git 에서
꺼낸다(이 커밋 이전). 화면 회귀가 실제로 문제가 되기 시작하면 그때 기준을 다시 연다.

**스위트를 연달아 돌렸다면 `frontend` 컨테이너를 재시작한다.** `next dev` 의 메모리가 회차마다
늘어(측정: 4.8GB → 6.3GB) 로그인 뒤 화면 이동이 5초를 넘기기 시작하고, 그러면 매 회차
무작위로 한두 건이 로그인 헬퍼의 `toHaveURL` 타임아웃으로 붉어진다 — 코드 회귀와 구분되지 않는
모양이다. `docker compose -f docker/compose.dev.yaml restart frontend` 한 번이면 그대로 초록으로
돌아온다(로그인 헬퍼의 단언은 15초로 잡아 뒀지만 근본 원인은 이쪽이다).

**메모리가 워커 수의 실제 상한이다.** 예전 머신(WSL, Docker VM 8GB)에서는 2워커에서도
`next dev` 컨테이너가 OOM 으로 죽어 절반이 `ERR_CONNECTION_REFUSED` 로 실패했고,
VM 을 24GB 로 올린 뒤에야 4워커가 성립했다 — 그때 실측이 공개 스위트 직렬 7.4분 →
4워커 4.4분(병렬 2.8분 + 배타 1.6분)이다. 지금 머신은 네이티브 리눅스 Docker(코어 12,
호스트 RAM 약 26GB)라 조절할 VM 크기가 없고, 컨테이너가 호스트 메모리를 그대로
나눠 쓴다. 기본값 `"50%"` 는 여기서 **6워커**라 검증된 4워커보다 높다 —
`PLAYWRIGHT_WORKERS` 로 바꾸고, 올리기 전에 `docker stats` 로 여유를 먼저 본다.

**우리 화면으로 돌아가는 리다이렉트는 상대 경로로 낸다.** 컨테이너 안의 Next 는
자기가 어떤 공개 주소로 불렸는지 모른다 — `new URL(request.url).origin` 이 리버스
프록시 뒤 standalone 모드에서 공개 도메인이 아니라 **바인드 주소**로 나온다.
카카오 로그인이 실제로 `https://0.0.0.0:3000/console` 로 튕겼다(로그인은 성공하는데
도착지가 존재하지 않아 사용자에게는 깨진 것으로 보인다). `lib/auth/redirect.ts` 의
`redirectToPath` 를 쓴다 — 상대 Location 은 브라우저가 자기가 친 주소 기준으로
풀어 언제나 맞는 오리진이 되고, 환경변수도 `X-Forwarded-*` 설정도 필요 없다.
`NextResponse.redirect()` 는 절대 URL 을 요구하므로 **외부로 나갈 때만** 쓴다
(카카오 authorize 등). dev 에서는 `request.url` 이 우연히 맞아 이 버그가 보이지
않는다 — e2e 가 Location 이 `/` 로 시작하는지를 직접 단언하는 이유다.

**워크스페이스 패키지를 새로 더하면 손으로 관리되는 목록들을 같이 고쳐야 한다.**
`pnpm-workspace.yaml` 은 글롭이라 저절로 잡지만, 그 아래는 멤버를 하나씩 적어 둔다 —
`docker/frontend.Dockerfile`·`docker/operator.Dockerfile`·`docker/classroom.Dockerfile`(#276)의
COPY(각각 base·dev·builder 셋)와 `docker/compose.dev.yaml` 의 **멤버별 `node_modules` 이름
있는 볼륨**(그 패키지를 쓰는 서비스마다 하나 + 볼륨 선언). **로컬 게이트는 둘 다 보지
않는다** — `typecheck` 는 호스트의 node_modules 를 쓰고, e2e 는 로컬에서 돌리지 않기
때문이다. #166 이 `packages/route-audit` 를 더하면서 정확히 이걸 빠뜨려 CI 가 4잡 빨갛게
났고, 증상이 둘로 갈려 원인이 하나로 안 보였다:

- **deploy-guard 둘** — 프로덕션 이미지의 builder 가 `Cannot find module '@codemit/route-audit'`
  로 죽는다. 앱 소스(`lib/routes/allowlist.ts`)가 그 패키지의 타입을 쓰는데 Dockerfile 이
  패키지를 복사하지 않았다. runner 스테이지는 `.next/standalone` 만 가져가므로 실행
  이미지에는 안 들어간다 — 그래도 builder 에는 있어야 한다.
- **e2e 둘** — 러너의 `pnpm install --frozen-lockfile` 이 `EACCES ... packages/route-audit/
  node_modules/.bin/tsc` 로 죽는다. 볼륨이 없으면 바인드 마운트가 그대로 남아, 컨테이너의
  `pnpm install` 이 **호스트 경로에 root 로** 쓴다. compose 의 그 볼륨 목록 옆 주석이 경고하는
  바로 그 상황이다.

**화면을 그리는 패키지라면 둘이 더 있다**(2026-09-16, `packages/markdown`):
각 `next.config.ts` 의 `transpilePackages`(빌드되지 않는 소스 패키지라 앱 코드처럼
컴파일돼야 한다)와 **Tailwind 의 스캔 경로**. 뒤쪽이 조용한 쪽이다 — Tailwind v4 는
`node_modules` 를 건너뛰므로 패키지가 부르는 유틸리티(`mt-5`·`list-disc`·`pt-9`)가
**오류 없이 아예 만들어지지 않는다**. 실제로 한 번 그렇게 났다: 제목이 전부 본문
크기, 목록에 글머리 점 없음, 코드블록 여백이 없어 버튼이 코드 위로 겹침. 그래서
`packages/markdown/markdown.css` 가 `@source "./src"` 로 자기 소스를 등록하고 두 앱의
`globals.css` 가 그 파일을 `@import` 한다 — 앱마다 경로를 적지 않는다.

재현은 CI 와 같은 명령으로 로컬에서 된다(스택 없이 몇 분):

```bash
docker build -f docker/frontend.Dockerfile --target runner -t x .   # deploy-guard 와 같은 것
docker build -f docker/operator.Dockerfile --target runner -t y .
```

**standalone 산출물에는 `public/` 이 들어가지 않는다 — Dockerfile 이 따로 옮긴다.**
`docker/frontend.Dockerfile` 의 runner 스테이지가 `COPY … /app/frontend/public` 한
줄로 옮기고, 그 줄이 없으면 `/kakao/...` 같은 정적 자산이 **배포에서만** 404 가
된다(2026-09-16, 카카오 로그인 버튼 이미지가 prod 에서 그렇게 깨졌다). dev 는 소스를
그대로 서빙하고 부팅 가드는 `/healthz` 만 보므로 세 게이트가 전부 못 본다 — 그래서
`frontend-deploy-guard` 잡이 구운 이미지에서 그 파일과 `/_next/image` 최적화 주소가
둘 다 200 인지 직접 확인한다(#297 의 「구운 이미지에만 드러나는 실패」와 같은 종류).
`operator/`·`classroom/` 에는 아직 `public/` 이 없다 — 생기면 같은 줄을 그 Dockerfile
에도 더한다.

**API 타입은 손으로 쓰지 않는다.** `packages/bff-client/src/schema.gen.ts` 는
`pnpm --dir frontend generate:api`(`packages/bff-client/scripts/generate-api-types.mjs`)가
백엔드의 OpenAPI 스키마에서 생성해 커밋한 산출물이다. 이 명령은 **스택이 필요
없다** — `uv run python manage.py export_openapi_schema`(DB 접속 없이 등록된
라우터·스키마만 읽는다, `backend/core/management/commands/
export_openapi_schema.py`)로 스키마를 뽑은 뒤 `openapi-typescript` 로 변환한다.
`uv sync` 만 된 신선한 체크아웃에서 바로 돈다 — CI의 `frontend-openapi-types` 잡이
컨테이너를 기다리지 않고 이 명령을 그대로 돌려 `git diff`로 최신성을 확인하는
이유다. 백엔드 스키마가 바뀌었는데 재생성을 안 하면(혹은 재생성해도 필드가
없어졌는데 호출부를 안 고치면) `tsc --noEmit` 이 빌드타임에 잡는다.

## 커밋 훅

**백엔드를 고치고 타입 재생성을 잊으면, 예전에는 push 하고 6분 뒤 CI 에서야
알았다**(#272). 지금은 `.githooks/pre-commit` 이 저장소에 커밋되어 있고, 루트
`package.json` 의 `postinstall` 이 `git config core.hooksPath .githooks` 한
줄로 그것을 건다 — `pnpm install` 이 이미 Orca 셋업 훅이자 Dockerfile 단계라
저절로 깔린다. **`.git` 이 없는 환경(Docker 빌드 단계)에서는 그 한 줄이
`|| true` 로 실패를 삼킨다** — 이미지를 굽는 데는 훅이 필요 없다.
`core.hooksPath` 가 **상대 경로**라 워크트리마다 자기 디렉터리 기준으로
풀리므로 워크트리는 손댈 것 없이 공짜로 따라온다.

훅이 매 커밋 하는 일 셋:

- **배경 진단 세션이면**(브랜치가 `auto-` 로 시작하거나 `CODEMIT_UNATTENDED=1`)
  `CLAUDE.md`·`CONTEXT.md`·`docs/features/`·`docs/adr/` 가 staged 된 커밋을 **거절한다**
  (2026-09-18) — 위 「그 오류를 에이전트가 집어 진단한다」의 게이트다. 사람이 쓰는
  브랜치(`main`·`chain-*`·`int-*`)는 영향을 받지 않는다.

- `backend/**/*.py` 가 **staged 일 때만** `pnpm --dir frontend generate:api`
  를 돌려 `packages/bff-client/src/schema.gen.ts` 를 재생성하고, 바뀌었으면
  자동으로 같이 스테이징한다(생성물이라 사람이 리뷰할 것이 없다) — 문서만
  고친 커밋은 이 2.1초를 안 낸다. 재생성 명령이 실패하면 커밋을 거절한다.
- **항상** `check_adr_status.py`·`check_screen_language.py`·
  `check_backend_error_language.py` 세 문서 검사를 돈다(합쳐 0.35초) — 하나라도
  걸리면 커밋을 거절한다.

**`git commit --no-verify` 로 넘어갈 수 있다** — 훅은 피드백을 6분에서 몇
초로 당기는 장치일 뿐 문이 아니다. `frontend-openapi-types`·`adr-status`·
`screen-language` CI 잡은 그대로 진짜 문이고, 이 훅이 그것들을 대체하지
않는다 — 셋 다 지우지 않았다. 훅 프레임워크(husky·lefthook 등)는 쓰지
않는다, 셸 스크립트 하나면 되는 일에 의존성을 더할 값이 없다.

## 어느 문서가 「지금」을 말하는가

**이 파일과 `CONTEXT.md`, 그리고 `docs/features/` 셋뿐이다.** 나머지 문서는 전부 **그때의
판단**이다.

| | 무엇을 말하는가 | 시제 |
| --- | --- | --- |
| `CLAUDE.md` | 지금 이 저장소가 어떻게 돌아가는가 — 사실 | 현재 |
| `CONTEXT.md` | 지금 이 도메인을 어떻게 부르는가 — 언어 | 현재 |
| `docs/features/` | 지금 이 서비스가 무엇을 하는가 — 기능 | 현재 |
| `docs/adr/` | 그때 무엇을 왜 정했는가 | 그 시점 |
| `docs/design/` | 그때 화면을 어떻게 그리기로 했는가 — 시안 | 그 시점 |
| `REQUEST.md` | 애초에 무엇을 만들자고 했는가 | 2026-08 |
| 닫힌 이슈·스펙 | 그때 무엇이 문제였고 무엇을 했는가 | 그 시점 |

**이걸 지키지 않아 실제로 사고가 났다.** 어떤 세션이 `#49`(staging 실물 연동 스펙)의
Problem Statement 를 읽고 「어댑터 실제 구현은 스토리지 하나뿐이다」를 현재 상태로 사용자에게
말했다. 그건 그 스펙을 **쓰던 시점**의 문제 진술이었고, 그 사이 어댑터 10종이 전부 실물로
붙어 있었다. 사용자가 화를 냈고 그럴 만했다.

**그래서 이렇게 읽는다:**

- ADR 은 **Status 줄**이 자기 위상을 말한다 — `Accepted` · `Amended by ADR-XXXX`(여전히
  유효하되 뒤 ADR 이 그 위에 얹혔다) · `Superseded by ADR-XXXX`(더 이상 유효하지 않다).
  **모든 ADR 에 있다** — 없으면 CI 의 `adr-status` 잡이 막는다. 그래야 「표시가 없다」가
  「아무도 안 고쳤다」가 아니라는 것이 성립한다.
- **이슈·스펙 본문의 현재형 서술을 현재 상태로 인용하지 않는다.** 그 문장은 그것이 쓰인
  날의 사실이다. 지금이 궁금하면 이 파일과 설정 파일·코드를 본다.
- 새 ADR 에는 Status 줄을 붙인다. ADR 템플릿은 이 저장소가 아니라 플러그인 스킬 안에
  있어 저장소가 모양을 강제할 다른 수단이 없다 — CI 검사가 유일한 문이다.

**코드 주석도 같은 규율을 받는다.** 자기 코드를 설명하는 주석은 지금처럼 두껍게 쓴다 —
그게 이 저장소의 자산이다. 다만 **다른 시스템의 상태를 서술할 때는 티켓 번호로 시점을
박는다.** `seed.ts` 의 「예전에는 `uv run` 서브프로세스였다(#156)」는 안 낡았고, CI
워크플로의 「호스트의 uv 는 e2e 시드가 쓴다」는 #156 이후 거짓인 채로 남아 진단을 한 번
어긋나게 했다. 차이는 시점을 박았느냐 하나다.

## 물어볼 때는 AskUserQuestion 으로, 선택지를 갖춰서

**작업이 끝났을 때와 사용자에게 물어야 할 때는 `AskUserQuestion` 으로 다음 선택지를 제시한다.**
산문 끝에 「어떻게 할까요?」를 붙이지 않는다 — 그러면 사용자가 선택지를 스스로 만들어야 하고,
그건 맥락을 방금 다 읽은 쪽이 할 일이다.

지켜야 할 모양:

- **권장안을 첫 번째에 두고 라벨에 `(권장)` 을 붙인다.** 권장이 없으면 그건 아직 판단을
  덜 한 것이다. 고르기 어려우면 왜 어려운지를 `description` 에 적는다.
- **각 선택지의 `description` 은 「고르면 무슨 일이 일어나는가」를 말한다** — 라벨을 고쳐 쓴
  문장이 아니라 대가와 결과다. 되돌릴 수 없는 것은 그렇다고 적는다.
- **답이 달라져야 다음 행동이 달라지는 것만 묻는다.** 관례적 기본값이 있거나 코드를 읽어
  확인할 수 있는 것은 묻지 말고 정하고 진행하면서 무엇을 골랐는지 말한다.
- **한 번에 최대 넷.** 서로 독립적인 결정이면 한 호출에 함께 담는다.

작업이 끝났을 때도 같다 — 무엇을 했는지 보고한 **뒤에** 다음 갈래를 선택지로 낸다. 열린
티켓, 막힌 것을 푸는 사람 작업, 이어서 할 만한 것이 그 후보다. 남은 일이 정말 없으면 묻지
않는다(없는 선택지를 지어내지 않는다).

**예외 둘.** 서브에이전트는 묻지 않는다 — 배경에서 도는 에이전트가 질문을 띄우면 병렬 실행이
통째로 멈춘다(`dispatch-tickets` 가 이미 금지한다). 그리고 되돌릴 수 없거나 바깥으로 나가는
행위는 선택지가 아니라 **확인**이 먼저다.

## CI 는 Jenkins 에서 돈다 — 브랜치마다, 노드를 통째로

**시험은 Jenkins `codemit-pr`(Multibranch, `Jenkinsfile.pr`)가 돌린다**(2026-10-02). GitHub
소스 `sandcorporation/laurio` 의 브랜치(`main`·`staging`·`production` 은 뺀다)마다 하위 잡이
생기고, 5분마다 훑어 새 push 를 찾는다. 결과는 GitHub 커밋 상태로 남는다. 같은 브랜치에 새로
push 하면 옛 빌드를 끊는다.

| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 변경 | sub(`laurio-staging`) | `scripts/ci/changed.sh` — 문서(`.md`·`docs/`)만 바뀌었으면 시험을 건너뛰고 문서 검사만 |
| 시험(병렬) | sub | `scripts/ci/sub-checks.sh` — Django `check`·`check --deploy`, pytest 전체(junit), 생성물 최신성 둘, ADR·화면 언어 검사, 단위 시험 여섯, 세 앱 typecheck |
| | macos | `scripts/ci/e2e.sh`(세 앱 프로덕션 이미지 스택 + 세 프로젝트) → `scripts/ci/celery-broker.sh` |
| 병합 | sub | 초록이면 열린 PR 을 `main` 에 rebase 병합(`automerge.py`, 상태 `codemit/automerge`) → 그 범위의 `GlitchTip:` 줄 해결 표시 |

- **노드는 실행기가 하나라 통째로 쓴다.** 예전에는 GitHub Actions 의 셀프호스티드 러너
  셋(sub)이 sub 의 코어를 제한 없이 나눠 써, 이미지 빌드와 겹친 시험이 경합만으로 한도를
  넘었다(#499 의 첫 CI — 공개 e2e 10건·단위 2건 타임아웃). 오래 걸리는 e2e 를 성능이 좋은
  macos 에, 짧은 것을 staging 배포와 실행기를 나눠 쓰는 sub 에 둔다.
- **sub 의 Jenkins 는 컨테이너라 node·pnpm·uv 가 없다** — 그래서 sub 쪽은 저장소를 담은
  시험 이미지(`docker/ci.Dockerfile`)를 굽고 사이드카 postgres(tmpfs·fsync 끔)와 같은 망에서
  `scripts/ci/sub-checks-inside.sh` 를 돈다. 바인드 마운트는 쓰지 않는다(컨테이너와 호스트의
  경로가 다르다, 아래 「Jenkins 는 staging 배포 호스트에 있다」). 그 이미지는 루트
  `.dockerignore` 대신 `docker/ci.Dockerfile.dockerignore` 를 읽어 **문서를 들인다** — 문서 검사와
  다이어그램 최신성 시험이 그것을 읽는다(빼먹었을 때 넷이 「파일이 없다」로 빨갰다).
- **실측**(2026-10-02, 첫 초록): sub 쪽 전체 약 3분(pytest 2489건 47초), macos e2e 공개 14초 ·
  운영자 4초 · 강의실 4초(이미지 굽기 제외).
- **잡 설정은 저장소 밖이다** — Multibranch 잡·자격증명(`github-sandcorporation-token` 은
  fine-grained PAT: 저장소 읽기·PR·커밋 상태·Contents 쓰기, `glitchtip-automation-token`)은 사람이
  Jenkins 에 만든다. Jenkins 설정을 API 로 고칠 때는 `Content-Type: application/xml;
  charset=utf-8` 을 붙인다 — 없으면 한글이 Latin-1 로 읽혀 500 이 난다.
- **GitHub Actions 에는 이미지 빌드와 부팅 가드만 남았다**(`images.yaml`, 호스티드 러너 — 위
  「배포」 절). 부팅 가드 셋은 프로덕션 이미지를 구워 배포 설정 없이는 죽고 완전한 설정으로는
  뜨는지 본다 — 컨테이너 포트를 러너에 열지 않고 띄운 컨테이너의 네트워크에 curl 컨테이너를
  붙여(`--network container:<이름>`) 친다(러너가 컨테이너일 때도 같은 모양이다).

**CI 는 `docker/compose.ci.yaml` 을 dev compose 위에 겹쳐 쓴다 — 지우면 CI 가 깨진다.**
`compose.dev.yaml` 의 `..:/app` 은 **개발용 핫리로드 장치**다. 러너 안에서 그 상대 경로는
호스트 데몬 기준으로 풀려 `/app` 이 통째로 비고, backend 는 `can't open file '/app/manage.py'`
로, 두 앱은 `Scope: all 0 workspace projects` 로 죽는다. 오버라이드가 하는 일은 셋뿐이다:

- 다섯 서비스(backend·events·frontend·operator·classroom, #379)의 `volumes` 를 `!reset []` —
  마운트 없이 **이미지 안의 코드**로 돈다.
- 세 앱(frontend·operator·classroom, #277)의 빌드 `target` 을 `runner` 로 — dev 서버가
  아니라 **배포되는 그 이미지**를 친다.
- 세 앱의 `command` 를 `!reset null` — 이미지의 `node server.js` 가 산다.

**그래서 e2e 가 검증하는 대상이 바뀌었다.** 예전엔 `next dev` 를, 지금은 프로덕션 빌드를
친다 — 배포되는 것과 테스트되는 것이 같아졌다. 위 `next dev` 메모리 주의는 이제
**로컬에서 스위트를 돌릴 때만** 해당한다.

**스택마다 이름을 갈라 준다.** e2e 와 celery-broker 의 compose 프로젝트 이름은 빌드
식별자(`CODEMIT_CI_RUN_ID` — 빌드 태그 + 시작 시각)에서 나오고, 포트는 compose 가 비어 있는 것을
고른다. 끝나면(성공·실패·중단 모두) `down -v` 로 지운다.

**화면 언어 검사**(#267, #268 — PR CI 의 sub 단계)는 스텝 둘로 두 표면을 막는다. 첫 스텝
(`scripts/check_screen_language.py`)은 공개 앱(`frontend/`)의 화면 문자열에
`CONTEXT.md` 가 정한 영어 도메인 용어(`Sponsor`·`Contest`·`Escrow` 등)나
`ADR-숫자`·`#숫자` 참조가 있으면 막는다. 둘째 스텝(`scripts/
check_backend_error_language.py`, #268)은 백엔드가 공개 앱으로 던지는
`HttpError(...)` 의 message 인자에 같은 것을 막는다 — 화면 문자열 자체가
아니라 백엔드 오류를 그대로 렌더하는 자리(`packages/bff-client/src/
result.ts` 의 `normalizeDetail`)라 첫 스텝이 볼 수 없던 표면이다. 운영자 API
(`/api/operator/*`)는 두 스텝 다 대상이 아니다 — 뒤쪽은 파일이 아니라 함수
단위로(데코레이터가 `router`인지 `operator_router`인지, 도우미는 호출
그래프로) 가른다. 정말 필요한 예외는 둘 다 같은 `SCREEN-LANGUAGE-EXCEPTION:
<이유>` 주석으로 표시한다.

**첫 스텝이 셋째 것도 막는다 — 화면이 자기 구현을 설명하는 문장이다**(2026-09-21).
이 저장소는 주석과 `docs/` 를 두껍게 쓰는데, 그 말투가 **사용자가 읽는 화면으로
새어 나간 적이 있다**: 이용약관에 「유료 공모전을 여는 시점에 채우는 조항」이라는
절이 있었고 방침 서두가 「그 조항은 8절에 자리만 남겨 두었고, 기능을 열 때
채웁니다」라고 말했다 — 없는 조항을 목차로 예고하는 약관은 없다. 공모전 상세의
무료 안내도 같은 종류로 한 번 지적받았다(2026-09-20, 화면 맨 위 상자 → 맨 아래
작은 글씨).

**규칙은 하나다: 화면은 지금 참인 사실만 말하고, 아직 없는 것은 적지 않는다.**
기능을 열 때 그 문서를 고쳐 알린다(약관·방침은 스스로 개정 조항을 갖고 있다).
`check_screen_language.py` 의 `META_PHRASES`(`자리만 남`·`채울 자리`·`나중에
채우`·`아직 구현`·`TODO` 등)가 그 말투를 기계로 막고, 같은
`SCREEN-LANGUAGE-EXCEPTION: <이유>` 로 연다. 목록은 오탐을 만들지 않도록 「이
자리는 나중에 채운다」는 뜻으로만 쓰이는 토막만 담는다 —
`scripts/test_check_screen_language.py` 가 「남은 자리가 없습니다」 같은 정상
문구가 통과하는 것까지 고정한다.

## Agent skills

### Issue tracker

GitHub Issues on `sandcorporation/laurio`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, unchanged: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

**ADR 은 역사다** — 위 「어느 문서가 「지금」을 말하는가」를 먼저 읽는다. ADR 과 나란히
현재를 말하는 것은 `CONTEXT.md` 와 `docs/features/` 다.

### Feature docs

`docs/features/` 가 **지금 이 서비스가 무엇을 하는가**를 말한다 — 백엔드·공개 앱·운영자 앱
하나씩. 기능을 더하거나 지우는 티켓이면 여기도 같은 커밋에서 고친다(위 「티켓을 닫는
기준」). 무엇이 바뀌면 어디를 고치는지는 `docs/features/README.md` 의 표가 들고 있다.

### Legal docs

`docs/legal/` 은 지도다 — 어느 법이 어디에 닿고, 코드가 어디서 지키며, 무엇이 아직
확인되지 않았는지. `README.md` 가 색인이고 열린 항목을 한 표로 모은다. 결정의 원문은
ADR, 값은 코드에 있다 — 세무·개인정보·약관·IP·결제 구조를 건드리면 먼저 읽고, 새
결정이 「약관 항목」을 만들면 `contracts-and-ip.md` 의 목록에 더한다.

### 이 저장소에만 있는 스킬

`.claude/skills/` 에 둔다 — 이 저장소를 열 때만 뜨고, 저장소와 함께 버전이 남는다
(`.gitignore` 가 `.claude/worktrees/` 만 무시하고 나머지는 커밋하도록 열어 둔 이유가
이것이다).

- **`contest-copy`** — 공모전 설명 문구를 쓰거나 고친다(2026-09-17). 실제 공모전 공고의
  항목 구성·어투, 이 서비스의 렌더러가 실제로 그리는 것(ADR-0047), 그리고 **공개한 뒤에는
  설명을 고치는 API 가 없다**는 사실이 그 안에 있다. 첫 무료 공모전의 설명이 「AI 가 쓴
  어투」라는 지적을 받아 고치면서, 무엇이 갈리는지를 세어 본 결과를 남겼다.
