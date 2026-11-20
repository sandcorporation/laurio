#!/bin/bash
# PR 검사의 e2e — 세 앱의 프로덕션 이미지 스택을 띄워 세 프로젝트를 돌린다
# (2026-10-02 Jenkinsfile.pr 에서 시작, 10-03~11-05 열차, 지금은 GitHub Actions `pr-check.yml` 의 e2e 잡이 부른다).
#
# **이미지는 두 길이다**(#712).
#   CODEMIT_IMAGE_TAG=<sha>-<arch>   PR 검사의 길 — `images.sh <arch>` 가 레지스트리에 올린 그 이미지를 받아
#                                    띄운다(`compose.ci-images.yaml`). 시험한 digest = 배포되는 digest.
#                                    받을 때 GHCR_TOKEN 이 있으면 그것으로 로그인한다(ghcr-login.sh).
#                                    받은 이미지는 지우지 않는다 — 다음 실행의 층 캐시다(macos-sweep.sh 가
#                                    저장소마다 가장 새것 하나만 남긴다).
#   (없음)                           스택이 `up --build` 로 직접 굽는다 — 로컬 `scripts/test.sh e2e` 와 같다. macos 노드는 실행기가
# 하나라 다른 빌드와 겹치지 않으므로 노드를 통째로 쓴다. 시험 하나 3초·재시도 0 은
# playwright.config.ts 가 정한다. 프로젝트마다 두 패스는 frontend/scripts/e2e-two-pass.sh 가 정의하고,
# 첫 패스가 붉어도 둘째(`@exclusive`) 패스까지 돈다 — 실패를 더 많이 남기려는 것이다(#700).
#
# 끝나면(성공·실패·중단 모두) 스택을 지운다 — 굽는 길이면 그 실행이 구운 이미지까지(`--rmi local`). 프로젝트
# 이름이 실행마다 달라(CODEMIT_CI_RUN_ID) 이미지가 새 이름으로 구워지므로, 남기면 Docker VM 디스크가
# 찬다(2026-10-14, 이미지 1,283개·51GB). 빌드 캐시는 남으니 다음 실행의 굽기는 캐시 히트다.
# 공용 base 이미지(postgres·redis·minio)는 compose 가 구운 것이 아니라 남는다.
# 프로젝트 하나가 실패해도 나머지는 끝까지 돈다.
#
# **Playwright 를 어디서 돌리나(#1109).** CODEMIT_E2E_PLAYWRIGHT_IMAGE=1(GitHub Actions 의 e2e 잡)이면 Playwright 만 공식
# 이미지(`scripts/ci/playwright-image`, 판·다이제스트 고정)에서 `--network host` 로 돈다 — 스택은 그대로 호스트의 docker
# compose 이고, 시험은 127.0.0.1 의 공개 포트로만 닿는다. 브라우저와 그 시스템 라이브러리·글꼴이 이미지에 있어 잡이 apt 도
# 브라우저 CDN 도 부르지 않는다(실행기 미러가 느린 날 조각 하나가 대기열을 붙잡았다). 이미지 판이 lockfile 의
# `@playwright/test` 와 다르면 시험 전에 실패한다(`playwright_image.py`). node_modules 는 호스트에서 깔고 저장소를 같은
# 경로로 마운트해 그대로 쓴다. 이미지 받기는 스택 굽기와 겹쳐 돈다. 없으면 예전처럼 호스트의 Playwright 다(로컬).
set -uo pipefail
cd "$(dirname "$0")/../.."
# playwright.config 의 입구 검사 — 이 노드는 Jenkins 가 통째로 쓰므로 test.sh 의 칸을 거치지 않는다.
export CODEMIT_TEST_ENTRY="scripts/ci/e2e.sh"

project=$(printf '%s' "${CODEMIT_CI_RUN_ID:-codemit-e2e-$$}-e2e" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | cut -c1-60)
C=(docker compose -p "$project" -f docker/compose.dev.yaml -f docker/compose.ci.yaml)
build_flag=(--build)
if [ -n "${CODEMIT_IMAGE_TAG:-}" ]; then
  C+=(-f docker/compose.ci-images.yaml)
  build_flag=()
  # shellcheck source=scripts/ci/ghcr-login.sh
  . scripts/ci/ghcr-login.sh
fi
# 이미지 층 캐시(GitHub Actions, #932) — 워크플로가 CODEMIT_BK_CACHE 를 주면 복원한 층을 읽는다(저장은 release.yml 의 cache 잡, #1090).
if [ -n "${CODEMIT_BK_CACHE:-}" ]; then
  C+=(-f docker/compose.ci-cache.yaml)
fi
# 노드 코어의 1/3 — Playwright 일꾼은 코어 둘에 하나보다 적게 둔다. 같은 노드의 Docker VM 안에서
# 앱 셋·백엔드 넷·DB 가 함께 돈다.
WORKERS=$(( $(getconf _NPROCESSORS_ONLN) / 3 ))
[ "$WORKERS" -ge 2 ] || WORKERS=2
# 코어가 적은 노드(GitHub 호스팅 실행기, #930)는 일꾼 수를 직접 준다 — 한도(3초)는 그대로다.
WORKERS="${CODEMIT_E2E_WORKERS:-$WORKERS}"
echo "코어 $(getconf _NPROCESSORS_ONLN) · Playwright 일꾼 $WORKERS"

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
  if [ -n "${CODEMIT_IMAGE_TAG:-}" ]; then ghcr_logout; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [ -n "${CODEMIT_IMAGE_TAG:-}" ]; then ghcr_login; fi
rm -rf test-results && mkdir -p test-results
summary=test-results/summary.txt
: >"$summary"
# 호스트(mac)의 1초 샘플 — 메모리 압력·스왑·load·Docker VM 프로세스·docker stats 를
# `test-results/host/*.log` 에(#716). 다음에 backend 요청 0건 틈이 생기면 VM·호스트 쪽을 배제하거나 짚는
# 증거다(#721). macOS 에서만 띄운다 — 다른 곳에서는 샘플러가 곧바로 끝나, 몇 분 뒤 cleanup 이 다른
# 프로세스가 물려받았을지 모르는 옛 pid 로 신호를 보내게 된다. 명령이 없어도 e2e 를 붉게 만들지 않는다.
if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
  bash scripts/ci/host-sample.sh test-results/host </dev/null >/dev/null 2>&1 &
  sampler=$!
fi

read_port() { "${C[@]}" port "$1" "$2" | head -n 1 | sed 's/.*://'; }

pw_image=""; pw_pull=""
if [ "${CODEMIT_E2E_PLAYWRIGHT_IMAGE:-}" = 1 ]; then
  pw_image=$(python3 scripts/ci/playwright_image.py) || exit 1
  echo "Playwright 이미지 $pw_image"
  pw_started=$SECONDS
  { docker pull -q "$pw_image" && echo "받기 $((SECONDS - pw_started))초"; } >test-results/playwright-pull.log 2>&1 &
  pw_pull=$!
fi

"${C[@]}" up -d minio >/dev/null
CODEMIT_MINIO_PORT=$(read_port minio 9000)
export CODEMIT_MINIO_PORT
echo "스택 띄우는 중($project, ${CODEMIT_IMAGE_TAG:-여기서 굽는다})…"
"${C[@]}" up -d ${build_flag[@]+"${build_flag[@]}"} frontend operator classroom events grader || { echo "스택을 띄우지 못했다"; exit 1; }
# 이 실행이 띄운 이미지의 digest — 「e2e 가 본 이미지 = prod 에 간 이미지」를 나중에 맞춰 본다(#712).
for service in backend frontend operator classroom; do
  image=$("${C[@]}" images -q "$service" 2>/dev/null | head -n 1)
  [ -n "$image" ] || continue
  printf '%s %s\n' "$service" "$(docker image inspect -f '{{join .RepoDigests " "}}' "$image" 2>/dev/null || echo "$image")"
done | tee test-results/images.txt

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
if [ -n "$pw_image" ]; then
  pw_waited=$SECONDS
  wait "$pw_pull" || { cat test-results/playwright-pull.log; echo "Playwright 이미지를 받지 못했다"; exit 1; }
  echo "Playwright 이미지 $(tail -n 1 test-results/playwright-pull.log), 스택 뒤 기다림 $((SECONDS - pw_waited))초"
else
  pnpm --dir frontend exec playwright install chromium >/dev/null || { echo "Playwright 브라우저를 받지 못했다"; exit 1; }
fi

# 두 패스(`@exclusive` 는 일꾼 하나로 따로)는 package.json 의 `test:*`·scripts/test.sh 와 같은
# frontend/scripts/e2e-two-pass.sh 다(#702). Playwright 는 실행마다 출력 폴더를 비우므로 패스마다
# `test-results/playwright/<프로젝트>[-exclusive]/` 에 따로 둔다(#699, 경로는 frontend 기준이라 `../`).
# 성공한 시험의 것은 `retain-on-failure` 가 남기지 않는다.
# CODEMIT_E2E_PATHS — 이 실행기가 돌 시험 파일(공백으로 나눈 Playwright 걸러내기 인자, e2e_plan.py #1089). 없으면 프로젝트 전부.
# 조각에는 `@exclusive` 시험이 없을 수 있어 빈 패스를 허용한다.
# 시험 시간 리포트(#1112) — 패스마다 `test-results/timings/<대상>[-exclusive].json`. 매시 e2e.yml 이 모아 조각 시간 기록을 만든다.
export E2E_TIMINGS_DIR="$PWD/test-results/timings"
run_target() {
  if [ -n "${CODEMIT_E2E_PATHS:-}" ]; then export E2E_ALLOW_EMPTY=1; fi
  export PLAYWRIGHT_WORKERS=$WORKERS
  export E2E_OUTPUT_DIR="../test-results/playwright/$1"
  export E2E_EXCLUSIVE_OUTPUT_DIR="../test-results/playwright/$1-exclusive"
  if [ -z "$pw_image" ]; then
    # CODEMIT_E2E_PATHS 는 공백으로 나눈 경로 목록이다
    # shellcheck disable=SC2086
    frontend/scripts/e2e-two-pass.sh "$1" ${CODEMIT_E2E_PATHS:-}
    return
  fi
  # 이미지 안: 호스트 사용자로(남는 파일이 root 것이 되지 않게), 시험이 읽는 환경만 넘긴다 — PLAYWRIGHT_BROWSERS_PATH 는
  # 이미지의 것(/ms-playwright)을 쓴다. pnpm 은 corepack 이 packageManager 판을 /tmp 에 깐다(apt 아님).
  local envs=() name
  while IFS= read -r name; do envs+=(-e "$name"); done < <(compgen -e | grep -E '^(CODEMIT_|E2E_|INTERNAL_API_TOKEN$|PLAYWRIGHT_WORKERS$|CI$|GITHUB_ACTIONS$)')
  # 작은따옴표 안은 안쪽 셸이 펼친다, CODEMIT_E2E_PATHS 는 공백으로 나눈 경로 목록이다
  # shellcheck disable=SC2016,SC2086
  docker run --rm --init --network host --ipc host --user "$(id -u):$(id -g)" \
    -v "$PWD:$PWD" -w "$PWD" -e HOME=/tmp -e COREPACK_HOME=/tmp/corepack -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    "${envs[@]}" "$pw_image" \
    bash -c 'mkdir -p /tmp/bin && corepack enable --install-directory /tmp/bin && PATH=/tmp/bin:$PATH exec frontend/scripts/e2e-two-pass.sh "$@"' \
    _ "$1" ${CODEMIT_E2E_PATHS:-}
}

failed=0
# GitHub Actions 는 실행기 둘로 나눠 `CODEMIT_E2E_TARGETS` 로 프로젝트를 고른다(#932). 없으면 셋 다.
for target in ${CODEMIT_E2E_TARGETS:-public operator classroom}; do
  started=$SECONDS
  if run_target "$target"; then
    echo "통과  e2e $target ($((SECONDS - started))초)" | tee -a "$summary"
  else
    echo "실패  e2e $target ($((SECONDS - started))초)" | tee -a "$summary"
    failed=1
  fi
done
exit "$failed"
