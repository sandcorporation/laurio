#!/usr/bin/env bash
# 자동 되돌리기 시연(#1092) — 로컬 dev 스택에서 일부러 깨진 backend 이미지로 바꿔 끼우고, 배포 뒤 확인
# (`post-deploy-check.sh`, 진짜)이 그것을 잡은 뒤 직전 이미지로 되돌려 다시 통과하는 것을 본다. 운영·원격에 닿지 않는다.
#
#   bash scripts/ci/post-deploy-drill.sh        # 띄우고 → 통과 → 깨진 이미지 → 실패 → 되돌림 → 통과 → 내린다
#   CODEMIT_DRILL_KEEP=1 bash …                  # 끝나도 스택을 남긴다
#
# 이 워크트리의 dev 스택과 겹치지 않게 프로젝트 `codemit-drill-<오프셋>` 을 따로 띄운다 — 포트는 dev-env.sh 의 칸
# (오프셋 0~9)을 쓰므로 `CODEMIT_DRILL_OFFSET`(기본 6)으로 비어 있는 칸을 고른다.
#
# 되돌리기의 순서(어느 계획으로 무엇을 다시 받아 끼우는가)는 prod 의 `deploy-prod.sh` → `deploy.sh rollback-plan` →
# `post-deploy-rollback.sh` 가 하고, 그 길은 `backend/tests/test_deploy_postdeploy.py` 가 가짜 docker 위에서 본다.
# 여기서는 진짜 컨테이너에서 「깨진 이미지를 확인이 잡는다」와 「직전 이미지로 바꾸면 확인이 다시 통과한다」를 본다.
set -euo pipefail
cd "$(dirname "$0")/../.."

offset="${CODEMIT_DRILL_OFFSET:-6}"
slot=$((offset * 100))
export COMPOSE_PROJECT_NAME="codemit-drill-$offset"
export CODEMIT_DB_PORT=$((55432 + slot)) CODEMIT_API_PORT=$((58000 + slot)) CODEMIT_EVENTS_PORT=$((58001 + slot))
export CODEMIT_LLM_PROXY_PORT=$((58002 + slot)) CODEMIT_REDIS_PORT=$((16379 + slot)) CODEMIT_PGBOUNCER_PORT=$((16432 + slot))
export CODEMIT_MINIO_PORT=$((19000 + slot)) CODEMIT_MINIO_CONSOLE_PORT=$((19001 + slot)) CODEMIT_SEARCH_PORT=$((19200 + slot))
export CODEMIT_WEB_PORT=$((53000 + slot)) CODEMIT_OPERATOR_WEB_PORT=$((53001 + slot)) CODEMIT_CLASSROOM_WEB_PORT=$((53002 + slot))

good="codemit-drill-backend:good"
broken="codemit-drill-backend:broken"
work=$(mktemp -d "${TMPDIR:-/tmp}/postdeploy-drill.XXXXXX")
cat >"$work/override.yaml" <<'YAML'
services:
  backend:
    image: ${DRILL_BACKEND_IMAGE}
    pull_policy: never
  celery-worker:
    image: ${DRILL_BACKEND_IMAGE}
    pull_policy: never
YAML
compose=(docker compose -f docker/compose.dev.yaml -f "$work/override.yaml" --profile celery)

down() {
  [ "${CODEMIT_DRILL_KEEP:-0}" = 1 ] && { echo "스택을 남긴다: $COMPOSE_PROJECT_NAME"; return; }
  DRILL_BACKEND_IMAGE="$good" "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  docker rmi "$broken" "$good" >/dev/null 2>&1 || true
}
trap down EXIT

swap() {
  echo "== backend·celery-worker 를 $1 로 바꿔 끼운다"
  DRILL_BACKEND_IMAGE="$1" "${compose[@]}" up -d --no-deps backend celery-worker >/dev/null
}

check() {
  POSTDEPLOY_COMPOSE="${compose[*]}" POSTDEPLOY_ENV_FILE=/dev/null \
    CODEMIT_POSTDEPLOY_URLS="http://127.0.0.1:${CODEMIT_API_PORT}/api/health?scope=ready" \
    CODEMIT_POSTDEPLOY_SECONDS="$1" bash scripts/ci/post-deploy-check.sh
}

echo "== 좋은 이미지를 굽는다($good)"
DRILL_BACKEND_IMAGE="$good" "${compose[@]}" build backend >/dev/null
printf 'FROM %s\nENTRYPOINT ["sh", "-c", "echo drill: 일부러 깨진 이미지; exit 3"]\n' "$good" >"$work/Dockerfile"
docker build -q -t "$broken" "$work" >/dev/null

echo "== 처음 띄운다(마이그레이션까지 — 확인 한도 600초 — 새 DB 는 5분 가까이 걸린다)"
DRILL_BACKEND_IMAGE="$good" "${compose[@]}" up -d backend celery-worker >/dev/null
check 600

swap "$broken"
if check 60; then
  echo "!! 깨진 이미지를 확인이 잡지 못했다"
  exit 1
fi
echo "== 확인 실패 — 직전 이미지로 되돌린다"
swap "$good"
check 60
echo "== 시연 끝: 깨진 이미지를 잡고, 되돌린 뒤 다시 통과했다"
