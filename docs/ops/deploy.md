# 배포 (dev / staging / prod)

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

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
버킷 생성·정책·CORS 는 이 저장소 밖의 수작업이다. 어댑터가 전부
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
ADR-0048이 amend). 스위치가 둘이다:

- **공모전** — `CODEMIT_CONTEST_PRODUCT_ENABLED`(기본값 켜짐, `CODEMIT_DEPLOYMENT_
  TARGET`과 무관한 독립 값). staging·prod도 이제 기본 켜짐이다(dev·CI는 원래부터
  켜진 채).
- **유료 공모전** — `CODEMIT_PAID_CONTEST_PRODUCT_ENABLED`(같은 원칙의 독립 값).
  `docker/compose.staging.yaml`·`docker/compose.prod.yaml`만 기본을 `false`로
  겹쳐 쓴다 — dev·CI는 건드리지 않으므로 둘 다 켜진 채다(기존 유료 공모전
  테스트가 계속 초록인 이유).

코드도 데이터도 지우지 않았다(ADR-0048) — 닫는 것은 표면뿐이다:

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
줄이다(ADR-0037·ADR-0048).

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
쓰기가 막혀도 이 삭제는 된다.** 토큰은 Jenkins 자격증명 `ghcr-prune-token`(Secret text·Secret file·아이디/비밀번호 어느 종류든) — **classic PAT**
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

- **새 마이그레이션은 먼저 돌리고 겹쳐 바꾼다**(#526, ADR-0053). `deploy.sh` 가 새 이미지의
  일회성 컨테이너(`compose run --rm backend`, 풀러 경유)에서 `migrate` 를 돌리는 동안 옛
  컨테이너는 그대로 요청을 받는다. 성공해야 겹쳐 바꾸고, 실패하면 아무것도 내리지 않고
  배포가 실패로 끝난다. 배포 compose 의 backend 기동 command 는 migrate 를 부르지 않는다 —
  migrate 는 그 한 곳에서만 돈다. 그 몇 초 동안 옛 코드가 새 스키마 위에서 돌므로
  **마이그레이션은 뒤로 호환되어야 한다**(삭제·이름 바꾸기·NOT NULL 은 다음 배포로 나눈다).
  `backend/tests/test_migration_rolling_safety.py` 가 표식 없는 위험 연산을 막는다. 예전에는
  마이그레이션이 든 배포가 전부 내리고 올렸고, 2026-10-02 prod 에서 그 창이 공개 앱 재시도
  예산보다 길어 `/contests` 가 500 을 냈다(`0014_connected_apps`, GlitchTip 75·83).
- **물러서는 배포가 셋이다** — 배포 범위의 마이그레이션에 `# ROLLING-DEPLOY-UNSAFE: <이유>`
  표식이 있을 때, 풀러를 바꿀 때(「풀러를 바꿔 끼울 때는」), 겹칠 옛 컨테이너가 없을 때(직전
  배포 표식이 없을 때 포함). 그때는 넷을 먼저 내리고 migrate 를 돌린 뒤 올린다. 그동안 backend
  가 없고, 그 창은 공개 앱 재시도 예산보다 길 수 있다. migrate 가 실패하면 내렸던 옛
  컨테이너를 다시 켠다. `deploy.sh plan` 이 어느 쪽인지와 이유를 출력한다.
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
끼우지만, 그 프로세스가 죽으면 강의실 화면만 폴링으로 물러난다(ADR-0046). 그래도 `deploy.sh` 는 다른 서비스와 똑같이
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
