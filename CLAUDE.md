# Laurio

## 개발 환경

Python + uv, Django + django-ninja, PostgreSQL. 백엔드는 `backend/`, 컨테이너 구성은 `docker/`.

```bash
docker compose -f docker/compose.dev.yaml up          # 전체 스택
docker compose -f docker/compose.dev.yaml up -d db redis   # 테스트용 인프라
cd backend && uv run pytest                           # 테스트
```

**공개 포트가 표준이 아니다.** compose 기본값이 5432·8000·6379·3000을 통째로 비켜 잡아
뒀다 — 표준 포트를 쓰는 다른 프로젝트와 한 머신에 얹기 위해서다. 지금 개발 머신에는
그런 프로젝트가 없지만 기본값은 그대로 둔다(옮기면 아래 표의 환경변수와 문서·스크립트가
같이 흔들린다).

| | 호스트 | 컨테이너 | 환경변수 |
| --- | --- | --- | --- |
| PostgreSQL | `55432` | 5432 | `LAURIO_DB_PORT` |
| backend | `58000` | 8000 | `LAURIO_API_PORT` |
| Redis | `16379` | 6379 | `LAURIO_REDIS_PORT` |
| 공개 앱(`frontend/`) | `53000` | 3000 | `LAURIO_WEB_PORT` |
| 운영자 앱(`operator/`, #63) | `53001` | 3000 | `LAURIO_OPERATOR_WEB_PORT` |

호스트에서 `uv run pytest`를 돌릴 때 붙는 DB 포트 기본값도 `LAURIO_DB_PORT`를 따라간다
(`backend/config/settings.py`). 컨테이너 안에서는 compose가 `POSTGRES_*`를 직접 주입한다.

## 배포 (dev / staging / prod)

세 compose 파일이 분리되어 있다 — 시크릿·어댑터 바인딩이 환경을 넘어 섞이지 않는다:

| | 파일 | `LAURIO_DEPLOYMENT_TARGET` | 어댑터 | TLS·secure 쿠키 하드닝 |
| --- | --- | --- | --- | --- |
| dev | `docker/compose.dev.yaml` | (미설정) | 전부 Fake (MinIO만 예외) | 없음 |
| staging | `docker/compose.staging.yaml` | `staging` | 전부 real(토스 샌드박스, 실제 S3/OCI 등) | 없음 |
| prod | `docker/compose.prod.yaml` | `production` | 전부 real(토스 실물) | 있음 |

어댑터 바인딩표(ADR-0007)는 각 compose 파일 상단 주석에 있다. 시크릿은
`docker/staging.env.example`/`docker/prod.env.example`을 복사해 `docker/.env.staging`/
`docker/.env.prod`로 채운다 — 둘 다 `.gitignore`가 막아 커밋되지 않는다.

**staging 은 떠 있다** — `https://laurio.honeycombpizza.link`(공개 앱),
`operator.laurio.honeycombpizza.link`(운영자 앱), `storage.honeycombpizza.link`(브라우저가
직접 PUT 하는 MinIO). 어댑터 6종 전부 실물 구현이 있다: `PortOneV2VerificationAdapter`(#85) ·
`TossPGAdapter`(#87) · `TossPayoutAdapter`·`TossSellerAdapter`(#57) ·
`OpenAIScoringAdapter`(#88) · `OpenAIRequirementChatAdapter`. 각 dotted path 는
`docker/staging.env.example` 에 그대로 적혀 있다.

**그래도 가드는 그대로다.** `core.adapters.check_adapter_mode`(`django.core.checks` 로
등록되어 `django.setup()` 이후 `manage.py migrate`/`check`/`runserver` 부팅 파이프라인에서
평가된다, #83)가 여섯 값(`VERIFICATION_ADAPTER_MODE`·`PAYMENT_ADAPTER_MODE`·
`PAYOUT_ADAPTER_MODE`·`SELLER_ADAPTER_MODE`·`LLM_ADAPTER_MODE`·
`LLM_REQUIREMENT_CHAT_ADAPTER_MODE`)이 배포 환경에서 fake 이거나 임포트되지 않으면 부팅
자체를 거부한다 — 컨테이너가 뜬 채로 첫 요청에서야 죽는 것보다 정직하게 못 뜨는 편이다.

`config/settings.py`의 `IS_DEPLOYED_ENVIRONMENT`(staging+production)가 fake 어댑터
바인딩을 부팅 시점에 거부하고, `IS_PRODUCTION_DEPLOYMENT`(production만)가 추가로
`manage.py check --deploy`가 요구하는 HSTS·SSL 리다이렉트·secure 쿠키·강한
`SECRET_KEY`를 강제한다. staging은 검증용 서브 호스트라 운영자가
`POST /api/internal/tick`을 수동으로 쏴서 21일 시나리오를 몇 초에 재현할 수 있다(tick 은
스캔 등록부 `core/scans.py` 의 스캔 **전부**를 등록 순서로 한 바퀴 돈다 — 전이·채점·환불·배분·
지급·알림. 스캔 하나만 돌리려면 `POST /api/internal/scans/{name}`, #137/#140) —
두 파일 모두 `INTERNAL_API_TOKEN`이 없으면 부팅 자체가 거부된다.

**운영자 앱(`operator/`)도 두 compose 파일에 뜬다**(#70). 공개 앱(`frontend`)과
같은 3스테이지 이미지(`docker/operator.Dockerfile` — dev/builder/runner)를 쓰고,
배포 compose는 `target: runner`를 명시적으로 고른다. 필수 설정은
`LAURIO_OPERATOR_ORIGIN`과 `LAURIO_API_BASE_URL`— 배포 환경에서 둘 중 하나라도
비면 `operator/instrumentation.ts`가 첫 요청을 받기 전에 `process.exit(1)`로
프로세스를 끊는다(`throw`만으로는 Next가 그 에러를 삼켜 컨테이너가 Up인 채로
이유 없는 500만 낸다는 게 공개 앱 쪽에서 이미 확인된 사실이다).

**`LAURIO_OPERATOR_ORIGIN`은 백엔드와 운영자 앱이 같은 `.env.staging`/`.env.prod`
줄 하나를 나눠 읽는 값이다** — 백엔드의 `OperatorOriginMiddleware`가 기대하는
오리진과 운영자 앱이 나가는 요청에 붙이는 오리진이 어긋나면 로그인을 포함한
모든 운영자 변경 요청이 조용히 403이 된다(fail-closed라 보안 구멍은 아니지만
원인을 찾기 어렵다 — 이 저장소가 이미 두 번 겪은 실패). 공개 앱의 오리진과
반드시 다른 서브도메인을 쓴다 — 같은 오리진을 공유하면 공개 앱이 뚫렸을 때
운영자 세션 쿠키까지 노출될 길이 생긴다.

**staging 배포는 `deploy.sh` 가 한다 — `Jenkinsfile` 이 아니다.** Jenkins 잡은
Pipeline 이 아니라 **freestyle** 이고, 셸 스텝이 `sh ./deploy.sh staging` 하나뿐이라
`Jenkinsfile` 은 읽히지 않는다. 이걸 모르고 Jenkinsfile 만 고쳤다가 빌드가
`cannot open ./deploy.sh` 로 통째로 실패했다 — 지금은 `Jenkinsfile` 도 같은
스크립트를 부르는 껍데기라 어느 쪽으로 돌려도 동작이 같다.

`deploy.sh` 는 **바뀐 것만 다시 굽는다**. 기준점은 `.jenkins-staging-deployed`
(gitignore, 빌드 디렉터리에 남는다 — 시크릿과 같은 전제). 그 파일이 없거나 그것이
가리키는 커밋이 저장소에 없으면 전부 굽는다. 경로 → 서비스 팬아웃은 1:1 이 아니다:
`backend/` 는 **backend + celery-worker + celery-beat** 를 함께 갈고(셋은 같은
Dockerfile 을 쓰지만 공유 `image:` 태그가 없어 **이미지가 셋**이다 — `build backend`
만 하면 워커 둘은 옛 이미지에 남고, `up -d` 는 바뀐 게 없으니 Running 이라 적고
지나가 배포가 초록으로 끝난 채 스캔만 옛 코드로 돈다),
`packages/bff-shared/` 와 `pnpm-lock.yaml` 은 **frontend + operator** 를 함께 간다.
없는 컨테이너는 변경 여부와 무관하게 굽는다 — 「없음」은 「최신」이 아니다.

**헬스 체크는 Host 헤더를 붙여야 한다.** 루프백으로 치면 Host 가 `127.0.0.1` 이
되는데 그건 `ALLOWED_HOSTS` 에 없어 Django 가 400 을 낸다 — gunicorn 이 멀쩡히
떠 있어도 배포가 실패로 끝난다(빌드 #5 가 세 이미지를 다 굽고 다섯 컨테이너를 다
띄운 뒤 그렇게 죽었다). 스크립트는 `DJANGO_ALLOWED_HOSTS` 의 첫 항목을 쓴다.

**Jenkins 는 staging 배포 호스트에 있다 — 개발 머신이 아니다.** 아래 `docker exec
jenkins` 와 `/server/jenkins/...` 는 그 호스트에서만 유효하다(개발 머신에서 치면
컨테이너도 경로도 없다).

Jenkins 컨테이너는 호스트 docker 소켓을 물고 root 로 돈다. 빌드 로그는
`docker exec jenkins sh -c 'tail /var/jenkins_home/jobs/laurio/builds/<N>/log'`.
워크스페이스는 컨테이너의 `/var/jenkins_home/workspace/laurio` 이자 호스트의
`/server/jenkins/workspace/laurio` 다 — **경로가 다르므로** compose 에 상대경로
바인드 마운트를 넣으면 호스트 데몬이 엉뚱한 곳을 본다. 지금은 named volume 뿐이다.

**`appeals` 마이그레이션이 다시 만들어졌다**(#44). 배포 이력이 없어 단일 initial 로
정리했는데, 옛 `0001_initial` 을 이미 적용한 dev DB 는 Django 가 "적용 완료" 로
보고 조용히 지나간다 — 테이블이 없다는 오류가 한참 뒤 런타임에 난다. 그 시점의
DB 가 있다면 볼륨째 다시 만들어야 한다:

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

## 운영

**Django admin 은 없다**(#46, ADR-0019). `/admin/` 은 마운트되지 않고 각 앱의
`admin.py` 도 없다 — admin 은 모델 행을 직접 편집할 수 있어서, `Appeal`·
`AppealRuling` 을 그 화면에서 고칠 수 있는 한 감사 추적에 우회로가 남는다.

사람이 판단하는 행위는 `/api/operator/*` 로만 한다. 운영자 앱이 나올 때까지는
운영자가 HTTP 로 그 API 를 직접 친다.

개발 중 데이터를 훑던 수단도 함께 사라졌다. 대신 이렇게 한다:

```bash
cd backend && uv run python manage.py shell      # ORM 으로 조회
docker compose -f docker/compose.dev.yaml exec db psql -U laurio -d laurio
```

첫 Operator 는 관리 명령으로 만든다 — 계정 관리 화면이 없기 때문이다.
`createsuperuser` 는 쓰지 않는다(Operator 와 참가자가 서로소라는 불변식을 모른다):

```bash
cd backend && uv run python manage.py create_operator <아이디> --superuser
```

## 테스트

Operator 세션은 실제 Redis 에 산다(#43, ADR-0018) — 그래서 테스트에도 `redis` 가
필요하다. DB 와 같은 구조다: 인프라는 compose 가 주고 pytest 는 호스트에서 붙는다.

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
cd backend && LAURIO_DB_PORT=55432 uv run pytest   # 포트는 쓰는 스택에 맞춰 바꾼다
```

dev compose의 `db` 서비스는 호스트 포트로 이미 노출돼 있으므로 호스트의 `uv run
pytest`가 그 DB에 직접 붙는다 — 컨테이너를 거칠 이유가 없다.

**스위트는 기본으로 병렬 실행된다**(#104). `pyproject.toml` 의 `addopts` 가 `-n 4` 를
준다 — 직렬 4분 11초가 1분 18초다(실측, 1132건). 워커별 테스트 DB 는 pytest-django 가,
세션 Redis 인덱스는 `tests/conftest.py` 가 갈라 준다. 직렬로 보려면 `-n 0`.

**`-n auto` 를 쓰지 마라 — `-n 4` 가 기본값인 이유가 있다.** `auto` 는 논리 코어
수(이 머신은 12)를 잡는데, 세션 Redis 인덱스가 워커마다 하나씩 올라간다
(`tests/conftest.py`: 기준 인덱스 + 워커 번호 + 1). 기본 `/1` 에 12워커면 최대 13 이라
아슬아슬하게 통과하지만, 인덱스를 조금만 올려 잡으면 그대로 Redis 기본 범위(0~15)를
넘겨 conftest 의 가드가 그 자리에서 막는다 — `/13` 이면 워커 넷만으로도 넘는다.
병렬 워크트리에서는 **낮은 인덱스를 골라 4칸씩 띄워 쓴다**(예: 체인마다 /0, /5, /10).

**pytest 를 두 개 이상 동시에 돌린다면 `LAURIO_TEST_DB_NAME` 을 서로 다르게
줘라.** 기본값은 Django 관례대로 `test_laurio` 하나라, 병렬 워크트리에서 체인 둘이
각자 pytest 를 돌리면 같은 DB 를 두고 싸운다 — `DROP DATABASE ... is being
accessed by other users` 로 서로를 떨어뜨리고, 그 실패는 **코드 회귀와 구분되지
않는다.** 실제로 겪었다.

**같은 이유로 `SESSION_REDIS_URL` 의 DB 인덱스도 달리 줘라.** Operator 세션은
실제 Redis 에 산다(ADR-0018). `tests/conftest.py` 가 테스트마다
`caches["sessions"].clear()` 를 부르는데 Django 의 RedisCache 는 그것을
**FLUSHDB** 로 구현한다 — **키 접두어로는 막을 수 없다.** 두 체인이 같은 인덱스를
쓰면 한쪽의 테스트 정리가 다른 쪽의 로그인 세션을 통째로 지우고, 피해자는
원인과 무관한 401 무더기를 본다.

```bash
cd backend && LAURIO_DB_PORT=55432   LAURIO_TEST_DB_NAME=test_laurio_c2   SESSION_REDIS_URL=redis://127.0.0.1:16379/5   uv run pytest
```

## 프론트엔드

Next.js + React. 저장소 루트가 pnpm 워크스페이스다(운영자 앱 04 #62, ADR-0021) —
락파일은 루트의 `pnpm-lock.yaml` 하나뿐이고, 공개 앱(`frontend/`, 위치·패키지 이름
변경 없음)·운영자 앱(`operator/`)·공유 BFF 패키지 둘이 그 멤버다 —
`packages/bff-shared`(서버 쪽: 경로 순회 방어·Origin 검증·허용목록 검사 함수·백엔드
전달 기계. 허용목록의 **내용**은 앱마다 자기 파일에 남는다)와 `packages/bff-client`
(브라우저 쪽, #146: 인증 구역 호출의 클라이언트·`ApiResult`·`normalizeDetail`·
`useBackendQuery`/`usePagedList`·생성 타입 `schema.gen.ts`). 명령은 그대로다 — 워크스페이스가
생겨도 `pnpm --dir <앱>` 호출법은 바뀌지 않는다.

테스트 시임은 **앱마다 하나**다(ADR-0021, ADR-0017 개정) — 앱이 둘이어도 그 아래로
내려가는 컴포넌트 테스트·모킹은 없다. `docker compose -f docker/compose.dev.yaml up`
으로 두 앱이 다 뜬 스택을 띄운 뒤 `pnpm --dir frontend test` 로 Playwright 가 프로젝트
둘로 두 앱을 한 번에 친다(공개 앱 스펙은 `frontend/e2e/*.spec.ts`, 운영자 앱 스펙은
`frontend/e2e/operator/*.spec.ts` — `playwright.config.ts` 가 프로젝트마다 다른
`testDir`·`baseURL` 을 준다). `LAURIO_E2E_BASE_URL`/`LAURIO_OPERATOR_E2E_BASE_URL`
로 각 프로젝트의 `baseURL` 을 바꿀 수 있다(기본값은 위 포트 표와 같다).
`pnpm --dir frontend typecheck`/`pnpm --dir operator typecheck` 는 스택 없이 돈다.

**운영자 앱은 인증의 모양이 다르다**(#63, ADR-0018/0019). 공개 앱은 쿠키의 JWT를
`Authorization` 헤더로 바꿔 달지만, 운영자 앱은 Django 세션 쿠키
(`laurio_operator_session`, `backend/config/settings.py`)를 이름으로만 골라
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
cd <worktree>/backend
LAURIO_DB_PORT=55432 STORAGE_BACKEND=s3 uv run python manage.py runserver 0.0.0.0:58101 &
cd ../frontend
LAURIO_API_BASE_URL=http://127.0.0.1:58101 pnpm exec next dev -p 53201 &
LAURIO_E2E_BASE_URL=http://127.0.0.1:53201 LAURIO_E2E_NAMESPACE=c2 pnpm exec playwright test --project=public
kill %1 %2
```

`STORAGE_BACKEND=s3` 를 주는 이유는 dev compose 의 backend 가 그렇게 뜨기 때문이다
(업로드 e2e 가 실물 MinIO 를 쳐야 한다) — 빼면 업로드 스펙만 갈린다.

**워크트리에서 일한다면 e2e 가 당신 코드를 치지 않는다.** `playwright.config.ts`
에 `webServer` 가 없는 것은 의도다(ADR-0021 — 테스트가 앱의 수명을 소유하지
않는다). 그 결과 compose 로 뜬 `frontend` 컨테이너는 **바깥 체크아웃**을 마운트해
서빙하므로, 격리된 워크트리에서 프론트를 고치고 e2e 를 돌리면 **고치기 전 코드가
통과한다.** 병렬 체인 둘이 각자 이 사실을 재발견했다.

워크트리 코드로 검증하려면 그 워크트리에서 임시 Next 서버를 띄우고 baseURL 을
그쪽으로 돌린다 — 백엔드는 이미 떠 있는 것을 그대로 쓴다:

```bash
cd <worktree>/frontend
LAURIO_API_BASE_URL=http://127.0.0.1:58000 pnpm exec next dev -p 53100 &
LAURIO_E2E_BASE_URL=http://127.0.0.1:53100 pnpm exec playwright test --project=public
kill %1
```

끝나면 반드시 죽인다 — 남겨 두면 다음 체인이 그 포트에서 막힌다.

**TDD 안쪽 고리에서 전체를 돌리지 마라.** 관련 파일만 돌리고, 전체는 게이트로 둔다.

| 언제 | 무엇 | 실측 |
| --- | --- | --- |
| red→green 반복 | 그 테스트 파일 하나 | 백엔드 3~17초 · e2e 13~42초 |
| 티켓 커밋 직전 | 건드린 쪽 스위트 (`pytest` 또는 `test:operator`) | 1분 20초 · 4.7분 |
| 체인/PR 보고 직전 | 전체 | 백엔드 1분 20초 + e2e 7분 |

백엔드 수치는 이 머신 실측이다. **e2e 수치는 전부 이전 머신(WSL) 실측이라 여기서는
다시 재지 않았다** — 아래 스위트 시간들도 같다.

```bash
cd backend && LAURIO_DB_PORT=<포트> uv run pytest tests/test_payouts.py -q
pnpm --dir frontend exec playwright test --project=operator e2e/operator/policy.spec.ts
```

안쪽 고리에서 전체를 돌리면 **한 번의 red→green 이 17초가 아니라 8분**이 된다.
슬라이스 하나에 그 왕복이 여러 번 있으니 티켓 하나가 통째로 테스트 대기에 잠긴다.

**스위트가 8분을 넘긴다 — 한 앱만 고쳤으면 그 앱만 돌린다.**

```bash
pnpm --dir frontend test            # 전체 (약 7분, 170건)
pnpm --dir frontend test:operator   # 운영자 앱만 (약 4.7분, 91건)
pnpm --dir frontend test:public     # 공개 앱만 (약 2.3분, 79건)
```

이게 편의가 아니라 필요다. 서브에이전트의 명령 타임아웃 상한이 10분인데 전체
스위트가 부하에 따라 8~10분에서 흔들린다 — 넘으면 하네스가 백그라운드로 돌리고
그 완료 알림은 에이전트가 아니라 최상위 세션으로 가서, 에이전트가 오지 않을
신호를 영원히 기다린다. 실제로 여러 체인이 그렇게 멈췄다.

**두 가지가 이미 시간을 반으로 줄여 뒀다 — 되돌리지 마라.**

`globalSetup` 이 두 앱의 주요 라우트를 미리 친다. Next dev 서버는 라우트를
요청받을 때 컴파일해서, 없으면 첫 실행이 테스트가 아니라 컴파일을 기다린다
(public 콜드 5.6분 대 웜 2.5분, 같은 79건 — contests-pagination 은 30초
타임아웃으로 실패하기까지 했다).

`seedE2eOperator()` 를 **인자 없이** 부르면 프로세스 안에서 계정을 재사용한다.
시드 호출 127회 중 79회가 이것이었고 한 번에 약 1.4초(Django 부팅만 640ms)라
계정 만드는 데만 95초가 쓰였다. **계정 자체를 바꾸는 테스트는 반드시 고유한
`username` 을 줘야 한다** — 인자를 주면 캐시를 타지 않는다.

**공개 스위트는 병렬로 돈다 — 다만 모두가 그런 것은 아니다**(#104). 실행이 두
패스로 갈린다: `@exclusive` 태그가 없는 것을 병렬로, 그 다음 태그가 붙은 것만
워커 하나로. `pnpm --dir frontend test:public` 이 그 둘을 이어 돌린다.

배타로 도는 것들과 그 이유 — **전역 상태를 건드리거나 전역 목록을 읽기 때문**이다.
`tokens.spec.ts` 는 추적 파일 `app/tokens.css` 를 실제로 편집하고(FE-02 #27),
`contests-list`·`contests-pagination`·`contests-detail`·`home` 은 공개 목록을 읽는데
그 화면은 네임스페이스로 필터링하지 않아 **다른 워커가 심은 Contest 도 함께
보인다**. `submit`·`upload` 는 고정 제목으로 Contest 를 만들어 서로를 덮어쓴다.
전역 상태를 건드리는 스펙을 새로 쓰면 그 태그를 붙여라.

**운영자 스위트는 여전히 직렬이다**(`test:operator` 가 `--workers=1`). 그쪽은 큐의
전체 건수를 단언하고(홈의 세 숫자), 「0건은 0건이라고 말한다」는 아예 빈 큐를
요구한다 — 2워커로 돌려 4건이 그렇게 깨지는 것을 확인했다. 풀려면 운영자 큐
시드에도 워커별 네임스페이스가 필요하다.

시드 충돌은 `seed_e2e_contests --namespace` 가 막는다 — 접두어와 계정 이름이 워커별로
갈려 자기 범위만 지운다. 그 대가로 아무도 안 걷는 것(죽은 워커의 잔여물, 런타임에
만들어진 `[E2E] `)이 생겨, `global-setup` 이 시작 전에 `--prune-all-namespaces` 로
한 번 걷는다.

**스위트를 연달아 돌렸다면 `frontend` 컨테이너를 재시작한다.** `next dev` 의 메모리가 회차마다
늘어(측정: 4.8GB → 6.3GB) 로그인 뒤 `/console` 이동이 5초를 넘기기 시작하고, 그러면 매 회차
무작위로 한두 건이 `toHaveURL(/\/console/)` 타임아웃으로 붉어진다 — 코드 회귀와 구분되지 않는
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

**API 타입은 손으로 쓰지 않는다.** `frontend/lib/api/schema.gen.ts` 는
`pnpm --dir frontend generate:api`(`frontend/scripts/generate-api-types.mjs`)가
백엔드의 OpenAPI 스키마에서 생성해 커밋한 산출물이다. 이 명령은 **스택이 필요
없다** — `uv run python manage.py export_openapi_schema`(DB 접속 없이 등록된
라우터·스키마만 읽는다, `backend/core/management/commands/
export_openapi_schema.py`)로 스키마를 뽑은 뒤 `openapi-typescript` 로 변환한다.
`uv sync` 만 된 신선한 체크아웃에서 바로 돈다 — CI의 `frontend-openapi-types` 잡이
컨테이너를 기다리지 않고 이 명령을 그대로 돌려 `git diff`로 최신성을 확인하는
이유다. 백엔드 스키마가 바뀌었는데 재생성을 안 하면(혹은 재생성해도 필드가
없어졌는데 호출부를 안 고치면) `tsc --noEmit` 이 빌드타임에 잡는다.

## Agent skills

### Issue tracker

GitHub Issues on `sandcorporation/laurio`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, unchanged: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Legal docs

`docs/legal/` 은 지도다 — 어느 법이 어디에 닿고, 코드가 어디서 지키며, 무엇이 아직
확인되지 않았는지. `README.md` 가 색인이고 열린 항목을 한 표로 모은다. 결정의 원문은
ADR, 값은 코드에 있다 — 세무·개인정보·약관·IP·결제 구조를 건드리면 먼저 읽고, 새
결정이 「약관 항목」을 만들면 `contracts-and-ip.md` 의 목록에 더한다.
