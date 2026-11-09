#!/usr/bin/env bash
# PR 검사(`codemit/ci-pr`) — jenkins-shared `sandcorpPrCheck` 의 `check`(#873, ADR-0071). 라이브러리가 빌드 노드
# (**macos 먼저** — Jenkinsfile.pr 의 `prefer: 'macos'`)에서 브랜치 머리(잡이 PR 발견이면 PR 머지 결과)를 체크아웃한 뒤
# 이것 하나를 돌린다. 2026-11-05 전에는 PR 마다 home 검사만 돌고 e2e·celery 와 병합은 열차(`codemit/ci-train`)가
# 했다 — 열차를 걷으며 그 품질 문을 여기로 옮겼다.
#
#   문서만(.md·docs/) 바뀐 PR   ADR 상태 검사만(`changed.sh`)
#   그 밖                       ① home 검사 묶음(`sub-checks.sh` — 백엔드·단위·생성물·문서·타입)
#                               ② prod(arm64) 여섯을 이 커밋으로 굽고(`images.sh arm64`, 바뀌지 않은 것은 ctx 로 건너뜀)
#                               ③ 이번에 구운 앱의 부팅 가드(#838)
#                               ④ 그 이미지로 e2e(`e2e.sh`)와 celery 브로커(`celery-broker.sh`) — 시험한 digest = 배포할 digest
#                               ⑤ 전부 초록이면 ctx 태그(`images-ctx.sh`)와 e2e 태그(`images-e2e.sh`) — squash 병합 커밋의
#                                  트리가 같으면 배포 잡은 굽지 않고 커밋 태그만 더하고, prod 의 `e2e-digest` 가 견준다
#
# **e2e 는 macos 에서만 돈다.** home(Jenkins 컨테이너, amd64)은 arm64 를 QEMU 로 굽고 띄워 e2e 의 3초 한도를 못 지킨다.
# home 으로 넘어온 빌드는 ① 만 돌고 실패로 끝난다 — 조용히 줄어든 초록을 내지 않는다(Jenkins 에서 `BUILDER=macos` 로 다시).
#
# 환경(라이브러리): SANDCORP_BUILT_ON(macos|home), GHCR_TOKEN(Jenkinsfile.pr 의 credentials), BUILD_TAG.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

GIT=(git -c safe.directory="$PWD")
# 시험 자원 이름 — 같은 PR 의 빌드 번호가 되풀이돼도 겹치지 않게 시각을 붙인다.
export CODEMIT_CI_RUN_ID="${CODEMIT_CI_RUN_ID:-${BUILD_TAG:-codemit-pr}-$(date +%s)}"

base=$("${GIT[@]}" merge-base origin/main HEAD 2>/dev/null || true)
plan=$(bash scripts/ci/changed.sh "$base")
echo "돌릴 것: $plan (기준 ${base:0:12})"
# 공개 저장소 위생(#930) — 내부 호스트·OCI 실값·워크플로 보안 규칙. 호스트의 git 이 필요해 CI 이미지 밖에서 돈다.
python3 scripts/test_public_repo.py || exit 1
if [ "$plan" = "TESTS=0" ]; then
  exec python3 scripts/check_adr_status.py
fi

status=0
bash scripts/ci/sub-checks.sh || status=$?
if [ "$status" -ne 0 ]; then
  echo "home 검사 묶음이 붉다(종료 $status) — 위의 요약"
  tail -n 40 test-results/summary.txt 2>/dev/null || true
  exit "$status"
fi

where="${SANDCORP_BUILT_ON:-}"
if [ "$where" != macos ]; then
  echo "e2e 는 macos 에서만 돈다 — 이 빌드는 '${where:-?}' 에서 돌았다. Jenkins codemit/ci-pr 의 이 PR 을 BUILDER=macos 로 다시 돌린다."
  exit 1
fi

# 중단된 앞 빌드가 남긴 스택·디스크부터 걷는다(trap 은 중단 때 돌지 못한다).
bash scripts/ci/macos-sweep.sh || true

set -e
bash scripts/ci/images.sh arm64
for app in frontend operator classroom; do
  if grep -qx "$app=built" .images-arm64.result; then
    CODEMIT_GUARD_ARCH=arm64 bash scripts/ci/deploy-guard.sh "$app"
  fi
done
set +e

tag="$("${GIT[@]}" rev-parse HEAD)-arm64"
e2e=0
CODEMIT_IMAGE_TAG="$tag" bash scripts/ci/e2e.sh || e2e=$?
# e2e 가 붉어도 celery 브로커는 돈다 — 어디가 깨졌는지 한 번에 본다.
celery=0
CODEMIT_IMAGE_TAG="$tag" bash scripts/ci/celery-broker.sh || celery=$?
if [ "$e2e" -ne 0 ] || [ "$celery" -ne 0 ]; then
  echo "e2e 종료 $e2e · celery 브로커 종료 $celery"
  exit 1
fi

# 여기까지 초록 — ctx·e2e 태그는 실패해도 검사를 붉히지 않는다(배포 잡이 다시 굽고, prod 의 e2e 대조가 「대조 못 함」이 될 뿐).
bash scripts/ci/images-ctx.sh .images-arm64.ctx || echo "ctx 태그 실패 — 배포 잡이 다시 굽는다"
tree=$("${GIT[@]}" rev-parse 'HEAD^{tree}')
bash scripts/ci/images-e2e.sh test-results/images.txt "$tree" || echo "e2e 태그 실패 — prod 의 e2e 대조가 「대조 못 함」이 될 뿐이다"
exit 0
