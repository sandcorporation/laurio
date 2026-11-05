#!/usr/bin/env bash
# PR 검사의 e2e 가 받은 arm64 이미지에 `e2e-<트리>-arm64` 태그를 붙인다(#729 — 지금은 scripts/ci/pr-check.sh 끝, #873 전에는 열차 「병합」).
#
#   scripts/ci/images-e2e.sh test-results/images.txt <트리 해시>
#
# `images.txt` 는 `e2e.sh` 가 남긴 `<compose 서비스> <RepoDigest…>` 줄이다(같은 이미지를 쓰는 서비스가
# 여럿이면 줄도 여럿 — 저장소@digest 로 하나씩만 붙인다). 열차는 시험 둘이 초록인 묶음에서만, ctx 와 함께
# **병합 전에** 이것을 부른다. 병합이 다 끝나면 main 의 트리가 이 트리와 같으므로 prod 배포가
# `deploy.sh prod e2e-digest` 로 「e2e 가 본 이미지 = 떠 있는 이미지」를 이 태그와 견준다. 태그는 내용
# 기준이라(이 트리를 e2e 가 이 digest 로 봤다) 병합이 거절돼도 무해하다. 매니페스트를 그대로 베낀다
# (`--prefer-index=false` — images.sh 의 건너뛰기와 같은 이유, 같은 버전에 태그만 는다).
#
# 환경변수: GHCR_TOKEN / GHCR_USER(images.sh 와 같다). bash 3.2 에서도 돈다.
set -euo pipefail

list="${1:-}"
tree="${2:-}"
if [ -z "$list" ] || [ -z "$tree" ]; then echo "쓰는 법: $0 <images.txt> <트리 해시>" >&2; exit 2; fi
[ -f "$list" ] || { echo "$list 이 없다 — 붙일 것이 없다"; exit 0; }

cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/ghcr-login.sh
. scripts/ci/ghcr-login.sh

trap ghcr_logout EXIT
trap 'exit 130' INT TERM

# 저장소@digest 를 모은다 — 우리 이미지(codemit-*)만, 같은 것은 한 번.
refs=$(tr ' ' '\n' < "$list" | grep -E '/codemit-[a-z]+@sha256:[0-9a-f]{64}$' | sort -u || true)
[ -n "$refs" ] || { echo "$list 에 우리 이미지의 digest 가 없다 — 붙일 것이 없다"; exit 0; }

ghcr_login

pids=""
for ref in $refs; do
  tag="${ref%@*}:e2e-$tree-arm64"
  echo "e2e 태그 ${ref##*/} ← ${tag##*:}"
  docker buildx imagetools create --prefer-index=false --tag "$tag" "$ref" &
  pids="$pids $!"
done
n=0
failed=0
for pid in $pids; do
  if wait "$pid"; then n=$((n + 1)); else failed=1; fi
done
echo "e2e 태그 ${n}개"
exit "$failed"
