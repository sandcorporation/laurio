// main 의 커밋 하나의 여정 — 잡 `codemit/deploy`(Pipeline, `*/main`, GitHub push 웹훅). **main 병합 하나가 곧 prod 배포
// 하나다**(2026-11-05 #873, ADR-0071 — portfolio·foresight 와 같은 jenkins-shared `sandcorpDeploy`). 순서·DeployGate·
// 커밋 상태 `sandcorp/deploy`·실패 댓글·디스코드·빌드 노드(macos 먼저, 못 잡으면 home)는 라이브러리 몫이고
// (README: https://github.com/sandcorporation/jenkins-shared), codemit 에만 있는 것은 저장소 스크립트 둘이 한다:
//
//   이미지 굽기(빌드 노드)  `scripts/ci/build-images.sh` — 여섯 이미지를 문맥 해시로 변경분만 굽고(`<svc>:<sha>-arm64`),
//                           구운 앱의 부팅 가드, ctx 태그, oracle 로 넘길 문맥 해시, GlitchTip 해결 표시
//   배포(oracle)            `scripts/ci/deploy-prod.sh` — `deploy.sh prod` 의 preflight → plan → image → up(겹쳐 바꾸기,
//                           마이그레이션이 있으면 그 전에 pg_dump) → verify → health → reindex → mark → prune.
//                           「문서만」 병합은 plan 이 배포 표식 기준으로 비워 교체 없이 표식만 옮긴다
//
// **자동 롤백은 끈다**(`autoRollback: false`) — deploy.sh 는 배포 표식 기준으로 바꿀 서비스를 정해, 옛 sha 로 다시
// 부르면 아무것도 되돌리지 않는다. 되돌리기는 사람이 「Build with Parameters」의 `ROLLBACK_SHA` 로 한다.
// **prod 를 멈추려면** 이 잡을 「Disable」한다. 같은 커밋을 다시 배포하려면 `ROLLBACK_SHA` 에 그 sha.
//
// oracle 의 작업 공간은 사람이 둔 `docker/.env.prod`(chmod 600)와 배포 표식이 있는 호스트의
// `/var/jenkins_home/workspace/codemit-deploy-prod` — 에이전트 컨테이너(`jenkins-desktop-agent`) 안에서는
// `/home/jenkins/agent/workspace/codemit-deploy-prod` 다(옛 잡 이름, 2026-10-23 #520 의 상대 경로 사고 뒤로 절대 경로).
@Library('sandcorp') _

sandcorpDeploy(
  name: 'Codemit',
  composeProject: 'codemit-prod',
  composeFiles: ['docker/compose.prod.yaml'],
  buildScript: 'bash scripts/ci/build-images.sh',
  // 열차의 병합 단계가 하던 GlitchTip 해결 표시(build-images.sh 끝).
  buildCredentials: [[id: 'glitchtip-automation-token', variable: 'GLITCHTIP_TOKEN_FOR_AUTOMATION']],
  deployDir: '/home/jenkins/agent/workspace/codemit-deploy-prod',
  deployScript: 'scripts/ci/deploy-prod.sh',
  autoRollback: false,
  // 부팅 가드는 arm64 이미지를 arm64 노드에서만 본다 — home(amd64)으로 넘어가면 앱을 새로 구울 때 멈추므로 macos 를 오래 기다린다.
  macWaitSeconds: 1200,
)
