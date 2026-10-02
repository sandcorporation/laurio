#!/bin/bash
# PR CI 의 macos 쪽 — Celery 가 실제 Redis 브로커로 beat → worker 까지 도는지 본다
# (옛 GitHub Actions `celery-broker` 잡을 그대로 옮겼다, 2026-10-02).
set -uo pipefail
cd "$(dirname "$0")/../.."

project=$(printf '%s' "${CODEMIT_CI_RUN_ID:-codemit-celery-$$}-celery" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | cut -c1-60)
C=(docker compose -p "$project" -f docker/compose.dev.yaml -f docker/compose.ci.yaml -f docker/compose.ci-internal-only.yaml --profile celery)
cleanup() { "${C[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM

"${C[@]}" up -d --build || { echo "스택을 띄우지 못했다"; exit 1; }

# 브로커 드라이버가 이미지에 들어 있다.
"${C[@]}" exec -T celery-worker python -c "import redis, kombu; print('redis', redis.__version__, 'kombu', kombu.__version__)" || exit 1

# worker 가 브로커에 붙었다.
ok=0
for _ in $(seq 1 30); do
  if "${C[@]}" exec -T celery-worker celery -A config inspect ping | grep -q pong; then ok=1; break; fi
  sleep 3
done
[ "$ok" = 1 ] || { echo "worker 가 브로커에 붙지 못했다"; "${C[@]}" logs celery-worker | tail -50; exit 1; }
echo "worker: pong"

# beat 가 쏜 태스크를 worker 가 실행한다.
TASK_NAME=$("${C[@]}" exec -T celery-worker python -c "from core.tasks import run_scan; print(run_scan.name)" | tr -d '\r\n')
[ -n "$TASK_NAME" ] || { echo "core.tasks.run_scan 의 태스크 이름을 읽지 못했다"; exit 1; }
echo "찾는 태스크: $TASK_NAME"
for _ in $(seq 1 40); do
  if "${C[@]}" logs celery-worker | grep -q "${TASK_NAME}.*succeeded"; then
    echo "beat -> worker 경로 확인"
    exit 0
  fi
  sleep 3
done
echo "beat 가 쏜 태스크를 worker 가 실행하지 못했다"
"${C[@]}" logs celery-beat | tail -50
"${C[@]}" logs celery-worker | tail -50
exit 1
