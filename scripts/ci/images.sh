#!/usr/bin/env bash
# 배포 이미지 여섯을 한 아키텍처로 굽거나, 바뀌지 않았으면 건너뛴다(#705, Jenkinsfile 「이미지」).
#
#   scripts/ci/images.sh arm64     prod 호스트(oracle)의 것 — 여섯 전부 `-arm64`. 배포는 이것 하나다
#   scripts/ci/images.sh amd64     로컬 시험용 — 열차·배포 잡은 부르지 않는다(staging 제거, #841). 문맥 해시의
#                                  플랫폼 구분(`image_context.py`)과 그 시험이 아직 두 값을 전제해 인자는 남겼다
#
# 태그는 `ghcr.io/sandcorporation/codemit-<서비스>:<커밋 sha>-<arch>` — deploy.sh 가 그 이름으로
# 받는다. 세 Next 앱도 환경을 모른다(#711, ADR-0062) — 공개 값은 빌드 인자가 아니라 실행 env
# (`CODEMIT_PUBLIC_*`)로 들어가므로 이 스크립트는 빌드 인자를 하나도 주지 않는다.
#
# **건너뛰기.** 서비스마다 빌드 문맥 해시(`scripts/ci/image_context.py` — Dockerfile 이 읽는 경로의
# git 해시 + 대상·플랫폼)를 내고, `…:ctx-<해시>-<arch>` 가 레지스트리에 있으면 굽지 않고 커밋 태그를
# 그 매니페스트에 더하기만 한다(`imagetools create`, 수 초). 없으면 굽고 **커밋 태그로만** 올린다. 콘솔에
# 서비스마다 「굽는다/건너뛴다」 한 줄이 남고, 결과는 `.images-<arch>.result` 에 `서비스=built|skipped`
# 로 적힌다 — 파이프라인이 그것으로 부팅 가드를 고른다.
#
# **ctx 태그는 여기서 붙이지 않는다**(#709). 구운 서비스는 `.images-<arch>.ctx` 에 `서비스 ctx태그 커밋태그`
# 한 줄씩 남기고, 파이프라인이 이미지 단계 전체와 부팅 가드가 초록인 뒤에 `scripts/ci/images-ctx.sh` 로
# 붙인다. 그래서 「ctx 태그가 있다」 = 「그 문맥을 어느 빌드가 끝까지 초록으로 봤다」이고, 건너뛴 앱의
# 이미지는 이미 한 번 가드를 지났다. 가드에서 떨어졌거나 다른 가지가 실패한 빌드의 이미지는 ctx 가 없어
# 다음 빌드가 다시 굽고 가드도 다시 돈다(레지스트리 캐시 덕에 대개 몇 분).
#
# 환경변수:
#   GHCR_TOKEN / GHCR_USER     ghcr 쓰기 토큰(Jenkins `ghcr-push-token`). 없으면 노드의 로그인을 쓴다
#   CODEMIT_IMAGES_MODE        push(기본) | plan | retag — plan 은 해시와 판단만 적고 굽지도 태그를 더하지도
#                              않는다. retag 는 건너뛸 것에만 커밋 태그를 더하고 구울 것은 `서비스=pending` 으로
#                              남긴다 — 빌더를 띄우지 않아 어느 노드에서나 돈다. `codemit/deploy` 가 열차가
#                              이미 구운 커밋을 macos 없이 끝내는 길이다(#729, Jenkinsfile 「대상 확인」)
#   CODEMIT_IMAGES_SERVICES    다룰 서비스(공백으로 가름, 기본 여섯 전부)
#   CODEMIT_IMAGE_REGISTRY     기본 ghcr.io/sandcorporation (로컬 시험은 localhost:<포트>)
#   CODEMIT_IMAGES_BUILDER     buildx 빌더 이름(기본 codemit-images — 없으면 docker-container 로 만든다.
#                              레지스트리 캐시를 내보내려면 docker 드라이버로는 안 된다)
#   CODEMIT_IMAGES_PARALLEL    1(기본)이면 굽는 것끼리 함께 돈다, 0 이면 하나씩
#   CODEMIT_IMAGES_KEEP_STORAGE  끝나고 빌더 캐시를 이만큼만 남긴다(기본 20gb)
#
# **실패 로그.** 실패한 서비스의 로그는 `test-results/images-<arch>/<서비스>.log` 에 남는다 — 열차가
# `scripts/ci/e2e_stall.py images <arch>` 로 레지스트리·buildx 탓인지 가른다(#729).
#
# bash 3.2(macos 노드)에서도 돈다 — 연관 배열·`wait -n`·`mapfile` 을 쓰지 않는다.
set -euo pipefail

arch="${1:-}"
case "$arch" in
  amd64|arm64) ;;
  *) echo "쓰는 법: $0 <amd64|arm64>" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/ghcr-login.sh
. scripts/ci/ghcr-login.sh

platform="linux/$arch"
registry="${CODEMIT_IMAGE_REGISTRY:-ghcr.io/sandcorporation}"
mode="${CODEMIT_IMAGES_MODE:-push}"
builder="${CODEMIT_IMAGES_BUILDER:-codemit-images}"
parallel="${CODEMIT_IMAGES_PARALLEL:-1}"
keep_storage="${CODEMIT_IMAGES_KEEP_STORAGE:-20gb}"
services="${CODEMIT_IMAGES_SERVICES:-$(python3 scripts/ci/image_context.py services | tr '\n' ' ')}"
sha="$(git -c safe.directory="$PWD" rev-parse HEAD)"
result_file=".images-$arch.result"
ctx_file=".images-$arch.ctx"
log_dir="test-results/images-$arch"
work="$(mktemp -d "${TMPDIR:-/tmp}/codemit-images.XXXXXX")"

case "$mode" in push|plan|retag) ;; *) echo "CODEMIT_IMAGES_MODE 는 push·plan·retag 중 하나다: $mode" >&2; exit 2 ;; esac
# 앞 빌드가 이 작업 공간에 남긴 결과를 먼저 지운다 — preflight 에서 멈춘 빌드가 옛 결과로 읽히지 않게.
rm -rf "$result_file" "$ctx_file" "$log_dir"

cleanup() {
  rm -rf "$work"
  ghcr_logout
}
trap cleanup EXIT
# Jenkins 가 중단하면(SIGTERM) EXIT trap 이 돌도록 — 안 그러면 쓰기 토큰이 담긴 임시 DOCKER_CONFIG 가 남는다.
trap 'exit 130' INT TERM

# ── preflight ───────────────────────────────────────────────────────────────
# sub 의 Jenkins 는 컨테이너다 — 그 안의 docker CLI 에 buildx 가 없으면 Dockerfile 의
# `RUN --mount`(BuildKit 전용)에서 전부 죽는다(2026-09-14 deploy.sh 빌드 #4~#6). 여기서 먼저 멈춘다.
if ! docker buildx version >/dev/null 2>&1; then
  echo "이 노드의 docker CLI 에 buildx 플러그인이 없다 — 에이전트에 docker-buildx 를 넣어라." >&2
  exit 1
fi

# 건너뛸 때 매니페스트를 그대로 베끼는 `imagetools create --prefer-index=false` 는 buildx 0.13+ 에 있다.
if ! docker buildx imagetools create --help 2>/dev/null | grep -q prefer-index; then
  echo "이 노드의 buildx 가 낡았다(imagetools create --prefer-index 없음) — buildx 0.13 이상을 넣어라." >&2
  exit 1
fi

ghcr_login

if [ "$mode" = push ]; then
  if ! docker buildx inspect "$builder" >/dev/null 2>&1; then
    echo "빌더 $builder 를 만든다(docker-container)"
    docker buildx create --name "$builder" --driver docker-container >/dev/null
  fi
  docker buildx inspect --bootstrap "$builder" >/dev/null
fi

# ── 서비스마다 ──────────────────────────────────────────────────────────────

build() {
  local svc="$1" suffix="$2" sha_ref="$3" target
  local cache="$registry/codemit-buildcache:$svc-$suffix"
  local cmd
  target="$(python3 scripts/ci/image_context.py field "$svc" target)"
  cmd=(docker buildx build --builder "$builder" --file "docker/$svc.Dockerfile" --platform "$platform"
       --provenance=false --push
       --tag "$sha_ref"
       --label "org.opencontainers.image.source=https://github.com/sandcorporation/laurio"
       --cache-from "type=registry,ref=$cache"
       --cache-to "type=registry,ref=$cache,mode=max")
  if [ -n "$target" ]; then cmd+=(--target "$target"); fi
  "${cmd[@]}" .
}

# 서비스 하나 — 판단을 한 줄로 적고 결과를 `$work/<svc>.result` 에 남긴다.
one() {
  local svc="$1" suffix="$arch" hash ctx_ref sha_ref
  hash="$(python3 scripts/ci/image_context.py hash "$svc" "$platform")"
  ctx_ref="$registry/codemit-$svc:ctx-$hash-$suffix"
  sha_ref="$registry/codemit-$svc:$sha-$suffix"

  if docker buildx imagetools inspect "$ctx_ref" >/dev/null 2>&1; then
    echo "건너뛴다 $svc ($suffix) — ctx-$hash 가 이미 있다"
    if [ "$mode" != plan ]; then
      # --prefer-index=false: 매니페스트를 그대로 베낀다(같은 digest — ghcr 에서는 같은 버전에 태그만
      # 는다). 빼면 buildx 가 매니페스트 하나짜리 index 를 새로 만들어, ghcr 에 그 index 와 원본이
      # 따로 버전으로 남고 정리 잡이 원본만 지우면 커밋 태그가 깨진다.
      docker buildx imagetools create --prefer-index=false --tag "$sha_ref" "$ctx_ref"
    fi
    echo "$svc=skipped" > "$work/$svc.result"
    return 0
  fi
  if [ "$mode" = retag ]; then
    echo "구울 것이 있다 $svc ($suffix) — ctx-$hash 가 없다, retag 는 굽지 않는다"
    echo "$svc=pending" > "$work/$svc.result"
    return 0
  fi
  echo "굽는다 $svc ($suffix) — ctx-$hash"
  if [ "$mode" = push ]; then
    build "$svc" "$suffix" "$sha_ref"
    # ctx 태그는 가드·다른 가지가 초록인 뒤에 — 머리 주석 「ctx 태그는 여기서 붙이지 않는다」.
    echo "$svc $ctx_ref $sha_ref" > "$work/$svc.ctx"
  fi
  echo "$svc=built" > "$work/$svc.result"
}

echo "커밋 $sha · $platform · 레지스트리 $registry · $mode"

# 서비스마다 배경 subshell 하나 — 로그는 파일로 받아 끝난 뒤 차례로 보인다(서로 섞이지 않는다).
# 하나씩(CODEMIT_IMAGES_PARALLEL=0)이면 띄우자마자 기다린다. `||` 안에서 부르면 set -e 가 꺼지므로
# 배경으로만 부른다.
show() {
  local pid="$1" svc="$2"
  if ! wait "$pid"; then
    echo "$svc=failed" > "$work/$svc.result"
  fi
  echo "──── $svc"
  cat "$work/$svc.log"
}
pids=""
for svc in $services; do
  ( one "$svc" ) > "$work/$svc.log" 2>&1 &
  if [ "$parallel" = 1 ]; then
    pids="$pids $!:$svc"
  else
    show "$!" "$svc"
  fi
done
for entry in $pids; do
  show "${entry%%:*}" "${entry#*:}"
done

failed=0
: > "$result_file"
: > "$ctx_file"
for svc in $services; do
  if [ -f "$work/$svc.ctx" ]; then cat "$work/$svc.ctx" >> "$ctx_file"; fi
  if [ -f "$work/$svc.result" ]; then
    cat "$work/$svc.result" >> "$result_file"
  else
    echo "$svc=failed" >> "$result_file"
  fi
  if grep -qx "$svc=failed" "$result_file"; then
    mkdir -p "$log_dir"
    cp "$work/$svc.log" "$log_dir/$svc.log" 2>/dev/null || true
  fi
done
grep -q '=failed$' "$result_file" && failed=1

echo
echo "── 결과($arch)"
cat "$result_file"

if [ "$mode" = push ] && grep -q '=built$' "$result_file"; then
  # 빌더 컨테이너의 캐시는 노드 디스크에 쌓인다 — 여기서 자른다(레지스트리 캐시는 그대로).
  docker buildx prune --builder "$builder" -f --keep-storage "$keep_storage" >/dev/null 2>&1 \
    || echo "빌더 캐시 정리를 건너뛴다 — 결과와 무관하다"
fi

exit "$failed"
