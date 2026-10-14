# CI 는 Jenkins 에서 돈다 — 브랜치마다, 노드를 통째로

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**시험은 Jenkins `codemit-pr`(Multibranch, `Jenkinsfile.pr`)가 돌린다**(2026-10-02). GitHub
소스 `sandcorporation/laurio` 의 브랜치(`main`·`staging`·`production` 은 뺀다)마다 하위 잡이
생기고, 5분마다 훑어 새 push 를 찾는다. 결과는 GitHub 커밋 상태로 남는다. 같은 브랜치에 새로
push 하면 옛 빌드를 끊는다.

**PR 마다** — sub 검사만 돌고, 초록이면 그 커밋을 줄 세운다:

| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 변경 | sub(`laurio-staging`) | `scripts/ci/changed.sh` — 문서(`.md`·`docs/`)만 바뀌었으면 시험을 건너뛰고 문서 검사만 |
| 시험(병렬) | sub | `scripts/ci/sub-checks.sh` — Django `check`·`check --deploy`, pytest 전체(junit), 생성물 최신성 둘, ADR·화면 언어 검사, 단위 시험 여섯, 세 앱 typecheck |
| 줄 서기 | sub | 초록이면 머리 커밋의 상태 `codemit/automerge` 를 `pending`(「다음 묶음을 기다린다」)으로 두고 `codemit-train` 을 부른다 |

**묶음마다** — Jenkins `codemit-train`(Pipeline, `Jenkinsfile.train`, 2026-10-03)이 줄 선 PR 을
최신 `main` 위에 차례로 쌓아 **한 번** 시험하고 초록이면 차례로 합친다. PR CI 가 부르고, 10분마다
스스로도 돈다. 규칙은 `scripts/ci/train.py` 머리말에 있다.

| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 묶기 | sub | 열린 main PR 중 머리 커밋이 줄에 선 것(초안·`hold` 는 빼고, 8개까지)을 번호 순으로 cherry-pick 해 쌓는다. 얹히지 않는 PR 은 `failure` 로 돌려보낸다 |
| 시험(병렬) | sub | 같은 계획으로 다시 쌓고(트리 해시 확인) `scripts/ci/sub-checks.sh` |
| | macos | 같은 계획으로 다시 쌓고 `scripts/ci/macos-sweep.sh`(중단된 앞 빌드가 남긴 `jenkins-codemit-pr-*`·`jenkins-codemit-train-*` 스택·볼륨·이미지를 걷고 빌드 캐시를 30GB 로 자른다 — 중단은 trap 을 건너뛰어, 남은 볼륨이 Docker VM 을 채우자 MinIO 가 `XMinioStorageFull` 로 업로드를 거절했다, 2026-10-03) → `scripts/ci/e2e.sh`(세 앱 프로덕션 이미지 스택 + 세 프로젝트) → `scripts/ci/celery-broker.sh` |
| 병합 | sub | 초록이면 차례로 rebase 병합(`sha` 로 머리를 고정 — 그 사이 push 된 PR 에서 멈춘다) → 합친 범위의 `GlitchTip:` 줄 해결 표시 → 남은 줄이 있으면 다음 묶음 |
| 붉으면 | sub | 둘 이상이면 앞의 절반으로 다시 돈다. 하나만 묶은 시험이 붉으면 그 PR 에 `failure` |

- **왜 묶나**(2026-10-03). PR 마다 macos e2e 를 따로 돌리면 이미지 셋 굽기 포함 약 8분이 노드
  실행기 하나에 줄을 서(PR 넷이면 32분), 각 PR 은 자기가 갈라진 **옛 main** 위에서만 시험됐다 —
  먼저 합쳐진 PR 과 충돌하는 PR 이 초록인 채 남았다(#530 이 #531·#532 와 그렇게 충돌했다).
- **줄에서 빠지는 법·돌아오는 법.** 새로 push 하면 새 커밋에는 상태가 없어 저절로 빠지고, PR CI
  가 다시 세운다. `failure` 를 받은 커밋은 PR CI 를 다시 돌리면(`POST /job/codemit-pr/job/<브랜치>/build`)
  줄로 돌아온다 — 인프라 고장으로 붉은 묶음이 가르기 끝에 PR 하나를 억울하게 잡았을 때의 길이다.
  초안을 풀거나 `hold` 를 떼면 다시 빌드하지 않아도 다음 묶음이 데려간다.

- **macos 의 Docker VM 디스크는 96GiB 이고, 묶음마다 무엇이 남는지 정해 두어야 찬다.** 맥 호스트
  디스크가 남아도 Docker Desktop 의 `Docker.raw` 가 차면 MinIO 가 `XMinioStorageFull` 로 업로드를
  거절하고 db 컨테이너가 죽는다 — 코드와 무관하게 묶음이 붉다. 실행마다 compose 프로젝트 이름이
  달라(`CODEMIT_CI_RUN_ID`) 쌓이는 것은 그 실행의 볼륨·이미지(`jenkins-codemit-…-e2e-<서비스>`, 다섯
  개·수 GB)와 빌드 캐시다. `e2e.sh`·`celery-broker.sh` 는 내릴 때 `down -v --rmi local` 로 볼륨과
  **자기가 구운 이미지**를 지우고(공용 base 이미지 postgres·redis·minio 는 남는다), 빌드 캐시는 남겨
  다음 굽기가 캐시 히트다. trap 이 못 돈 중단 빌드의 찌꺼기는 다음 빌드 첫머리의 `macos-sweep.sh` 가
  걷고, 빌드 캐시는 나이가 아니라 크기(30GB, 오래 안 쓴 것부터)로 자른다. 사고 둘: 2026-10-03 중단된
  스택의 볼륨 400여 개(30GB), 2026-10-14 지워지지 않은 이미지 1,283개(51GB)와 캐시 48GB.
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
- **잡 설정은 저장소 밖이다** — Multibranch 잡·묶음 잡 `codemit-train`(Pipeline, `*/main` 의 `Jenkinsfile.train`)·자격증명(`github-sandcorporation-token` 은
  fine-grained PAT: 저장소 읽기·PR·커밋 상태·Contents 쓰기, `glitchtip-automation-token`)은 사람이
  Jenkins 에 만든다. Jenkins 설정을 API 로 고칠 때는 `Content-Type: application/xml;
  charset=utf-8` 을 붙인다 — 없으면 한글이 Latin-1 로 읽혀 500 이 난다.
- **문서(`*.md`·`docs/`)만 바뀐 커밋은 시험도 이미지도 건너뛴다** — PR CI 는 `scripts/ci/changed.sh`, 이미지는 `images.yaml` 의 `paths-ignore`. 그런 커밋은 staging·production 을 앞당기지 않고 다음 코드 커밋과 함께 간다.
- **GitHub Actions 에는 이미지 빌드와 부팅 가드만 남았다**(`images.yaml`, 호스티드 러너 — 위
  「배포」 절). 부팅 가드 셋은 **images-staging 이 올린 바로 그 이미지를 ghcr 에서 받아**
  배포 설정 없이는 죽고 완전한 설정으로는 뜨는지 본다(2026-10-02 — 예전에는 같은 Dockerfile 을
  CI 전용 값으로 따로 구워, 검사한 것과 배포되는 것이 달랐다). 방침의 문의 주소는 저장소 변수
  `STAGING_SUPPORT_EMAIL` 이 실렸는지로, `.dockerignore` 는 가짜 시크릿을 심은 **빌드 컨텍스트**
  (`COPY . /ctx` 만 하는 이미지)로 본다. 컨테이너 포트를 러너에 열지 않고 띄운 컨테이너의 네트워크에 curl 컨테이너를
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
