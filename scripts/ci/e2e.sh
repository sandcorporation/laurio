#!/bin/bash
# PR CI 의 macos 쪽 e2e — 세 앱의 프로덕션 이미지 스택을 굽고 띄워 세 프로젝트를 돌린다
# (2026-10-02, Jenkinsfile.pr). macos 노드는 실행기가 하나라 다른 빌드와 겹치지 않으므로 노드를
# 통째로 쓴다. 시험 하나 3초·재시도 0 은 playwright.config.ts 가 정한다.
#
# 끝나면(성공·실패·중단 모두) 스택을 지운다. 프로젝트 하나가 실패해도 나머지는 끝까지 돈다.
set -uo pipefail
cd "$(dirname "$0")/../.."
# playwright.config 의 입구 검사 — 이 노드는 Jenkins 가 통째로 쓰므로 test.sh 의 칸을 거치지 않는다.
export CODEMIT_TEST_ENTRY="scripts/ci/e2e.sh"

project=$(printf '%s' "${CODEMIT_CI_RUN_ID:-codemit-e2e-$$}-e2e" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | cut -c1-60)
C=(docker compose -p "$project" -f docker/compose.dev.yaml -f docker/compose.ci.yaml)
# 노드 코어의 1/3 — Playwright 일꾼은 코어 둘에 하나보다 적게 둔다. 같은 노드의 Docker VM 안에서
# 앱 셋·백엔드 넷·DB 가 함께 돈다.
WORKERS=$(( $(getconf _NPROCESSORS_ONLN) / 3 ))
[ "$WORKERS" -ge 2 ] || WORKERS=2

cleanup() {
  "${C[@]}" logs --tail 80 >test-results/e2e-stack.log 2>&1 || true
  "${C[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
rm -rf test-results && mkdir -p test-results
summary=test-results/summary.txt
: >"$summary"

read_port() { "${C[@]}" port "$1" "$2" | head -n 1 | sed 's/.*://'; }

"${C[@]}" up -d minio >/dev/null
CODEMIT_MINIO_PORT=$(read_port minio 9000)
export CODEMIT_MINIO_PORT
echo "스택 굽고 띄우는 중($project)…"
"${C[@]}" up -d --build frontend operator classroom events grader || { echo "스택을 띄우지 못했다"; exit 1; }

CODEMIT_API_PORT=$(read_port backend 8000)
CODEMIT_API_BASE_URL="http://127.0.0.1:$CODEMIT_API_PORT"
CODEMIT_E2E_BASE_URL="http://127.0.0.1:$(read_port frontend 3000)"
CODEMIT_OPERATOR_E2E_BASE_URL="http://127.0.0.1:$(read_port operator 3000)"
CODEMIT_CLASSROOM_E2E_BASE_URL="http://127.0.0.1:$(read_port classroom 3000)"
export CODEMIT_API_PORT CODEMIT_API_BASE_URL CODEMIT_E2E_BASE_URL CODEMIT_OPERATOR_E2E_BASE_URL CODEMIT_CLASSROOM_E2E_BASE_URL
for url in "$CODEMIT_E2E_BASE_URL" "$CODEMIT_OPERATOR_E2E_BASE_URL" "$CODEMIT_CLASSROOM_E2E_BASE_URL"; do
  ok=0
  for _ in $(seq 1 90); do
    curl --fail --silent "$url/healthz" >/dev/null 2>&1 && { ok=1; break; }
    sleep 2
  done
  [ "$ok" = 1 ] || { echo "$url 이 응답하지 않는다"; exit 1; }
done

corepack enable >/dev/null 2>&1 || true
pnpm install --frozen-lockfile >/dev/null || { echo "pnpm install 실패"; exit 1; }
pnpm --dir frontend exec playwright install chromium >/dev/null || { echo "Playwright 브라우저를 받지 못했다"; exit 1; }

failed=0
for target in public operator classroom; do
  started=$SECONDS
  if PLAYWRIGHT_WORKERS=$WORKERS pnpm --dir frontend run "test:$target"; then
    echo "통과  e2e $target ($((SECONDS - started))초)" | tee -a "$summary"
  else
    echo "실패  e2e $target ($((SECONDS - started))초)" | tee -a "$summary"
    failed=1
  fi
done
exit "$failed"
