# 배포를 jenkins-shared 로 — 병합 하나가 배포 하나, 열차를 걷는다

Status: Accepted (2026-11-05 결정)

## 맥락 (#873)

대표 지시(2026-11-05): codemit 배포 구조를 portfolio·foresight 와 같게 맞춘다. 병합 하나 = 배포 하나로 하고 PR 열차를
없앤다. 공용 대기 스크립트(`wait-ci.py`·`wait-deploy.py`)가 그대로 먹어야 한다.

그 전(ADR-0068 뒤)의 codemit 은 jenkins-shared 를 쓰지 않았다.

- PR CI(`Jenkinsfile.pr`)는 home 검사만 돌고 초록이면 커밋을 줄 세웠다(`codemit/automerge` = pending). 열차
  `codemit/ci-train`(`Jenkinsfile.train`, `scripts/ci/train.py`)이 줄 선 PR 을 최신 main 위에 cherry-pick 으로 쌓아
  macos 에서 이미지·부팅 가드·e2e·celery 를 한 번 돌리고 rebase 병합했다. `codemit/automerge` 가 병합 전까지
  pending 이라 `wait-ci.py` 는 SUCCESS 를 보지 못했다.
- 배포 잡(`Jenkinsfile`, 446줄)은 GitHub 커밋 상태도 실패 댓글도 남기지 않아 `wait-deploy.py` 의 GitHub 길이
  NO_BUILD 였다. 「문서만」 판단과 「배포된 커밋」 기록은 `production` 브랜치였다.
- jenkins-shared 의 `sandcorpDeploy` 는 이미지를 `images[]` 마다 `build-image.sh` 로 굽고 `<repo>:<sha>` 태그를 쓴다.
  codemit 의 여섯 이미지·문맥 해시로 변경분만 굽기·부팅 가드·`<svc>:<sha>-arm64` 태그는 그 틀에 들지 않는다.
  라이브러리의 교체는 `--force-recreate` 라 중단이 있다 — codemit 의 겹쳐 바꾸기(무중단)는 그것으로 지킬 수 없다.

## 결정

- **잡 이름은 그대로**(`codemit/deploy`, `codemit/ci-pr`). 저장소 파일만 라이브러리 호출로 바꾼다 — 잡 설정을 건드리지
  않는다.
- **배포는 `sandcorpDeploy`, 실제 굽기·교체는 codemit 스크립트**(라이브러리 인자 `buildScript`·`deployScript`).
  - 라이브러리에서 받는 것: DeployGate(같은 sha 는 `NOT_BUILT`), 커밋 상태 `sandcorp/deploy`, 배포 실패 PR 댓글,
    디스코드, 빌드 노드 순서(macos → home), `ROLLBACK_SHA` 수동 되돌리기.
  - codemit 에 남기는 것: 여섯 이미지와 문맥 해시 건너뛰기·부팅 가드·ctx 태그(`scripts/ci/build-images.sh`),
    `deploy.sh prod` 의 단계 — 겹쳐 바꾸기, 마이그레이션 전 pg_dump·순서, 헬스, e2e 대조, 배포 표식(`scripts/ci/deploy-prod.sh`).
  - jenkins-shared 에 더한 것(PR #21, 셋 다 기본값이 이전 동작): `buildScript`(+ 빌드 노드 → oracle 로 `KEY=VALUE` 넘기기 —
    oracle 에 python3 가 없어 문맥 해시를 빌드 노드에서 낸다, #849), `autoRollback`, `buildCredentials`, PR 검사의 `credentials`.
- **자동 롤백은 끈다**(`autoRollback: false`). `deploy.sh` 는 배포 표식 기준으로 바꿀 서비스를 정해서, 라이브러리처럼 같은
  스크립트를 옛 sha 로 다시 부르면 표식이 아직 옛 커밋이라 아무것도 되돌리지 않는다 — 거짓 「되돌림」을 내느니 지금처럼
  없음으로 둔다. 수동 되돌리기(`ROLLBACK_SHA`)는 `deploy-prod.sh` 가 그 커밋을 체크아웃해 같은 절차를 돈다.
- **PR 검사는 `sandcorpPrCheck`**, 검사 내용은 `scripts/ci/pr-check.sh` — home 검사 묶음(`sub-checks.sh`) + 열차가 하던
  arm64 이미지·부팅 가드·e2e·celery(그 이미지로) + ctx·e2e 태그. e2e 가 macos 에서만 돌아 `prefer: 'macos'`(25분),
  home 으로 넘어오면 붉다. 파괴적 migrate 검사(라이브러리)는 끈다 — codemit 은 ADR-0053 의 표식과 시험으로 지킨다.
- **병합은 작업자가** `wait-ci.py` SUCCESS 뒤 `gh pr merge --squash` 로 한다. `codemit/automerge` 는 더 만들지 않는다.
- **「문서만」 병합은 교체를 건너뛴다** — 판단 기준을 `production` 브랜치에서 oracle 의 배포 표식(`.jenkins-prod-deployed`)
  으로 옮긴다: `deploy.sh plan` 이 바뀐 서비스가 없다고 내면 교체 없이 표식만 옮긴다. ADR-0068 이 버린 「oracle 의 표식을
  읽는 길」(첫 단계부터 oracle 을 잡아야 했다)은 이제 배포 단계 안이라 비용이 없다. 대가: 문서만 병합도 빌드 노드를
  잠깐 잡는다(전부 ctx 로 건너뛰어 커밋 태그만 더한다). `production` 앞당기기는 멈춘다.
- **GlitchTip 해결 표시**는 열차의 병합 단계에서 배포 잡의 이미지 굽기 끝으로 옮긴다(직전 성공 배포 → 이 커밋 범위).
- 이미지 태그(`<svc>:<sha>-arm64`)·ctx 태그·`ghcr-prune` 은 그대로다. `ghcr-prune` 은 `production` 이 없어도 멈추지 않게 했다.

### 지운 것

`Jenkinsfile.train`·`scripts/ci/train.py`·`scripts/ci/fast_forward.py`·`scripts/ci/e2e_stall.py`(열차의 인프라 재실행
판정)와 그 시험(이미지 스크립트 시험은 `scripts/test_ci_images.py` 로 옮겼다), `Jenkinsfile` 의 「대상 확인」·
`IMAGES_ONLY`·`production` 앞당기기, `.jenkins-production-base`.

### 하지 않은 것(대장·대표 몫)

Jenkins `codemit/ci-train` 잡·자격증명 `codemit-train-webhook-token`·열차용 GitHub 웹훅 삭제, 원격 `production` 브랜치
삭제, 브랜치 보호 규칙, `codemit/ci-pr` 를 PR 발견(머지 결과)으로 바꾸기 — 지금은 브랜치 발견이라 상태 문맥이
`continuous-integration/jenkins/branch` 이고 라이브러리의 「PR 검사 실패」 댓글이 달리지 않는다.

## 결과

- `wait-ci.py` 가 PR 검사의 SUCCESS 를 보고, `wait-deploy.py --job codemit/deploy --pr <N>` 가 `sandcorp/deploy` 로 배포
  끝을 본다 — work 에 Jenkins 키가 없어도 된다.
- PR 마다 e2e 가 돈다(열차는 묶음마다 한 번). macos 실행기 하나를 PR 검사와 배포가 나눠 쓴다. 대신 PR 끼리의 충돌은
  열차가 잡던 것을 놓친다 — squash 병합 전 PR 이 뒤처졌으면 배포 잡이 바뀐 문맥만 다시 굽고 가드한다.
- 배포 단계가 Jenkins 화면에서 「배포」 하나로 보인다(`deploy.sh` 명령마다 콘솔에 `== deploy.sh prod <명령>`).
