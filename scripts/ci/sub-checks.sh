#!/bin/bash
# PR CI 의 home 쪽 — 백엔드 시험·단위 시험·생성물·문서 검사·타입 검사 (2026-10-02, Jenkinsfile.pr).
#
# 저장소를 담은 CI 이미지(docker/ci.Dockerfile)를 굽고, 사이드카 postgres 와 같은 망에서 그 안의
# `scripts/ci/sub-checks-inside.sh` 를 돌린다. 끝나면(성공·실패·중단 모두) 컨테이너·망·이미지를
# 지운다. 결과는 test-results/(junit·요약)로 꺼내 온다.
set -uo pipefail
cd "$(dirname "$0")/../.."

run_id=$(printf '%s' "${CODEMIT_CI_RUN_ID:-codemit-ci-$$}" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | cut -c1-60)
image="codemit-ci:$run_id"
net="$run_id"
pg="$run_id-pg"
box="$run_id-box"

cleanup() {
  docker rm -fv "$pg" "$box" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  docker rmi "$image" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

rm -rf test-results && mkdir -p test-results

echo "CI 이미지 굽는 중($image)…"
# 층 캐시(GitHub Actions, #932): CODEMIT_BK_CACHE 가 있으면 복원한 층을 읽고(buildx 컨테이너 빌더라 --load),
# 저장은 release.yml 의 cache 잡이 한다(#1090).
build_cache=()
if [ -n "${CODEMIT_BK_CACHE:-}" ]; then
  build_cache=(--load --cache-from "type=local,src=$CODEMIT_BK_CACHE/ci")
fi
docker build -q -f docker/ci.Dockerfile ${build_cache[@]+"${build_cache[@]}"} -t "$image" . >/dev/null || { echo "CI 이미지를 굽지 못했다"; exit 1; }

docker network create "$net" >/dev/null
# 버릴 DB 라 디스크 동기화를 끈다 — dev compose 와 같은 이유(커밋 대기가 시험 시간을 먹는다).
docker run -d --name "$pg" --network "$net" --network-alias postgres --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=codemit -e POSTGRES_USER=codemit -e POSTGRES_PASSWORD=codemit \
  --health-cmd "pg_isready -U codemit -d codemit" --health-interval 1s \
  postgres:17-alpine -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$pg")" = healthy ] && break
  sleep 1
done

# 마이그레이션 호환 검사(#1091)의 base — 병합 대상 커밋의 backend 마이그레이션 경로 목록. 이미지에는 .git 이 없어
# 여기서 뽑아 넣는다. CODEMIT_MIGRATION_BASE 는 pr-check.yml 이 준다(PR·대기열·main push 각각의 base). 없으면
# origin/main 과의 merge-base(로컬). 얕은 클론이면 그 커밋 하나만 받는다.
mounts=()
case "${1:-all}" in
  all|static)
    base="${CODEMIT_MIGRATION_BASE:-$(git merge-base HEAD origin/main 2>/dev/null || true)}"
    if [ -n "$base" ] && { git cat-file -e "$base^{commit}" 2>/dev/null || git fetch -q --no-tags --depth=1 origin "$base"; }; then
      git ls-tree -r --name-only "$base" -- backend | grep -E '^backend/[^/]+/migrations/[^/]+\.py$' >test-results/base-migrations.txt || true
      mounts=(-v "$PWD/test-results/base-migrations.txt:/tmp/base-migrations.txt:ro")
    else
      echo "마이그레이션 호환 검사의 base(${base:-없음})를 받지 못했다 — 그 단계가 실패한다"
    fi
    ;;
esac

status=0
# CODEMIT_PYTEST_FILES(#1088): PR 의 선택 실행이 고른 시험 파일 — 없으면 전부(pytest_shards.py)
docker run --name "$box" --network "$net" --env-file scripts/ci/backend-test.env -e CI=true -e CODEMIT_PYTEST_FILES \
  ${mounts[@]+"${mounts[@]}"} "$image" bash scripts/ci/sub-checks-inside.sh "$@" || status=$?
docker cp "$box:/repo/test-results/." test-results/ >/dev/null 2>&1 || true
exit "$status"
