#!/usr/bin/env bash
# 이번 빌드가 구운 이미지에 문맥 태그(`ctx-<해시>-<arch>`)를 붙인다(#709, Jenkinsfile 「문맥 태그」).
#
#   scripts/ci/images-ctx.sh .images-amd64.ctx .images-arm64.ctx
#
# 파일은 `images.sh` 가 남긴 `서비스 ctx태그 커밋태그` 줄이다. 파이프라인은 이미지 단계 전체(두 가지)와
# 부팅 가드가 초록인 뒤에만 이것을 부른다 — 그래서 ctx 태그가 있는 문맥은 어느 빌드가 끝까지 초록으로
# 본 것이고, 다음 빌드가 그 서비스를 「건너뛴다」로 둬도 가드를 거치지 않은 이미지가 staging 으로 가지
# 않는다. 커밋 태그의 매니페스트를 그대로 베낀다(`--prefer-index=false` — images.sh 의 건너뛰기와 같은
# 이유). 없는 파일·빈 파일은 붙일 것이 없다는 뜻이다.
#
# 환경변수: GHCR_TOKEN / GHCR_USER(images.sh 와 같다). bash 3.2(macos 노드)에서도 돈다.
set -euo pipefail

cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/ghcr-login.sh
. scripts/ci/ghcr-login.sh

trap ghcr_logout EXIT
trap 'exit 130' INT TERM

ghcr_login

n=0
for file in "$@"; do
  [ -f "$file" ] || { echo "$file 이 없다 — 붙일 것이 없다"; continue; }
  while read -r svc ctx_ref sha_ref; do
    [ -n "${svc:-}" ] || continue
    if [ -z "${ctx_ref:-}" ] || [ -z "${sha_ref:-}" ]; then
      echo "$file 의 줄이 깨졌다: $svc $ctx_ref $sha_ref" >&2
      exit 1
    fi
    echo "문맥 태그 $svc — ${ctx_ref##*:} ← ${sha_ref##*:}"
    docker buildx imagetools create --prefer-index=false --tag "$ctx_ref" "$sha_ref"
    n=$((n + 1))
  done < "$file"
done
echo "문맥 태그 ${n}개"
