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

**워크트리는 스택을 통째로 따로 띄운다.**

```bash
eval "$(sh docker/dev-env.sh)"
docker compose -f docker/compose.dev.yaml up -d
```

`docker/dev-env.sh` 가 체크아웃 경로에서 compose 프로젝트 이름과 **모든 포트**를 파생한다 —
DB·Redis·MinIO·두 앱이 통째로 갈리므로 체인 둘이 서로의 데이터를 보지 않는다. 예전에는
스택 하나를 공유하고 시드 이름 접두어로 막았는데, 그 방식은 전역 건수나 단일 행(정책·시계)
앞에서는 성립하지 않는다.

**주 워크트리는 오프셋 0 이다** — 위 표의 포트가 그대로다. 판정 기준은 디렉터리 이름이
아니라 `git worktree list` 가 말하는 주 워크트리인가이고(다른 이름으로 클론해도 맞는다),
스크립트는 cwd 가 아니라 **자기 위치**를 기준으로 삼는다. 해시가 겹치면 나중에 뜨는 쪽이
포트 바인딩 실패로 **못 뜬다** — 조용히 남의 스택에 붙는 것보다 낫다.

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
cd backend && LAURIO_DB_PORT=55432 uv run pytest   # 포트는 쓰는 스택에 맞춰 바꾼다
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
cd backend && LAURIO_DB_PORT=55432 uv run python manage.py seed_e2e_operator_appeal
```

**e2e 가 남긴 것이 dev 화면을 덮으면 걷어낸다**(#183). Contest 는 스위트 시작에 저절로
걷히지만(`global-setup.ts` 가 세 정리를 순서대로 부른다 — 실행 토큰별 큐, 네임스페이스별
Contest, 그리고 기준데이터), 스위트를 한동안 안 돌렸다면 손으로 한 번 부른다:

```bash
cd backend && LAURIO_DB_PORT=55432 uv run python manage.py prune_e2e_junk
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
준다 — 실측(이 머신, 1192건) `-n 4` 84초 → `-n auto` 57초. 직렬로 보려면 `-n 0`.

**테스트는 서로를 밟지 않는다 — 손으로 갈라 줄 것이 없다.**

예전에는 체인마다 `LAURIO_TEST_DB_NAME` 과 `SESSION_REDIS_URL` 의 인덱스를 손으로 달리
줘야 했고, 잊으면 조용히 서로를 떨어뜨렸다(`DROP DATABASE ... is being accessed`, 그리고
남의 로그인 세션이 통째로 지워져 나오는 401 무더기 — 둘 다 코드 회귀와 구분되지 않는다).
지금은 둘 다 자동이다:

- **테스트 DB 이름**이 체크아웃 경로에서 파생된다(`config/settings.py` 의
  `_default_test_db_name`). `LAURIO_TEST_DB_NAME` 을 주면 그 값이 이긴다.
- **세션 캐시가 테스트에서는 LocMem 이다**(같은 파일의 `_RUNNING_TESTS`). 프로세스별로
  갈리므로 워커 격리도 체인 격리도 공짜다.

**그래서 pytest 에 Redis 가 필요 없다** — `db` 하나만 띄우면 된다. 예전 문장(「Operator
세션은 실제 Redis 에 산다, 그래서 테스트에도 redis 가 필요하다」)은 더 이상 사실이 아니다.
ADR-0018 은 **운영**에서 세션이 Redis 에 산다고 정한 것이고, 실물 Redis 위의 세션 동작은
운영자 로그인 e2e 가 실물 스택으로 계속 덮는다.

```bash
docker compose -f docker/compose.dev.yaml up -d db   # pytest 에 필요한 것은 이것뿐이다
cd backend && LAURIO_DB_PORT=55432 uv run pytest
```

**그리고 이것이 실제 사고를 하나 막는다.** 호스트 pytest 의 기본 세션 URL 은 dev compose
가 노출한 **바로 그 Redis 의 같은 인덱스**였다. 즉 `uv run pytest` 한 번이 떠 있는 dev
환경의 운영자 세션과 조회 카운터를 통째로 지웠다(`RedisCache.clear()` 는 FLUSHDB 다).
LocMem 으로 바뀌면서 그 경로 자체가 사라졌다.

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

**e2e 는 로컬에서 돌리지 않는다 — CI 가 돌린다.**

프론트엔드 티켓 하나에 한 시간씩 쓰던 이유의 절반이 테스트 대기였다(실측: 티켓당 평균
51분 중 대략 절반). 그래서 개발 중의 확인을 e2e 에서 **브라우저로** 옮긴다.

**개발 중에는 에이전트가 Playwright 로 유저스토리를 직접 걸어본다.** 코드를 쓰고, 실제
브라우저로 그 화면을 열어 사람이 걸을 경로를 그대로 걷고, 걸은 경로를 글로 요약해 보고한다
(`mcp__playwright__browser_*`). **모킹이 아니고 새 시임도 아니다** — ADR-0017/0021 이 정한
바로 그 시임(실행 중인 앱)을 자동화 대신 손으로 미는 것이다. 그 ADR 들은 시임의 **위치**를
정하지 「언제 돌리는가」를 정하지 않는다.

**e2e 스펙은 개발 중에 쓰지 않는다.** 티켓이 끝날 때 1~2개만 남긴다. 무엇을 남기는지는
아래 「남길 것」이 정한다. 새로 쓴 스펙도 **로컬에서 돌리지 않는다** — CI 가 처음 돌린다.

**예외는 하나다: e2e 자체를 고치는 작업.** 스펙을 지우거나 헬퍼를 바꾸는 티켓에서는 e2e 가
작업의 **대상**이므로 돌려 봐야 결과를 안다. 기능 개발에는 해당하지 않는다.

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

로컬 게이트는 셋이다 — **백엔드 `pytest`**, **두 앱 `typecheck`**, **에이전트가 브라우저로
걸어본 결과**. 통과하면 머지하고 **push 한다**. 다음 티켓을 시작하기 전에 CI 결과를 확인해
보고한다.

**push 를 빠뜨리면 CI 는 아무것도 보지 않는다.** 실제로 그런 적이 있다 — 하루 작업 20커밋이
푸시되지 않은 채 쌓였고, 그 사이 CI 잡 하나가 21시간 빨간 것도 아무도 몰랐다. e2e 를 CI 에
맡기는 이상 push 와 결과 확인이 그 규율의 절반이다.

| 언제 | 무엇 | 실측 (이 머신, 2026-09-04) |
| --- | --- | --- |
| red→green 반복 | 백엔드 테스트 파일 하나 | **12초** |
| red→green 반복 | 브라우저로 화면 하나 걸어보기 | **수 초** |
| 티켓 커밋 직전 | `pytest` 전체 | 1분 28초 |
| 티켓 커밋 직전 | 두 앱 `typecheck` | 각 10~20초 |
| CI (push 후) | 전체 | 백엔드 + e2e |

로컬에서 `pnpm --dir frontend test` 를 돌리지 않는다. 스크립트는 CI 와 e2e 자체를 고치는
작업을 위해 남아 있다.

**이번엔 전부 이 머신에서 다시 쟀다** — 옛 표의 e2e 수치는 이전 머신(WSL) 것이었다.

```bash
cd backend && LAURIO_DB_PORT=<포트> uv run pytest tests/test_payouts.py -q
pnpm --dir frontend exec playwright test --project=public e2e/payout.spec.ts -g "상금 그대로가"
```

안쪽 고리에서 전체를 돌리면 **한 번의 red→green 이 4초가 아니라 7분**이 된다. 슬라이스
하나에 그 왕복이 여러 번 있으니 티켓 하나가 통째로 테스트 대기에 잠긴다.

**CI 가 돌리는 것 (참고용 수치).**

```bash
pnpm --dir frontend test            # 전체 (약 1.8분, 102건)
pnpm --dir frontend test:public     # 공개 앱만 (약 1.4분, 74건)
pnpm --dir frontend test:operator   # 운영자 앱만 (약 25초, 28건)
```

**293건이 102건이 됐다.** 남긴 기준은 위 「남길 것」이다. 지운 것의 대부분은 「로그인된
상태에서 화면이 서버 값을 어떻게 그리는가」였고, 그 사실들은 대개 백엔드 테스트가 이미
고정하고 있다 — 여러 스펙이 자기 주석에 「백엔드가 실물로 검증한다」고 적어 두고 같은 값을
다시 단언하고 있었다. 미들웨어 가드는 `matcher` 하나에 걸린 함수 하나인데 7개 스펙이 경로
문자열만 바꿔 같은 함수를 쳤다.

**그 대가를 알고 지웠다.** 지운 것들의 회귀는 이제 아무도 잡지 않는다 — 되돌리려면 git 에서
꺼낸다(이 커밋 이전). 화면 회귀가 실제로 문제가 되기 시작하면 그때 기준을 다시 연다.

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

**워크스페이스 패키지를 새로 더하면 손으로 관리되는 목록 셋을 같이 고쳐야 한다.**
`pnpm-workspace.yaml` 은 글롭이라 저절로 잡지만, 그 아래 셋은 멤버를 하나씩 적어 둔다 —
`docker/frontend.Dockerfile` 과 `docker/operator.Dockerfile` 의 COPY(각각 base·dev·builder
셋)와 `docker/compose.dev.yaml` 의 **멤버별 `node_modules` 이름 있는 볼륨**(두 서비스 ×
볼륨 선언). **로컬 게이트는 셋 다 보지 않는다** — `typecheck` 는 호스트의 node_modules 를
쓰고, e2e 는 로컬에서 돌리지 않기 때문이다. #166 이 `packages/route-audit` 를 더하면서
정확히 이걸 빠뜨려 CI 가 4잡 빨갛게 났고, 증상이 둘로 갈려 원인이 하나로 안 보였다:

- **deploy-guard 둘** — 프로덕션 이미지의 builder 가 `Cannot find module '@laurio/route-audit'`
  로 죽는다. 앱 소스(`lib/routes/allowlist.ts`)가 그 패키지의 타입을 쓰는데 Dockerfile 이
  패키지를 복사하지 않았다. runner 스테이지는 `.next/standalone` 만 가져가므로 실행
  이미지에는 안 들어간다 — 그래도 builder 에는 있어야 한다.
- **e2e 둘** — 러너의 `pnpm install --frozen-lockfile` 이 `EACCES ... packages/route-audit/
  node_modules/.bin/tsc` 로 죽는다. 볼륨이 없으면 바인드 마운트가 그대로 남아, 컨테이너의
  `pnpm install` 이 **호스트 경로에 root 로** 쓴다. compose 의 그 볼륨 목록 옆 주석이 경고하는
  바로 그 상황이다.

재현은 CI 와 같은 명령으로 로컬에서 된다(스택 없이 몇 분):

```bash
docker build -f docker/frontend.Dockerfile --target runner -t x .   # deploy-guard 와 같은 것
docker build -f docker/operator.Dockerfile --target runner -t y .
```

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

## CI 는 셀프호스티드 러너에서, 프로덕션 이미지로 돈다

GitHub 호스티드 러너는 과금이 막혀 못 쓴다. 9개 잡 전부 `runs-on: [self-hosted, sub]` —
staging 배포 호스트와 **같은 머신**이다. 러너 컨테이너는 `--network host` 로 돌고 호스트
docker 소켓을 물어 컨테이너를 바깥에 띄운다(DooD).

**CI 는 `docker/compose.ci.yaml` 을 dev compose 위에 겹쳐 쓴다 — 지우면 CI 가 깨진다.**
`compose.dev.yaml` 의 `..:/app` 은 **개발용 핫리로드 장치**다. 러너 안에서 그 상대 경로는
호스트 데몬 기준으로 풀려 `/app` 이 통째로 비고, backend 는 `can't open file '/app/manage.py'`
로, 두 앱은 `Scope: all 0 workspace projects` 로 죽는다. 오버라이드가 하는 일은 셋뿐이다:

- 세 서비스의 `volumes` 를 `!reset []` — 마운트 없이 **이미지 안의 코드**로 돈다.
- 두 앱의 빌드 `target` 을 `runner` 로 — dev 서버가 아니라 **배포되는 그 이미지**를 친다.
- 두 앱의 `command` 를 `!reset null` — 이미지의 `node server.js` 가 산다.

**그래서 e2e 가 검증하는 대상이 바뀌었다.** 예전엔 `next dev` 를, 지금은 프로덕션 빌드를
친다 — 배포되는 것과 테스트되는 것이 같아졌다. 위 `next dev` 메모리 주의는 이제
**로컬에서 스위트를 돌릴 때만** 해당한다.

**잡마다 스택을 갈라 준다.** compose 를 쓰는 세 잡(`celery-broker`·e2e 둘)이 한 러너에서
겹치므로 각자 다른 `COMPOSE_PROJECT_NAME` 과 포트 슬롯을 잡는다 — 안 그러면 서로의
컨테이너를 `down -v` 로 지운다. 뒷정리는 `if: always()` 로 건다.

**pytest 잡에 redis 서비스가 없다.** 테스트 세션 캐시가 LocMem 이라(위 「테스트는 서로를
밟지 않는다」) 필요가 없어졌다. postgres 는 `55532` 로 노출한다 — 러너 호스트의 5432 는
이미 점유돼 있다.

실측(9잡 전부 초록, 2026-09-05): 전체 **6분**. e2e 운영자 4분 · 공개 3분 ·
`celery-broker` 2분 · `pytest` 1분 · 나머지 다섯은 각 1분 미만.

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
