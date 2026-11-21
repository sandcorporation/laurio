#!/usr/bin/env bash
# 세 Next 앱 이미지 층 캐시의 actions/cache 키(#1137) — `<앱>=bk-<앱>-<빌드 문맥 해시>` 를 한 줄에 하나.
#
#   bash scripts/ci/bk-keys.sh [앱...] >>"$GITHUB_OUTPUT"     인자가 없으면 frontend operator classroom
#
# 해시는 배포 이미지의 ctx 태그와 같은 `image_context.py hash <앱> amd64` 다 — 그 앱 폴더·packages·잠금 파일·Dockerfile 중
# `.dockerignore` 가 문맥에 남기는 것(e2e 스펙·단위 시험만 고친 커밋은 그대로다). 저장(release-cache.yml cache 잡)과 복원
# (pr-check.yml·e2e.yml)이 이 스크립트 하나로 같은 키를 낸다(scripts/test_release_flow.py). 해시는 「언제 새 세대를
# 저장하나」만 정한다 — 층이 맞는지는 BuildKit 이 내용으로 가린다. 복원은 정확한 키가 없으면 `bk-<앱>-` 접두로 가장 새
# main 세대를 받는다.
set -euo pipefail
cd "$(dirname "$0")/../.."
apps=("$@")
[ ${#apps[@]} -gt 0 ] || apps=(frontend operator classroom)
for app in "${apps[@]}"; do
  echo "$app=bk-$app-$(python3 scripts/ci/image_context.py hash "$app" amd64)"
done
