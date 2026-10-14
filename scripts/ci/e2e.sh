#!/bin/bash
# 열차의 macos 쪽 e2e — 세 앱의 프로덕션 이미지 스택을 굽고 띄워 세 프로젝트를 돌린다
# (2026-10-02 Jenkinsfile.pr 에서 시작, 지금은 Jenkinsfile.train 이 부른다). macos 노드는 실행기가
# 하나라 다른 빌드와 겹치지 않으므로 노드를 통째로 쓴다. 시험 하나 3초·재시도 0 은
# playwright.config.ts 가 정한다. 프로젝트마다 두 패스는 frontend/scripts/e2e-two-pass.sh 가 정의하고,
# 첫 패스가 붉어도 둘째(`@exclusive`) 패스까지 돈다 — 실패를 더 많이 남기려는 것이다(#700).
#
# 끝나면(성공·실패·중단 모두) 스택을 지운다 — 그 실행이 구운 이미지까지(`--rmi local`). 프로젝트
# 이름이 실행마다 달라(CODEMIT_CI_RUN_ID) 이미지가 새 이름으로 구워지므로, 남기면 Docker VM 디스크가
# 찬다(2026-10-14, 이미지 1,283개·51GB). 빌드 캐시는 남으니 다음 실행의 굽기는 캐시 히트다.
# 공용 base 이미지(postgres·redis·minio)는 compose 가 구운 것이 아니라 남는다.
# 프로젝트 하나가 실패해도 나머지는 끝까지 돈다.
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

# 스택 로그는 **서비스마다 통째로** `test-results/stack/<서비스>.log` 에 남긴다(#699). 예전의
# `--tail 80` 한 파일은 앞선 celery 줄로 다 차서, 시험이 붉어진 그 몇 초의 줄이 하나도 없었다
# (열차 #1840). 줄마다 Docker 타임스탬프(나노초)를 붙여 서비스끼리, 그리고 Playwright trace 와
# 시각으로 맞춰 본다. 무엇을 거둘지 실패해도 `down` 까지는 간다.
sampler=""
cleanup() {
  [ -n "$sampler" ] && kill "$sampler" 2>/dev/null
  mkdir -p test-results/stack
  for service in $("${C[@]}" ps -a --services 2>/dev/null); do
    "${C[@]}" logs --no-color --timestamps "$service" >"test-results/stack/$service.log" 2>&1 || true
  done
  "${C[@]}" down -v --remove-orphans --rmi local >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
rm -rf test-results && mkdir -p test-results
summary=test-results/summary.txt
: >"$summary"
# 호스트(mac)의 1초 샘플 — 메모리 압력·스왑·load·Docker VM 프로세스·docker stats 를
# `test-results/host/*.log` 에(#716). 열차 #1890 의 4초 정지는 Docker VM 전체였고 컨테이너 로그로는 더
# 가릴 수 없었다. macOS 가 아니면 곧바로 끝나고, 명령이 없어도 e2e 를 붉게 만들지 않는다.
bash scripts/ci/host-sample.sh test-results/host </dev/null >/dev/null 2>&1 &
sampler=$!

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

# 두 패스(`@exclusive` 는 일꾼 하나로 따로)는 package.json 의 `test:*`·scripts/test.sh 와 같은
# frontend/scripts/e2e-two-pass.sh 다(#702). Playwright 는 실행마다 출력 폴더를 비우므로 패스마다
# `test-results/playwright/<프로젝트>[-exclusive]/` 에 따로 둔다(#699, 경로는 frontend 기준이라 `../`).
# 성공한 시험의 것은 `retain-on-failure` 가 남기지 않는다.
run_target() {
  PLAYWRIGHT_WORKERS=$WORKERS \
    E2E_OUTPUT_DIR="../test-results/playwright/$1" \
    E2E_EXCLUSIVE_OUTPUT_DIR="../test-results/playwright/$1-exclusive" \
    frontend/scripts/e2e-two-pass.sh "$1"
}

failed=0
for target in public operator classroom; do
  started=$SECONDS
  if run_target "$target"; then
    echo "통과  e2e $target ($((SECONDS - started))초)" | tee -a "$summary"
  else
    echo "실패  e2e $target ($((SECONDS - started))초)" | tee -a "$summary"
    failed=1
  fi
done
exit "$failed"
