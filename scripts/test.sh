#!/bin/bash
# 로컬 시험의 입구 (2026-10-02). 전체 시험은 여기서 돌리지 않는다 — 브랜치 PR 의 CI 가 돌린다.
#
#   scripts/test.sh backend [pytest 인자…]      예) scripts/test.sh backend tests/test_refunds.py -q
#   scripts/test.sh e2e [playwright 인자…]      예) scripts/test.sh e2e --project=operator e2e/operator/appeals.spec.ts
#
# - 기계 전체에서 동시에 둘까지 — 셋째부터는 빈 칸을 기다린다(flock, 워크트리가 달라도 같은 칸을 센다).
# - 한 칸은 호스트 코어의 1/3 을 고정해서 쓴다(이 머신 12코어면 4) — pytest·Playwright 는 taskset,
#   e2e 스택 컨테이너는 `docker update --cpuset-cpus`. `--cpus` 몫 제한이 아니라 코어를 못 박는 이유는
#   web-rpg 가 겪었다: 몫이 차면 0.1초씩 통째로 멈춰 시험이 흔들린다.
# - 한 번에 400개를 넘게 돌리지 않는다 — pytest 는 conftest 가, e2e 는 이 스크립트가 미리 세어 거절한다.
# - e2e 는 CI 와 같은 프로덕션 이미지 스택(compose.dev + compose.ci)을 이 워크트리 전용 이름으로 띄우고,
#   끝나면 지운다. 되풀이할 때는 CODEMIT_E2E_KEEP=1 로 남겨 두고, 다 쓰면 `scripts/test.sh e2e-down`.
set -euo pipefail

cd "$(dirname "$0")/.."
kind="${1:-}"
[ $# -gt 0 ] && shift

SLOTS=2
LOCAL_TEST_LIMIT=400
NCPU=$(nproc)
CPUS=$((NCPU / 3))
[ "$CPUS" -ge 1 ] || CPUS=1
# e2e 일꾼은 코어 둘에 하나(web-rpg 와 같은 비율) — 정하지 않으면 Playwright 가 호스트 코어를 보고
# 여섯을 띄워 칸이 넘친다.
E2E_WORKERS=$(((CPUS + 1) / 2))
LOCK_DIR="${CODEMIT_TEST_LOCK_DIR:-/tmp/codemit-test-slots}"

usage() { sed -n '2,15p' "$0"; exit 2; }
case "$kind" in backend|e2e|e2e-down) ;; *) usage ;; esac

eval "$(sh docker/dev-env.sh)"
E2E_PROJECT="${COMPOSE_PROJECT_NAME}-e2e"
C=(docker compose -p "$E2E_PROJECT" -f docker/compose.dev.yaml -f docker/compose.ci.yaml)

if [ "$kind" = e2e-down ]; then
  "${C[@]}" down -v --remove-orphans
  exit 0
fi

# 빈 칸을 잡는다 — fd 를 쥔 채 이 스크립트가 끝나면 풀린다.
mkdir -p "$LOCK_DIR"
waited=0
while :; do
  for i in $(seq 1 "$SLOTS"); do
    exec {slot_fd}>"$LOCK_DIR/slot-$i.lock"
    if flock -n "$slot_fd"; then
      echo "$$ $kind $(pwd) $(date +%H:%M:%S)" >"$LOCK_DIR/slot-$i.who"
      slot=$i
      break 2
    fi
    exec {slot_fd}>&-
  done
  if [ $((waited % 30)) -eq 0 ]; then
    echo "시험 칸 빈 곳 기다림($SLOTS/$SLOTS 사용 중):"
    cat "$LOCK_DIR"/slot-*.who 2>/dev/null | sed 's/^/  /' || true
  fi
  sleep 5
  waited=$((waited + 5))
done
first=$(((slot - 1) * CPUS % NCPU))
CPUSET="$first-$((first + CPUS - 1))"
echo "시험 칸 $slot — 코어 $CPUSET (호스트 ${NCPU}코어의 1/3)"

case "$kind" in
  backend)
    docker compose -f docker/compose.dev.yaml up -d db >/dev/null
    docker update --cpuset-cpus "$CPUSET" "${COMPOSE_PROJECT_NAME}-db-1" >/dev/null
    cd backend
    # pyproject 의 `-n auto` 를 칸 크기로 덮는다 — 뒤에 준 값이 이긴다.
    exec taskset -c "$CPUSET" uv run pytest -n "$CPUS" "$@"
    ;;
  e2e)
    cleanup() {
      if [ -z "${CODEMIT_E2E_KEEP:-}" ]; then
        "${C[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
      fi
    }
    trap cleanup EXIT
    trap 'exit 130' INT TERM

    read_port() { "${C[@]}" port "$1" "$2" | head -n 1 | sed 's/.*://'; }

    "${C[@]}" up -d minio >/dev/null
    CODEMIT_MINIO_PORT=$(read_port minio 9000)
    export CODEMIT_MINIO_PORT
    echo "e2e 스택 굽고 띄우는 중($E2E_PROJECT, 캐시)…"
    "${C[@]}" up -d --build frontend operator classroom >/dev/null
    docker ps -q --filter "label=com.docker.compose.project=$E2E_PROJECT" |
      xargs docker update --cpuset-cpus "$CPUSET" >/dev/null

    CODEMIT_API_PORT=$(read_port backend 8000)
    # dev-env.sh 가 dev 스택의 주소로 채워 둔 값을 이 스택으로 덮는다 — 시드(`seed-http.ts`)는
    # 이 값을 포트보다 먼저 본다.
    CODEMIT_API_BASE_URL="http://127.0.0.1:$CODEMIT_API_PORT"
    CODEMIT_E2E_BASE_URL="http://127.0.0.1:$(read_port frontend 3000)"
    CODEMIT_OPERATOR_E2E_BASE_URL="http://127.0.0.1:$(read_port operator 3000)"
    CODEMIT_CLASSROOM_E2E_BASE_URL="http://127.0.0.1:$(read_port classroom 3000)"
    export CODEMIT_API_PORT CODEMIT_API_BASE_URL CODEMIT_E2E_BASE_URL CODEMIT_OPERATOR_E2E_BASE_URL CODEMIT_CLASSROOM_E2E_BASE_URL
    for url in "$CODEMIT_E2E_BASE_URL" "$CODEMIT_OPERATOR_E2E_BASE_URL" "$CODEMIT_CLASSROOM_E2E_BASE_URL"; do
      for _ in $(seq 1 90); do
        curl --fail --silent "$url/healthz" >/dev/null 2>&1 && break
        sleep 2
      done
      curl --fail --silent "$url/healthz" >/dev/null || { echo "$url 이 응답하지 않는다"; "${C[@]}" logs --tail 50; exit 1; }
    done

    pw=(taskset -c "$CPUSET" pnpm --dir frontend exec playwright test)
    count=$("${pw[@]}" --list "$@" 2>/dev/null | grep -c ' › ' || true)
    if [ "$count" -gt "$LOCAL_TEST_LIMIT" ]; then
      echo "시험 ${count}개를 한 번에 돌리려 했다 — 로컬은 ${LOCAL_TEST_LIMIT}개까지다. 파일·--project 로 좁히고, 전체는 브랜치 PR 의 CI 로 본다."
      exit 4
    fi

    # package.json 의 test:* 와 같은 두 패스 — 전역 상태를 건드리는 `@exclusive` 는 일꾼 하나로 따로 돈다.
    status=0
    "${pw[@]}" --workers="$E2E_WORKERS" --grep-invert @exclusive --pass-with-no-tests "$@" || status=$?
    "${pw[@]}" --workers=1 --grep @exclusive --pass-with-no-tests "$@" || status=$?
    exit "$status"
    ;;
esac
