# CI 는 Jenkins 에서 돈다 — PR 검사 하나, 병합 하나 = 배포 하나 (PR 검사는 Actions 에서도)

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**2026-11-05(#873, ADR-0071)부터 portfolio·foresight 와 같은 jenkins-shared 흐름이다** — PR 검사(`sandcorpPrCheck`)가
초록이면 작업자가 squash 로 병합하고, 그 main push 가 배포 잡(`sandcorpDeploy`, 「배포」 문서)을 깨운다. 열차
(`codemit/ci-train`, 2026-10-03~11-05)와 그 상태 `codemit/automerge` 는 없다. 라이브러리의 인자·동작은
`sandcorporation/jenkins-shared` 의 README 가 원문이고, 여기에는 codemit 에만 있는 것을 적는다.

**PR 검사는 GitHub Actions 에서도 돈다**(2026-11-09 #930, ADR-0076 — 저장소 공개 준비). `.github/workflows/pr-check.yml`
이 `pull_request`·`main` push 마다 호스팅 실행기에서 같은 스크립트를 잡으로 나눠 부른다 — `plan`(`changed.sh`, 문서만이면
ADR 검사만, 공개 위생 `scripts/test_public_repo.py` 는 늘) → `checks`(`sub-checks.sh`)·`guard`(세 앱을 amd64 로 굽고 `deploy-guard.sh`, `CODEMIT_GUARD_IMAGE`)·`e2e`
(`e2e.sh`, 스택을 여기서 굽는다)·`celery`(`celery-broker.sh`) → `결과`(모두 초록이면 초록 — 필수 검사로 걸 이름).
이미지를 레지스트리에 올리지 않으므로 ctx·e2e 태그는 Jenkins 만 붙인다. secrets 를 쓰지 않고(`scripts/ci/*.env` 의 가짜
값), 권한은 `contents: read`, `pull_request_target`·self-hosted 를 쓰지 않으며 액션은 SHA 로 고정한다. **병합 기준은 Actions
「결과」 잡이다**(2026-11-09 대표 결정, #930 댓글) — `gh pr checks <PR>`·`gh run watch` 로 본다. Jenkins PR 검사는 대장이 끄기
전까지 함께 돌지만 기다리지 않고 결과도 병합 조건이 아니다. 아래 Jenkins 절은 그 잡이 꺼질 때까지의 사실이다.

**PR 검사는 Jenkins `codemit/ci-pr`(Multibranch, `Jenkinsfile.pr`)가 돌린다.** 지금 잡은 **브랜치 발견**이다 —
GitHub 소스 `sandcorporation/laurio` 의 브랜치(`main`·`production`·옛 `staging` 은 뺀다)마다 하위 잡이 생기고,
5분마다 훑어 새 push 를 찾는다. 같은 브랜치에 새로 push 하면 옛 빌드를 끊는다. 결과는 브랜치 머리 커밋의 상태
`continuous-integration/jenkins/branch` 이다 — 병합 기준이 아니다(위 Actions 문단, 「티켓을 닫는 기준」).
라이브러리의 「PR 검사 실패 — …」 댓글은 PR 빌드(`CHANGE_ID`)에서만 달리므로 **지금은 달리지 않는다** — 잡을 PR 발견
(머지 결과, 라이브러리 README 「잡」)으로 바꾸는 것은 Jenkins 잡 설정이라 대장 몫이다. 그때까지 실패 줄은 home Jenkins
홈의 빌드 로그(`/var/jenkins_home/jobs/codemit/jobs/ci-pr/branches/<브랜치>/builds/<N>/log`)를 읽는다.

| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 노드 고르기 | — | **macos 먼저**(`prefer: 'macos'`), 25분 안에 못 잡으면 home — e2e 가 macos 에서만 돌아 home 으로 넘어간 빌드는 ① 만 돌고 붉다 |
| 검사 | macos | `scripts/ci/pr-check.sh`. 문서(`.md`·`docs/`)만 바뀌었으면(`changed.sh`, merge-base 와 견준다) ADR 검사만. 아니면 ① `sub-checks.sh`(파일 이름의 sub 는 옛 호스트 이름) — Django `check`·`check --deploy`, pytest 전체, 생성물 최신성 둘, ADR·화면 언어·고정 대기 검사, 단위 시험, 세 앱 typecheck ② `macos-sweep.sh` → `images.sh arm64`(prod 여섯을 이 커밋으로, 바뀌지 않은 문맥은 ctx 로 건너뜀, `ghcr-push-token`) ③ 이번에 구운 앱의 부팅 가드(`deploy-guard.sh`, #838) ④ **그 이미지를 받아** `e2e.sh`(세 프로젝트)·`celery-broker.sh` ⑤ 초록이면 ctx 태그(`images-ctx.sh`)와 e2e 태그(`images-e2e.sh`) |

파괴적 migrate 검사(라이브러리)는 끈다(`migrationGuard: false`) — codemit 은 겹쳐 바꾸기 안전을 `ROLLING-DEPLOY-UNSAFE`
표식과 `backend/tests/test_migration_rolling_safety.py` 로 지킨다(ADR-0053).

**배포 이미지는 PR 검사가 굽고, 배포 잡은 대개 커밋 태그만 더한다.** PR 검사는 이 브랜치 머리로 여섯을 굽고
커밋 태그 `<sha>-arm64` 로 올린다. e2e·celery 는 스택이 따로 굽지 않고 그 이미지를 받아 돈다
(`docker/compose.ci-images.yaml`, `CODEMIT_IMAGE_TAG`) — 그래서 **e2e 가 본 digest 가 prod 에 가는 digest 다**
(`test-results/images.txt`). 초록이면 그 digest 마다 `e2e-<트리>-arm64` 태그를 붙이고(`images-e2e.sh`, #729), prod 배포의
「e2e 대조」(`deploy.sh prod e2e-digest`)가 그 커밋의 트리로 태그를 받아 떠 있는 backend·세 앱의 이미지 ID 와 견줘 콘솔에
적는다(관측만 — 붉히지 않는다). 서비스마다 한 줄 — `e2e 대조: <서비스> — 같다 (<ID>)`, 다르면 `… — <판정> 떠 있는 것 <ID>
(<떠 있는 커밋 12자>), e2e 가 본 것 <ID>`, 태그나 컨테이너가 없으면 대조 못 함 — 이고 끝 줄이
`e2e 대조: 같다 N · 다시 구움 N · 다르다 N · 대조 못 함 N (트리 <12자>)` 다. 다르면 떠 있는 컨테이너를 만든 커밋과 이 커밋의
문맥을 `image_context.py changed` 로 견줘 「다르다(문맥 같음 — 다시 구운 것)」·「다르다!(문맥 다름)」·「다르다!(문맥 모름)」
으로 가른다(#738, #741).

- **왜 배포 잡이 건너뛰나 — sha 가 아니라 트리다.** squash 병합 커밋은 PR 머리와 sha 가 다르지만, PR 이 main 위에
  있었으면(뒤처지지 않았으면) 트리가 같고 서비스마다 문맥 해시도 같다 — 배포 잡의 `images.sh` 는 ctx 를 보고 굽지 않는다.
  PR 이 뒤처진 채 병합됐으면 다른 문맥만 배포 잡이 굽고 가드한다 — 해시가 판단하므로 틀린 이미지가 건너뛰어지지 않는다.
- **ctx 는 「그 문맥을 어느 빌드가 끝까지 초록으로 봤다」이다**(#709). PR 검사는 e2e·celery 까지 초록일 때, 배포 잡은
  굽기·가드가 초록일 때만 붙인다. 붉은 빌드의 이미지는 커밋 태그만 남아 다음 빌드가 다시 굽는다. 병합되지 않은 PR 의
  커밋 태그 이미지는 `codemit/ghcr-prune` 이 먼저 지운다(main 에 없는 커밋).
- **PR 검사는 다시 돌지 않는다.** 열차의 「인프라 고장이면 같은 묶음을 한 번 더」(#716·#729, `e2e_stall.py`)는 열차와 함께
  걷었다. 붉으면 작업자가 로그를 보고 고치거나(코드 탓), 같은 커밋을 Jenkins 에서 다시 돌린다(인프라 탓).
- **「시험 하나 3초·재시도 없음」은 그대로다**(playwright.config.ts).

- **macos 의 Docker VM 디스크는 96GiB 이고, 묶음마다 무엇이 남는지 정해 두어야 찬다.** 맥 호스트
  디스크가 남아도 Docker Desktop 의 `Docker.raw` 가 차면 MinIO 가 `XMinioStorageFull` 로 업로드를
  거절하고 db 컨테이너가 죽는다 — 코드와 무관하게 묶음이 붉다. 실행마다 compose 프로젝트 이름이
  달라(`CODEMIT_CI_RUN_ID`) 쌓이는 것은 그 실행의 볼륨과 이미지다. 지금(#712, #873) PR 검사의 스택은 굽지 않고
  `images.sh` 가 올린 `ghcr.io/sandcorporation/codemit-<서비스>:<sha>-arm64` 를 받는다 — 커밋마다 새 태그라
  `macos-sweep.sh` 가 저장소마다 **가장 새것 하나**만 남긴다(다음 실행이 바뀌지 않은 층을 다시 받지 않는 층
  캐시). 굽는 쪽 캐시는 빌더 `codemit-images` 의 것이고 `images.sh` 가 20GB 로 자른다. `e2e.sh`·
  `celery-broker.sh` 는 내릴 때 `down -v --rmi local` 로 볼륨과 (굽는 길이면) 자기가 구운 이미지를 지운다.
  trap 이 못 돈 중단 빌드의 찌꺼기는 다음 빌드 첫머리의 `macos-sweep.sh` 가 걷고, 기본 빌더 캐시(이제
  로컬 굽기 길만 쓴다)는 나이가 아니라 크기(10GB, 오래 안 쓴 것부터)로 자른다. 사고 둘: 2026-10-03 중단된
  스택의 볼륨 400여 개(30GB), 2026-10-14 지워지지 않은 이미지 1,283개(51GB)와 캐시 48GB.
- **노드는 실행기가 하나라 통째로 쓴다.** 예전에는 GitHub Actions 의 셀프호스티드 러너
  셋(home)이 home 의 코어를 제한 없이 나눠 써, 이미지 빌드와 겹친 시험이 경합만으로 한도를
  넘었다(#499 의 첫 CI — 공개 e2e 10건·단위 2건 타임아웃). 오래 걸리는 e2e 를 성능이 좋은
  macos 에, 짧은 것을 배포 잡의 built-in 단계와 실행기를 나눠 쓰는 home 에 둔다(#840 전에는 staging 배포 전체와 나눠 썼다).
- **e2e 가 흔들리면 무엇을 보나**(#699). PR 검사 빌드의 작업 공간(`test-results/**`, macos)에
  셋이 있다. ① `test-results/playwright/<프로젝트>[-exclusive]/<시험>/` — 실패한 시험의 `trace.zip`
  (`pnpm --dir frontend exec playwright show-trace <파일>` 로 연다)과 `error-context.md`. 성공한 시험의
  것은 남지 않는다(`retain-on-failure`). 패스마다 폴더가 다른 것은 Playwright 가 실행마다 출력 폴더를
  비우기 때문이다 — 한 폴더면 뒤의 `@exclusive` 패스(시험 0개여도)가 앞 패스의 trace 를 지운다. 두 패스의 정의는
  `frontend/scripts/e2e-two-pass.sh` 하나다(#702 — `package.json`·`scripts/test.sh` 도 그것을 부른다).
  ② `test-results/stack/<서비스>.log` — 스택의 서비스마다 로그 전체, 줄마다 Docker 타임스탬프(나노초).
  `backend.log` 에는 gunicorn 접근 로그가 요청마다 한 줄 있다(`POST /api/… HTTP/1.1 201 128 24ms pid=<13>`
  — 상태·응답 바이트·걸린 ms·워커). `db.log` 에는 300ms 넘은 문장(`LOG:  duration: 400.691 ms  statement: …`)과
  300ms 넘게 잠금을 기다린 세션(`still waiting for AccessShareLock … after 300.082 ms` · 쥔 프로세스 ·
  `acquired … after`)이 찍힌다 — `compose.ci.yaml` 의 db·backend 오버라이드가 켠다(dev·배포는 그대로).
  ③ `test-results/summary.txt` — 프로젝트별 통과·실패와 걸린 초. 여러 시험이 한꺼번에 3초를 넘었으면
  trace 의 정지 시각을 `backend.log`·`db.log` 의 같은 시각과 맞춰 본다(열차 #1840 은 이것이 없어 원인을
  못 남겼다). ④ `test-results/host/*.log` — macos 호스트의 1초 샘플(#716, `scripts/ci/host-sample.sh` — vm-top 만 1.5~2초):
  `memory.log`(memory_pressure 의 남은 %·vm_stat 의 free/compressed/swapins/swapouts·스왑·load),
  `vm-top.log`(Docker VM 프로세스의 CPU·메모리 — 첫 줄은 이름이 맞는 후보 전부의 pid·RSS·실행 파일이고, 그중
  RSS 가 가장 큰 것을 VM 본체로 본다. CPU 는 `top -l 2 -s 1` 의 둘째 샘플이라 줄이 1.5초쯤마다 찍힌다 — 열차
  #1899 는 `pgrep | head -1` 이 RSS 39M 짜리 보조 프로세스를 집었고 `top -l 1` 의 첫 샘플이라 내내 0.0 이었다,
  #719), `docker-stats.log`(컨테이너마다, 따로 돌아 VM 이 멈추면
  줄 사이가 빈다). 줄마다 UTC 초 시각이라 스택 로그·trace 와 맞춰 본다. 명령이 없거나 권한이 없으면 그 칸이
  빌 뿐 e2e 를 붉게 만들지 않는다. 로컬 `scripts/test.sh e2e` 는 같은 trace 를 `frontend/test-results/`(뒤 패스는
  `frontend/test-results/exclusive/`)에 두고, 스택 로그는 `CODEMIT_E2E_KEEP=1` 로 남긴 스택에서
  `docker compose -p <워크트리>-e2e … logs --timestamps <서비스>` 로 본다.
- **backend 요청 0건 틈**(#716·#723). 열차 시절 e2e 넷이 한꺼번에 3초를 넘던 모양(backend 접근 로그에 4초 동안 요청 0건)은
  VM 정지가 아니라 강의실 BFF 가 끊긴 연결을 backend 에 넘겨 gunicorn 워커가 모두 붙잡힌 코드 탓이었다(#723 이 고쳤다).
  그 모양을 인프라로 가르던 판정(`e2e_stall.py`)과 재실행은 열차와 함께 걷었다(#873) — 다시 보이면 trace 의 정지 시각을
  `test-results/stack/backend.log`·`db.log` 와 맞춰 코드부터 본다.
- **macos 의 Docker Desktop 설정**(#716 — 사람이 mac 에서 한 번 읽어 적는다). 지금까지 trace 로 본 틈은
  VM 정지가 아니라 코드 탓(#723)이었다. 표는 다음에 판정이 발동하면 VM·호스트 쪽을 배제하거나 짚는 데
  쓰려고 남긴다 — 그 전에는 채울 급한 이유가 없다:

  | 항목 | 값 | 읽은 날 |
  | --- | --- | --- |
  | VM 메모리 | 11.67GiB — `test-results/host/docker-stats.log` 의 분모(`/ 11.67GiB`)로 읽을 수 있다(`playwright.config.ts` 주석은 24GB) | 2026-10-15(열차 #1899) |
  | VM CPU 수 | (적을 자리) | |
  | 스왑 | (적을 자리) | |
  | 가상화 프레임워크(Apple Virtualization·Docker VMM·QEMU) | (적을 자리) | |
  | 파일 공유(VirtioFS·gRPC FUSE·osxfs) | (적을 자리) | |
  | 네트워크 모드·포트 전달 | (적을 자리) | |
  | Resource Saver | (적을 자리) | |
  | Docker Desktop 버전 · macOS 버전 · 호스트 RAM | (적을 자리) | |

- **home 의 Jenkins 는 컨테이너라 node·pnpm·uv 가 없다** — 그래서 home 쪽은 저장소를 담은
  시험 이미지(`docker/ci.Dockerfile`)를 굽고 사이드카 postgres(tmpfs·fsync 끔)와 같은 망에서
  `scripts/ci/sub-checks-inside.sh` 를 돈다. 바인드 마운트는 쓰지 않는다(컨테이너와 호스트의
  경로가 다르다, 아래 「Jenkins 는 home 호스트에 있다」). 그 이미지는 루트
  `.dockerignore` 대신 `docker/ci.Dockerfile.dockerignore` 를 읽어 **문서를 들인다** — 문서 검사와
  다이어그램 최신성 시험이 그것을 읽는다(빼먹었을 때 넷이 「파일이 없다」로 빨갰다).
- **실측**(2026-10-02, 첫 초록): home 쪽 전체 약 3분(pytest 2489건 47초), macos e2e 공개 14초 ·
  운영자 4초 · 강의실 4초(이미지 굽기 제외).
- **잡 설정은 저장소 밖이다** — Multibranch 잡·배포 잡·자격증명(`github-sandcorporation-token` 은
  fine-grained PAT: 저장소 읽기·PR·커밋 상태·Contents 쓰기, `glitchtip-automation-token`, 이미지 잡의 `ghcr-push-token`)은 사람이
  Jenkins 에 만든다. Jenkins 설정을 API 로 고칠 때는 `Content-Type: application/xml;
  charset=utf-8` 을 붙인다 — 없으면 한글이 Latin-1 로 읽혀 500 이 난다.
- **잡은 폴더 `codemit/` 안에 넷이다**(2026-10-23, #780) — Jenkins 첫 화면에는 폴더 하나만 보인다. 2026-10-15(#708)
  부터는 `codemit-<역할>-<대상>` 으로 나란히 섰고, #779 가 `codemit-deploy-prod` 를 `codemit-deploy-staging` 의 「prod 배포」
  단계로 합쳐 넷이 남자 폴더로 묶으며 접두 `codemit-` 을 뗐다. 접두를 뗀 이유는 `BUILD_TAG`(`jenkins-<전체 이름의 / 를 - 로>-<번호>`)
  가 **그대로**이기 때문이다 — `codemit/ci-train` → `jenkins-codemit-ci-train-N`. 그래서 `macos-sweep.sh` 의 compose
  프로젝트 패턴과 #735 는 건드리지 않았다. API 경로는 `/job/codemit/job/<이름>/…`, 잡 디렉터리는
  `/var/jenkins_home/jobs/codemit/jobs/<이름>/` 이다.

  | 잡 | 옛 이름 | 파일 | 워크스페이스·이름에 묶인 것 |
  | --- | --- | --- | --- |
  | `codemit/ci-pr`(Multibranch) | `codemit-ci-pr` | `Jenkinsfile.pr` | 검사의 컨테이너·네트워크·이미지(`codemit-ci:<run_id>`)와 e2e·celery 스택 `jenkins-codemit-ci-pr-*`(`BUILD_TAG` 에서) |
  | `codemit/deploy` | `codemit-deploy-staging` | `Jenkinsfile` | jenkins-shared `sandcorpDeploy` — 확인·알림은 built-in 의 잡 워크스페이스, 굽기는 macos(못 잡으면 home), 배포는 에이전트 `oracle` 의 `ws('/home/jenkins/agent/workspace/codemit-deploy-prod')` = oracle 호스트 `/var/jenkins_home/workspace/codemit-deploy-prod/`(사람이 둔 `docker/.env.prod`·배포 표식) |
  | `codemit/ghcr-prune` | `codemit-ghcr-prune` | 저장소 밖 | |

  더 전의 이름은 `codemit-pr`·`codemit-train`·`laurio`·`codemit` 이다. 열차 잡 `codemit/ci-train`(2026-10-03~11-05)은
  #873 이 `Jenkinsfile.train` 을 지워 할 일이 없다 — 잡·자격증명 `codemit-train-webhook-token`·열차용 GitHub 웹훅을 지우는 것은
  대장 몫이다(그때까지 30분 cron 이 지워진 파일을 찾다 붉게 끝난다). 잡을 이름으로 부르는 자리는 이제 없다.
  GitHubPushTrigger(저장소 URL)·전역 자격증명·GitHub 커밋 상태 문맥(`continuous-integration/jenkins/branch`,
  `sandcorp/deploy`)은 잡 이름과 무관하다. PR CI·prune 의 워크스페이스는 새로 받아도 되는
  체크아웃이라 붙잡지 않았다(옮긴 뒤 첫 빌드가 통째로 clone 해 한 번 느리다). `macos-sweep.sh` 는
  rename 직전에 남은 `jenkins-codemit-(pr|train)-*` 도 한동안 같이 걷는다 — 2026-11-15 이후 #735 로 지운다(지울 조건은 그 파일 머리말).
  #708 끝 조건의 「새 이름으로 한 번씩 초록」은 prod 를 뺀 셋이었다 — 옛 `codemit-deploy-prod` 는 10-21 prod #177
  이 마지막 빌드였고 #779 로 사라졌다.
- **문서(`*.md`·`docs/`)만 바뀐 커밋은 시험도 교체도 건너뛴다.** PR 검사는 `scripts/ci/changed.sh`(merge-base 와 견준다)로
  ADR 검사만 한다. 배포 잡은 「배포할 커밋 확인」(라이브러리 DeployGate — 같은 sha 면 `NOT_BUILT`)을 지나 `build-images.sh` 가
  문맥 해시로 전부 「건너뛴다」(커밋 태그만)가 되고, oracle 의 `deploy.sh plan` 이 **배포 표식**(`.jenkins-prod-deployed`, 마지막으로
  성공한 prod 배포) 기준으로 바뀐 서비스가 없다고 내 교체 없이 표식만 옮긴다(#873 — 그 전에는 GitHub 의 `production` 브랜치와
  `changed.sh` 로 견줘 노드도 잡지 않았다, #840). 배포 표식은 성공한 배포의 마지막에만 옮기므로 배포가 실패한 커밋 뒤의 문서
  커밋도 그 배포를 다시 시도한다(#709 의 교훈).
- **배포는 GitHub Actions 를 쓰지 않는다**(2026-10-15, #705, ADR-0061 — PR 검사만 #930 에서 돌아왔다, ADR-0076). 조직이 Free 요금제라 호스티드 분량(월
  2,000분)이 바닥나자 `staging` 이 멈췄고, 결제하지 않고 떠났다. Actions 가 하던 셋 — 배포 이미지, 부팅
  가드, `staging` 앞당기기 — 은 `main` push 에서 도는 Jenkins `codemit/deploy` 잡(`Jenkinsfile`)의 앞 단계가 됐다
  (「배포」 절, `staging` 앞당기기는 #840 에서 걷었다). 이미지는 macos 가 arm64 여섯을 굽고(`scripts/ci/images.sh`; #840 전에는 home 가 amd64 여섯도 구웠고 #841 에서 걷었다),
  **바뀌지 않은 서비스는 빌드 문맥 해시로 건너뛴다**. 구운 이미지는 커밋 태그로만 올리고, 문맥 태그
  (`ctx-<해시>`)는 굽기와 부팅 가드가 **모두 초록인 뒤에** 「문맥 태그」 단계(`scripts/ci/images-ctx.sh`,
  macos)가 붙인다(#709) — 그래서 「건너뛴다」는 언제나 앞 빌드가 끝까지 초록으로 본 이미지이고, 가드가 빨갛거나
  굽기가 실패한 빌드의 이미지는 다음 빌드가 다시 굽고 가드도 다시 돈다. 부팅 가드 셋(`scripts/ci/deploy-guard.sh`, prod 의 arm64 를 PR 검사(macos, #838)와 배포 잡의 「이미지 굽기」(#840, #873)가 본다)은
  **방금 올린 그 이미지를 ghcr 에서 받아** 배포 설정 없이는 죽고 완전한 설정으로는 뜨는지 본다 — 이번에
  구운 앱만(건너뛴 앱의 이미지는 이미 한 번 지났다). 앱 이미지는 환경을 모르므로(#711) 가드가 공개 값을
  `-e CODEMIT_PUBLIC_*` 로 주고, 방침의 문의 주소가 `/privacy` 에, 토스 클라이언트 키가 첫 화면의
  `window.__CODEMIT_PUBLIC__` 에 실리는지(시크릿은 실리지 않는지)로, `.dockerignore` 는 가짜 시크릿을 심은 **빌드 컨텍스트**(`COPY . /ctx`
  만 하는 이미지)로 본다 — 표식에 빌드마다 다른 값을 섞는다(스크립트 자신이 문맥에 들어 고정 문자열이면
  늘 걸린다). 컨테이너 포트를 노드에 열지 않고 띄운 컨테이너의 네트워크에 curl 컨테이너를
  붙여(`--network container:<이름>`) 친다(home 의 Jenkins 가 컨테이너라 바인드 마운트도 쓰지 않는다).
- **`Jenkinsfile`(배포)은 PR 검사가 보지 못한다** — 그 파일·`build-images.sh`·`deploy-prod.sh` 를 바꾼 PR 의 첫 실행이 곧 그 병합의
  prod 배포다(`Jenkinsfile.pr` 은 멀티브랜치라 브랜치의 것으로 돈다). 라이브러리 쪽은 `@Library('sandcorp@<브랜치>')` 로 시험할 수
  있다(라이브러리 README). 스크립트 쪽은 로컬에서 돈다: `CODEMIT_IMAGES_MODE=plan`(해시와 판단만),
  `CODEMIT_IMAGE_REGISTRY=localhost:<포트>`(로컬 `registry:2` 에 실제로 굽고 건너뛰기), `CODEMIT_GUARD_IMAGE=<이미지>`(가드가
  받을 이미지), `CODEMIT_IMAGE_TAG=<sha>-<arch> scripts/test.sh e2e`(올린 이미지로 e2e — PR 검사의 길). 두 스크립트는 macos 의
  bash 3.2 에서도 돈다.

**CI 는 `docker/compose.ci.yaml` 을 dev compose 위에 겹쳐 쓴다 — 지우면 CI 가 깨진다.**
`compose.dev.yaml` 의 `..:/app` 은 **개발용 핫리로드 장치**다. 러너 안에서 그 상대 경로는
호스트 데몬 기준으로 풀려 `/app` 이 통째로 비고, backend 는 `can't open file '/app/manage.py'`
로, 두 앱은 `Scope: all 0 workspace projects` 로 죽는다. 오버라이드가 하는 일은 셋뿐이다:

- 다섯 서비스(backend·events·frontend·operator·classroom, #379)의 `volumes` 를 `!reset []` —
  마운트 없이 **이미지 안의 코드**로 돈다.
- 세 앱(frontend·operator·classroom, #277)의 빌드 `target` 을 `runner` 로 — dev 서버가
  아니라 **배포되는 그 이미지**를 친다.
- 세 앱의 `command` 를 `!reset null` — 이미지의 `node server.js` 가 산다.

PR 검사는 셋째 장 `docker/compose.ci-images.yaml` 을 더 얹는다(#712) — 위 셋은 그대로 받고 `build` 를 걷어
`images.sh` 가 올린 `codemit-<서비스>:${CODEMIT_IMAGE_TAG}` 를 받는다(backend 계열 다섯은 `codemit-backend`
하나). `CODEMIT_IMAGE_TAG` 가 없으면 `e2e.sh`·`celery-broker.sh`·`scripts/test.sh e2e` 는 예전처럼 스택이 굽는다.

**그래서 e2e 가 검증하는 대상이 바뀌었다.** 예전엔 `next dev` 를, 지금은 프로덕션 빌드를
친다 — 배포되는 것과 테스트되는 것이 같아졌다. 위 `next dev` 메모리 주의는 이제
**로컬에서 스위트를 돌릴 때만** 해당한다.

**스택마다 이름을 갈라 준다.** e2e 와 celery-broker 의 compose 프로젝트 이름은 빌드
식별자(`CODEMIT_CI_RUN_ID` — 빌드 태그 + 시작 시각)에서 나오고, 포트는 compose 가 비어 있는 것을
고른다. 끝나면(성공·실패·중단 모두) `down -v` 로 지운다.

**화면 언어 검사**(#267, #268 — PR CI 의 home 단계)는 스텝 둘로 두 표면을 막는다. 첫 스텝
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
