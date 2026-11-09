#!/usr/bin/env bash
# 배포 잡(`codemit/deploy`)의 **비상 길** 「이미지 굽기」 — jenkins-shared `sandcorpDeploy` 의 `buildScript`(#873, ADR-0071).
# 평소에는 GitHub Actions(image.yml)가 굽고 Jenkins 는 굽지 않는다(#938, ADR-0077). 「Build with Parameters」의
# `BUILD_ON=jenkins` 일 때만 라이브러리가 빌드 노드(macos 먼저, 못 잡으면 home)에서 배포할 커밋을 체크아웃한 뒤 이것을 돌린다.
#
#   1. `images.sh arm64`        여섯을 굽거나, 문맥(ctx)이 같으면 커밋 태그만 더한다. PR 검사가 같은 트리를 이미
#                               굽고 ctx 를 붙였으면(scripts/ci/pr-check.sh) 전부 「건너뛴다」 — 수 초다.
#   2. 부팅 가드                이번에 구운 앱만(#838). 건너뛴 앱은 ctx 가 붙을 때 이미 지났다.
#   3. `images-ctx.sh`          1·2 가 초록이면 이번에 구운 것에 ctx 태그.
#   4. 문맥 해시를 oracle 로     직전 성공 배포(`SANDCORP_PREVIOUS_SHA`) → 이 커밋 사이에 문맥이 바뀐 서비스를
#                               `$SANDCORP_DEPLOY_ENV` 에 적는다 — 라이브러리가 `deploy-prod.sh` 의 환경으로 넘기고
#                               `deploy.sh plan` 이 배포 표식과 기준이 같을 때만 쓴다(#849: oracle 에는 python3 가 없다).
#
# GlitchTip 해결 표시는 여기서 하지 않는다 — 배포가 끝난 뒤 oracle 의 `deploy-prod.sh` 가 한다(#938).
#
# 환경(라이브러리): IMAGE_SHA(배포할 커밋), SANDCORP_PREVIOUS_SHA, SANDCORP_DEPLOY_ENV, GHCR_TOKEN.
set -euo pipefail
cd "$(dirname "$0")/../.."

GIT=(git -c safe.directory="$PWD")
sha="${IMAGE_SHA:?IMAGE_SHA 가 없다 — 라이브러리 buildScript 로만 부른다}"
head=$("${GIT[@]}" rev-parse HEAD)
if [ "$head" != "$sha" ]; then
  echo "체크아웃($head)이 배포할 커밋($sha)이 아니다"
  exit 1
fi

bash scripts/ci/images.sh arm64

for app in frontend operator classroom; do
  if grep -qx "$app=built" .images-arm64.result; then
    CODEMIT_GUARD_ARCH=arm64 bash scripts/ci/deploy-guard.sh "$app"
  fi
done

bash scripts/ci/images-ctx.sh .images-arm64.ctx

base="${SANDCORP_PREVIOUS_SHA:-}"
if [ -z "${SANDCORP_DEPLOY_ENV:-}" ]; then
  echo "SANDCORP_DEPLOY_ENV 가 없다 — 문맥 해시를 넘기지 않는다(deploy.sh 가 경로 비교로 간다)"
elif [ -z "$base" ]; then
  echo "직전 성공 배포를 모른다 — 문맥 해시를 넘기지 않는다(deploy.sh 가 경로 비교로 간다)"
elif ! "${GIT[@]}" cat-file -e "${base}^{commit}" 2>/dev/null; then
  echo "직전 배포 ${base:0:12} 가 체크아웃에 없다 — 문맥 해시를 넘기지 않는다"
elif changed=$(python3 scripts/ci/image_context.py changed "$base" "$sha"); then
  # 줄바꿈·연속 공백을 한 칸으로 — 한 줄 값이어야 한다(BuildOutput).
  changed=$(printf '%s' "$changed" | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//')
  printf 'CODEMIT_CTX_BASE=%s\nCODEMIT_CTX_HEAD=%s\nCODEMIT_CTX_CHANGED=%s\n' "$base" "$sha" "$changed" > "$SANDCORP_DEPLOY_ENV"
  echo "문맥 해시(직전 배포 ${base:0:12} → 이 커밋) — 바뀐 서비스: ${changed:-없음}"
else
  echo "문맥 해시를 내지 못했다 — deploy.sh 가 경로 비교로 간다"
fi
