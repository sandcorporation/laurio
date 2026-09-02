# Laurio

## 개발 환경

Python + uv, Django + django-ninja, PostgreSQL. 백엔드는 `backend/`, 컨테이너 구성은 `docker/`.

```bash
docker compose -f docker/compose.dev.yaml up          # 전체 스택
docker compose -f docker/compose.dev.yaml up -d db redis   # 테스트용 인프라
cd backend && uv run pytest                           # 테스트
```

**공개 포트가 표준이 아니다.** 이 머신의 5432·8000은 다른 프로젝트가 쓰고 있어 비켜 잡았다.

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

**staging/prod는 지금 뜨지 않는다 — #85(PortOne 본인확인)·#87(Toss 결제)·
#57(Seller 등록)·#88(OpenAI 채점/AI grill)이 끝나기 전까지는 의도된 상태다.**
저장소에 `Real*` 어댑터 클래스가 하나도 없어서다 — `VERIFICATION_ADAPTER_MODE`·
`PAYMENT_ADAPTER_MODE`·`PAYOUT_ADAPTER_MODE`·`SELLER_ADAPTER_MODE`·
`LLM_ADAPTER_MODE`·`LLM_REQUIREMENT_CHAT_ADAPTER_MODE` 여섯 값을 `example`
그대로 채워도(`${VAR:?...}`가 요구하는 값을 줘도) `core.adapters.check_adapter_mode`
(`django.core.checks`로 등록되어 `django.setup()` 이후 `manage.py
migrate`/`check`/`runserver` 부팅 파이프라인에서 평가된다, #83)가 "fake도
아니고 실제로 쓸 수도 없다"며 부팅 자체를 거부한다. 컨테이너가 뜬 채로
첫 요청에서야 죽는 것보다, 정직하게 못 뜨는 편을 택했다 — 위 네 티켓이 각자의
dotted path를 채워 넣으면 그 값으로 교체되며 정상 부팅된다.

`config/settings.py`의 `IS_DEPLOYED_ENVIRONMENT`(staging+production)가 fake 어댑터
바인딩을 부팅 시점에 거부하고, `IS_PRODUCTION_DEPLOYMENT`(production만)가 추가로
`manage.py check --deploy`가 요구하는 HSTS·SSL 리다이렉트·secure 쿠키·강한
`SECRET_KEY`를 강제한다. staging은 검증용 서브 호스트라 운영자가
`POST /api/internal/tick`을 수동으로 쏴서 21일 시나리오를 몇 초에 재현할 수 있다 —
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
변경 없음)·운영자 앱(`operator/`)·공유 BFF 패키지(`packages/bff-shared`, 경로
순회 방어·Origin 검증·허용목록 검사 함수·백엔드 전달 기계만 담는다 — 허용목록의
**내용**은 앱마다 자기 파일에 남는다)가 그 멤버다. 명령은 그대로다 — 워크스페이스가
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

**TDD 안쪽 고리에서 전체를 돌리지 마라.** 관련 파일만 돌리고, 전체는 게이트로 둔다.

| 언제 | 무엇 | 실측 |
| --- | --- | --- |
| red→green 반복 | 그 테스트 파일 하나 | 백엔드 3~17초 · e2e 13~42초 |
| 티켓 커밋 직전 | 건드린 쪽 스위트 (`pytest` 또는 `test:operator`) | 3분 · 4.7분 |
| 체인/PR 보고 직전 | 전체 | 백엔드 3분 + e2e 7분 |

```bash
cd backend && LAURIO_DB_PORT=<포트> uv run pytest tests/test_payouts.py -q
pnpm --dir frontend exec playwright test --project=operator e2e/operator/policy.spec.ts
```

안쪽 고리에서 전체를 돌리면 **한 번의 red→green 이 17초가 아니라 10분**이 된다.
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

**병렬로 돌리지 마라(`workers: 1` 을 올리지 마라).** 시도해서 8.0분이 3.5분으로
줄었지만 **16건이 실패했다.** 공개 스펙 넷이 각자 `beforeAll` 에서 같은 고정
접두어 데이터를 다시 심어 서로를 리셋하는 구조이고(직렬에서만 성립한다), 운영자
쪽은 큐 **건수**를 단언한다. 병렬로 가려면 시드에 워커별 네임스페이스를 주는
설계 변경이 먼저다 — 설정 한 줄로 되는 일이 아니다. 시간은 특정 테스트에 몰려
있지도 않다(167건 합계 467초, 가장 느린 10건이 19%).

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
