#!/bin/bash
# PR CI 의 macos 쪽 — Celery 가 실제 Redis 브로커로 beat → worker 까지 도는지 본다
# (beat 는 worker 컨테이너 안에서 `-B` 로 돈다, #859 — 그래도 태스크는 브로커를 왕복한다)
# (옛 GitHub Actions `celery-broker` 잡을 그대로 옮겼다, 2026-10-02).
set -uo pipefail
cd "$(dirname "$0")/../.."

project=$(printf '%s' "${CODEMIT_CI_RUN_ID:-codemit-celery-$$}-celery" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | cut -c1-60)
C=(docker compose -p "$project" -f docker/compose.dev.yaml -f docker/compose.ci.yaml -f docker/compose.ci-internal-only.yaml)
# 이미지의 두 길은 e2e.sh 와 같다(#712) — CODEMIT_IMAGE_TAG 가 있으면 images.sh 가 올린 backend 를 받고,
# 없으면 여기서 굽는다.
build_flag=(--build)
if [ -n "${CODEMIT_IMAGE_TAG:-}" ]; then
  C+=(-f docker/compose.ci-images.yaml)
  build_flag=()
  # shellcheck source=scripts/ci/ghcr-login.sh
  . scripts/ci/ghcr-login.sh
fi
# 이미지 층 캐시(GitHub Actions, #932) — 워크플로가 CODEMIT_BK_CACHE 를 주면 복원한 층을 읽고,
# main push 실행만 CODEMIT_BK_CACHE_SAVE=1 로 backend 층을 내보낸다.
if [ -n "${CODEMIT_BK_CACHE:-}" ]; then
  C+=(-f docker/compose.ci-cache.yaml)
  if [ -n "${CODEMIT_BK_CACHE_SAVE:-}" ]; then C+=(-f docker/compose.ci-cache-save.yaml); fi
fi
C+=(--profile celery)
# 구운 이미지까지 지운다(--rmi local) — 프로젝트 이름이 실행마다 달라 남기면 쌓인다(e2e.sh 머리 주석).
cleanup() {
  "${C[@]}" down -v --remove-orphans --rmi local >/dev/null 2>&1 || true
  if [ -n "${CODEMIT_IMAGE_TAG:-}" ]; then ghcr_logout; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [ -n "${CODEMIT_IMAGE_TAG:-}" ]; then ghcr_login; fi

"${C[@]}" up -d ${build_flag[@]+"${build_flag[@]}"} || { echo "스택을 띄우지 못했다"; exit 1; }

# 브로커 드라이버가 이미지에 들어 있다.
"${C[@]}" exec -T celery-worker python -c "import redis, kombu; print('redis', redis.__version__, 'kombu', kombu.__version__)" || exit 1

# worker 가 브로커에 붙었다. 판정은 출력을 받아 둔 뒤 문자열로 한다 — `… | grep -q` 는 pipefail
# 아래에서 grep 이 먼저 끝나 앞 명령이 SIGPIPE 로 죽으면 찾고도 실패로 읽힌다(옛 Actions 셸에는
# pipefail 이 없었다).
ok=0
ping=""
for _ in $(seq 1 30); do
  ping=$("${C[@]}" exec -T celery-worker celery -A config inspect ping 2>&1 || true)
  if [[ "$ping" == *pong* ]]; then ok=1; break; fi
  sleep 3
done
if [ "$ok" != 1 ]; then
  echo "worker 가 브로커에 붙지 못했다 — 마지막 ping:"
  printf '%s\n' "$ping"
  echo "--- worker 기동 로그(앞부분)"
  "${C[@]}" logs --no-log-prefix celery-worker | head -60
  exit 1
fi
echo "worker: pong"

# beat 가 쏜 태스크를 worker 가 실행한다.
TASK_NAME=$("${C[@]}" exec -T celery-worker python -c "from core.tasks import run_scan; print(run_scan.name)" | tr -d '\r\n')
[ -n "$TASK_NAME" ] || { echo "core.tasks.run_scan 의 태스크 이름을 읽지 못했다"; exit 1; }
echo "찾는 태스크: $TASK_NAME"
for _ in $(seq 1 40); do
  logs=$("${C[@]}" logs celery-worker 2>&1 || true)
  if grep -q "${TASK_NAME}.*succeeded" <<<"$logs"; then
    echo "beat -> worker 경로 확인"
    exit 0
  fi
  sleep 3
done
echo "beat 가 쏜 태스크를 worker 가 실행하지 못했다"
"${C[@]}" logs celery-worker | tail -50
exit 1
