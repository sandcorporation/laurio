#!/bin/bash
# PR CI 의 home 쪽 — 백엔드 시험·단위 시험·생성물·문서 검사·타입 검사 (2026-10-02, Jenkinsfile.pr).
#
# 저장소를 담은 CI 이미지(docker/ci.Dockerfile)를 굽거나 받고(`ci-image.sh`), 사이드카 postgres 와 같은 망에서 그 안의
# `scripts/ci/sub-checks-inside.sh` 를 돌린다. 끝나면(성공·실패·중단 모두) 컨테이너·망·이미지를
# 지운다. 결과는 test-results/(junit·요약)로 꺼내 온다.
#
# CODEMIT_CI_IMAGE_TAR 가 있으면 굽지 않고 그 tar 를 싣는다 — GitHub Actions 의 `ci-image` 잡이 한 번 구워
# 산출물로 넘긴 것이다(#1081). postgres 는 이미지를 굽거나 싣는 동안 먼저 뜬다.
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

docker network create "$net" >/dev/null
# 버릴 DB 라 디스크 동기화를 끈다 — dev compose 와 같은 이유(커밋 대기가 시험 시간을 먹는다).
# 이미지를 굽거나 싣는 동안 받고 뜨게 먼저 띄운다.
docker run -d --name "$pg" --network "$net" --network-alias postgres --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=codemit -e POSTGRES_USER=codemit -e POSTGRES_PASSWORD=codemit \
  --health-cmd "pg_isready -U codemit -d codemit" --health-interval 1s \
  postgres:17-alpine -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null

if [ -n "${CODEMIT_CI_IMAGE_TAR:-}" ]; then
  echo "CI 이미지 싣는 중($CODEMIT_CI_IMAGE_TAR → $image)…"
  loaded=$(docker load -q -i "$CODEMIT_CI_IMAGE_TAR" | sed -n 's/^Loaded image: //p' | head -1)
  [ -n "$loaded" ] && docker tag "$loaded" "$image" || { echo "CI 이미지를 싣지 못했다"; exit 1; }
else
  echo "CI 이미지 굽는 중($image)…"
  bash scripts/ci/ci-image.sh load "$image" || { echo "CI 이미지를 굽지 못했다"; exit 1; }
fi

for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$pg")" = healthy ] && break
  sleep 1
done

status=0
docker run --name "$box" --network "$net" --env-file scripts/ci/backend-test.env -e CI=true \
  "$image" bash scripts/ci/sub-checks-inside.sh "$@" || status=$?
docker cp "$box:/repo/test-results/." test-results/ >/dev/null 2>&1 || true
exit "$status"
