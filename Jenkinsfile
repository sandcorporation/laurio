// 운영 = production 브랜치 머리(#938, ADR-0077). 잡 `codemit/deploy`(Pipeline, 브랜치 지정자 `*/production`, GitHub push 웹훅)는
// production 만 배포한다 — jenkins-shared `sandcorpDeploy` 의 `deployFrom`(README 「승격 브랜치에서 배포」, sandcorp-metrics 와 같다).
//
//   main push → GitHub Actions release.yml: 검사(pr-check.yml) → 이미지(image.yml, ubuntu-24.04-arm, 여섯) → production fast-forward
//   production push → 여기: 굽지도 검사하지도 않는다. 여섯 이미지의 `ghcr.io/sandcorporation/codemit-<서비스>:<sha>` 가 있는지
//                     짧게 보고(`imageWaitMinutes`), oracle 에서 `scripts/ci/deploy-prod.sh` — `deploy.sh prod` 의 preflight → plan →
//                     image → up(겹쳐 바꾸기, 마이그레이션이 있으면 그 전에 pg_dump) → verify → health → reindex → mark → GlitchTip
//                     해결 표시 → prune. 「문서만」 병합은 plan 이 배포 표식 기준으로 비워 교체 없이 표식만 옮긴다.
//
// 파라미터(라이브러리):
//   BUILD_ON=jenkins  비상 길: Actions 가 못 구울 때 빌드 노드(macos 먼저, 못 잡으면 home)에서 `scripts/ci/build-images.sh` 로
//                     굽고 배포한다(#873 때의 길 그대로 — 문맥 해시 건너뛰기·부팅 가드·ctx 태그·문맥 해시를 oracle 로).
//   ROLLBACK_SHA      비상 되돌리기: 빌드 없이 그 sha 의 이미지로 배포(deploy-prod.sh 가 그 커밋을 체크아웃한다). production 은
//                     그대로라 다음 승격이 다시 앞으로 간다. 정석은 main 에 revert PR — docs/ops/deploy.md 「되돌리기」.
//
// **자동 롤백은 끈다**(`autoRollback: false`) — deploy.sh 는 배포 표식 기준으로 바꿀 서비스를 정해, 옛 sha 로 다시
// 부르면 아무것도 되돌리지 않는다. **prod 를 멈추려면** 이 잡을 「Disable」한다.
//
// oracle 의 작업 공간은 사람이 둔 `docker/.env.prod`(chmod 600 — GlitchTip 쓰기 토큰도 여기, deploy.md)와 배포 표식이 있는
// 호스트의 `/var/jenkins_home/workspace/codemit-deploy-prod` — 에이전트 컨테이너(`jenkins-desktop-agent`) 안에서는
// `/home/jenkins/agent/workspace/codemit-deploy-prod` 다(옛 잡 이름, 2026-10-23 #520 의 상대 경로 사고 뒤로 절대 경로).
@Library('sandcorp') _

sandcorpDeploy(
  name: 'Codemit',
  deployFrom: 'production',
  // 같은 목록이 .github/workflows/image.yml 의 matrix 와 scripts/ci/image_context.py 의 SERVICES 에 있다(scripts/test_release_flow.py).
  // 라이브러리는 `<repo>:<sha>` 를 기다린다 — image.yml 이 `<sha>-arm64`(compose 가 받는 것)와 같은 매니페스트에 붙인다.
  images: [
    [repo: 'ghcr.io/sandcorporation/codemit-backend', envVar: 'CODEMIT_BACKEND_IMAGE'],
    [repo: 'ghcr.io/sandcorporation/codemit-frontend', envVar: 'CODEMIT_FRONTEND_IMAGE'],
    [repo: 'ghcr.io/sandcorporation/codemit-operator', envVar: 'CODEMIT_OPERATOR_IMAGE'],
    [repo: 'ghcr.io/sandcorporation/codemit-classroom', envVar: 'CODEMIT_CLASSROOM_IMAGE'],
    [repo: 'ghcr.io/sandcorporation/codemit-search', envVar: 'CODEMIT_SEARCH_IMAGE'],
    [repo: 'ghcr.io/sandcorporation/codemit-pgbouncer', envVar: 'CODEMIT_PGBOUNCER_IMAGE'],
  ],
  imageWaitHint: 'https://github.com/sandcorporation/laurio/actions/workflows/release.yml',
  composeProject: 'codemit-prod',
  composeFiles: ['docker/compose.prod.yaml'],
  // BUILD_ON=jenkins 비상 길에서만 돈다.
  buildScript: 'bash scripts/ci/build-images.sh',
  deployDir: '/home/jenkins/agent/workspace/codemit-deploy-prod',
  deployScript: 'scripts/ci/deploy-prod.sh',
  autoRollback: false,
  // 비상 길의 부팅 가드는 arm64 이미지를 arm64 노드에서만 본다 — home(amd64)으로 넘어가면 앱을 새로 구울 때 멈추므로 macos 를 오래 기다린다.
  macWaitSeconds: 1200,
)
