#!/bin/bash
# CI 이미지(docker/ci.Dockerfile)를 굽는 한 곳 — `sub-checks.sh` 와 PR 검사의 `ci-image` 잡이 부른다(#1081).
#
#   ci-image.sh load TAG         굽어서 이 도커에 TAG 로 싣는다(로컬·한 실행기에서 다 도는 길)
#   ci-image.sh save TAG FILE    굽어서 `docker load -i FILE` 로 실을 tar 로만 낸다(도커에 싣지 않는다)
#
# GitHub Actions 는 `ci-image` 잡이 한 번 save 하고 checks 여섯 잡이 산출물로 받아 load 한다 — 잡마다 굽던 것(#1079).
# 층 캐시(#932): CODEMIT_BK_CACHE 가 있으면 복원한 층을 읽고(buildx 컨테이너 빌더), main push 실행만
# (CODEMIT_BK_CACHE_SAVE=1) CODEMIT_BK_CACHE_NEW 로 내보낸다.
set -euo pipefail
cd "$(dirname "$0")/../.."

mode="${1:?load|save}"
tag="${2:?TAG}"

cache=()
if [ -n "${CODEMIT_BK_CACHE:-}" ]; then
  cache=(--cache-from "type=local,src=$CODEMIT_BK_CACHE/ci")
  if [ -n "${CODEMIT_BK_CACHE_SAVE:-}" ]; then
    cache+=(--cache-to "type=local,dest=$CODEMIT_BK_CACHE_NEW/ci,mode=max")
  fi
fi

case "$mode" in
  load)
    # 컨테이너 빌더(캐시가 있을 때)는 결과를 도커에 실으라고 따로 말해야 한다
    out=()
    [ -n "${CODEMIT_BK_CACHE:-}" ] && out=(--load)
    docker build -q -f docker/ci.Dockerfile ${cache[@]+"${cache[@]}"} ${out[@]+"${out[@]}"} -t "$tag" . >/dev/null
    ;;
  save)
    file="${3:?FILE}"
    if [ -n "${CODEMIT_BK_CACHE:-}" ]; then
      # 컨테이너 빌더가 tar 를 바로 쓴다 — 도커에 실었다가 다시 꺼내는 두 번을 건너뛴다.
      # 새로 생긴 층(저장소·node_modules)만 zstd 로 묶고, 캐시에서 온 층은 받은 압축 그대로 둔다.
      docker build -q -f docker/ci.Dockerfile "${cache[@]}" \
        --output "type=docker,name=$tag,dest=$file,compression=zstd,compression-level=3" . >/dev/null
    else
      docker build -q -f docker/ci.Dockerfile -t "$tag" . >/dev/null
      docker save -o "$file" "$tag"
    fi
    ;;
  *)
    echo "모르는 방식: $mode (load|save)" >&2
    exit 2
    ;;
esac
