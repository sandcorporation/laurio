# 이미지는 Actions 가 굽고 production 으로 승격한다 — Jenkins 는 배포만

Status: Accepted (2026-11-09 결정)

## 맥락 (#938)

대표 지시(2026-11-09): sandcorp-metrics 에서 검증한 흐름을 나머지 저장소에도 편다 — main 병합 뒤 GitHub Actions 가 검사하고
이미지를 굽고 `production` 브랜치로 승격하며, Jenkins 는 `production` push 만 보고 배포한다. metrics 실측은 병합 → 승격
1분 28초, Jenkins 배포 49.5초였다(그 전에는 맥에서 검사·빌드·배포 4분 20~45초).

그 전(ADR-0071, 2026-11-05)의 codemit 은 `main` push 하나가 Jenkins `codemit/deploy` 한 빌드였다: 빌드 노드(macos 먼저,
못 잡으면 home)가 `build-images.sh` 로 여섯 arm64 이미지를 굽고(문맥 해시 건너뛰기·부팅 가드·ctx 태그·문맥 해시를 oracle 로·
GlitchTip 해결 표시), oracle 이 배포했다. PR 검사는 #930·#932(ADR-0076)로 이미 Actions 로 옮겨 Jenkins PR 검사가 꺼졌고,
그래서 배포 잡은 PR 검사가 남기던 이미지·ctx 를 더는 받지 못해 매번 굽게 됐다(#933). 맥의 디스크·메모리 부족, 시험 한도
흔들림이 배포 경로에 그대로 들어와 있었다.

## 결정

- **`release.yml`(push: main)**: `check`(pr-check.yml 을 workflow_call 로 그대로) → `image`(image.yml) → `promote`
  (`scripts/ci/promote.sh ff` — production fast-forward 만). pr-check.yml 은 `push: main` 을 빼고 `workflow_call` 을 더했다.
  main 실행의 캐시 저장(#932)은 부른 쪽의 `github.event_name`·`github.ref` 로 그대로 돈다.
- **`image.yml`**: 이미지마다 `ubuntu-24.04-arm` matrix 잡 하나가 **지금과 같은 스크립트**(`images.sh arm64` → 부팅 가드 →
  `images-ctx.sh`)를 부른다 — 이름 `ghcr.io/sandcorporation/codemit-<서비스>`, 태그 `<sha>-arm64`·`ctx-<해시>-arm64`, 라벨,
  레지스트리 캐시 `codemit-buildcache:<서비스>-arm64` 가 그대로라 oracle 의 compose 는 바뀌지 않는다. 같은 매니페스트에
  접미사 없는 `<sha>` 태그를 하나 더한다 — jenkins-shared `waitForGhcrImage` 가 `<repo>:<sha>` 를 기다리기 때문이다.
- **Jenkinsfile**: `sandcorpDeploy(deployFrom: 'production', images: [여섯], imageWaitHint: release.yml)`. 평소에는 굽지도
  검사하지도 않는다. 배포 파라미터 `ROLLBACK_SHA` 는 Actions 가 올린 GHCR 이미지에만 쓴다. Jenkins 이미지 빌드 비상 길과 빌드 노드 선택 파라미터는 제거한다.
- **GlitchTip 해결 표시는 배포 단계로**: Actions 에는 GITHUB_TOKEN 외 비밀을 두지 않으므로 `deploy-prod.sh` 가 배포 표식 뒤에
  `scripts/ci/glitchtip-resolve.sh`(git·curl — oracle 에이전트에 python3 가 없다)를 부른다. 토큰은 oracle `docker/.env.prod` 의
  `GLITCHTIP_TOKEN_FOR_AUTOMATION`. `buildCredentials` 와 `glitchtip_resolve.py` 는 걷었다.
- **e2e 대조를 걷는다**: e2e 태그를 붙이던 Jenkins PR 검사가 꺼져 대조(`deploy.sh e2e-digest`)는 늘 「태그 없음」이었다.
  「배포되는 것은 검사가 통과한 커밋」은 check → image → promote 순서가 지킨다.
- **되돌리기는 둘이다**: main 에 revert PR(정석 — 승격이 따라간다), 급하면 Jenkins `ROLLBACK_SHA`. production 을 옛 sha 로
  강제로 옮기는 워크플로는 만들지 않는다 — 조직 ruleset 이 Actions 를 bypass 로 받지 않아(422) production 에는 강제 push·삭제
  금지만 걸리기 때문이다(sandcorp-metrics 에서 바뀐 것).

## 대가

- 빌드 노드 단계가 없어 문맥 해시(`CODEMIT_CTX_*`)가 oracle 로 오지 않는다 — `deploy.sh plan` 은 경로 비교로 고른다(문맥 밖
  파일만 바뀐 커밋에도 서비스를 다시 띄울 수 있다).
- 병합에서 배포까지 release 의 check(PR 검사 전체)만큼 늦어진다. 대신 맥이 배포 경로에서 빠진다.
- Jenkinsfile·deploy-prod.sh·image.yml·release.yml 은 PR 에서 돌려 볼 수 없다 — 병합 뒤 첫 실행이 시험이다
  (`scripts/test_release_flow.py` 는 배선만 본다).
- 기존 GHCR 패키지는 Jenkins 의 개인 토큰이 만들어 저장소 GITHUB_TOKEN 이 쓰지 못한다 — 첫 release 에서 지우고 Actions 가
  새로 만든다(대장 몫).
