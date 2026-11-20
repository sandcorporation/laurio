#!/usr/bin/env bash
# 배포 뒤 확인(#1092, spec #1079 결정 6) — 바꿔 끼운 직전 1분 안에 서비스가 실제로 일하는지 본다.
#
#   bash scripts/ci/post-deploy-check.sh           # 확인한다(0 통과 · 1 실패)
#   bash scripts/ci/post-deploy-check.sh --mode    # 스위치 값(off|check|rollback)만 낸다
#
# `deploy.sh health` 는 교체 단계의 문지기다 — 새 컨테이너가 DB·Redis 에 닿는지(`?scope=ready`)만 150초까지 본다.
# 여기는 그 뒤에 한 번 더, 짧은 한도 안에 셋을 본다:
#
#   준비        backend 컨테이너 안에서 `/api/health?scope=ready` 가 200
#   작업자      backend 의 `/api/health`(작업자 생존 신호 `HEALTH_REQUIRED_WORKERS` 까지, #949)가 200 이고,
#               celery-worker 안에서 `celery inspect ping` 에 답하는 작업자가 있다
#   핵심 경로   `CODEMIT_POSTDEPLOY_URLS` 의 주소마다 2xx·3xx(바깥 길 — 프록시·공개 앱·API 를 지난다)
#
# 항목은 차례로, 하나의 한도(`CODEMIT_POSTDEPLOY_SECONDS`, 기본 60초) 안에서 통과할 때까지 다시 본다.
# 한도가 끝나면 남은 항목은 실패다.
#
# **스위치 `CODEMIT_POSTDEPLOY`(기본 off)** — off: 확인도 되돌리기도 없다(지금 배포 그대로) · check: 확인하고 실패면
# 배포를 실패(2)로 끝낸다 · rollback: 실패면 직전 배포 표식의 이미지로 되돌린다(scripts/ci/post-deploy-rollback.sh).
# 값은 환경변수가 먼저, 없으면 `docker/.env.prod` 의 같은 이름 줄이다 — 호스트·주소는 코드에 두지 않는다.
# 주소가 없는데 켜져 있으면 핵심 경로가 실패한다(조용히 통과하지 않는다).
#
# 시험·dev 시연용: `POSTDEPLOY_COMPOSE`(compose 명령 앞부분), `POSTDEPLOY_ENV_FILE`, `CODEMIT_POSTDEPLOY_INTERVAL`.
# bash 3.2 문법만 쓴다(macOS 에서 dev 시연을 돈다).
set -uo pipefail

ENV_FILE="${POSTDEPLOY_ENV_FILE:-docker/.env.prod}"
COMPOSE="${POSTDEPLOY_COMPOSE:-docker compose -f docker/compose.prod.yaml --env-file docker/.env.prod}"

# 환경변수 → env 파일의 `KEY=값` 줄(마지막 것) → 기본값. 파일을 source 하지 않는다 — 비밀 값이 함께 있다.
setting() {
  local key="$1" default="$2" value
  value="${!key-}"
  if [ -z "$value" ] && [ -f "$ENV_FILE" ]; then
    value=$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)
    value="${value%\"}"
    value="${value#\"}"
  fi
  printf '%s' "${value:-$default}"
}

MODE=$(setting CODEMIT_POSTDEPLOY off)
case "$MODE" in
  off|check|rollback) ;;
  *) echo "CODEMIT_POSTDEPLOY=$MODE 는 모르는 값이다 (off|check|rollback)" >&2; exit 1 ;;
esac
if [ "${1:-}" = --mode ]; then
  echo "$MODE"
  exit 0
fi

LIMIT=$(setting CODEMIT_POSTDEPLOY_SECONDS 60)
INTERVAL=$(setting CODEMIT_POSTDEPLOY_INTERVAL 5)
URLS=$(setting CODEMIT_POSTDEPLOY_URLS "" | tr ',' ' ')
case "$LIMIT$INTERVAL" in *[!0-9]*) echo "한도·간격은 초(정수)다: $LIMIT $INTERVAL" >&2; exit 1 ;; esac

start=$SECONDS
deadline=$((start + LIMIT))

# backend 컨테이너 안에서 친다 — backend 는 호스트 포트를 열지 않는다(deploy.sh 의 django_answers 와 같은 요청).
# Host 는 허용 호스트의 첫 값 — `*`(dev)는 Host 로 보낼 수 없어(400) 127.0.0.1, `.example` 꼴은 점을 뗀다.
backend_health() {
  # shellcheck disable=SC2086
  $COMPOSE exec -T backend python -c "import os,urllib.request,sys; host=(os.environ.get('DJANGO_ALLOWED_HOSTS') or '').split(',')[0].strip().lstrip('.'); host='127.0.0.1' if host in ('','*') else host; req=urllib.request.Request('http://127.0.0.1:8000/api/health$1', headers={'Host': host, 'X-Forwarded-Proto': 'https'}); sys.exit(0 if urllib.request.urlopen(req, timeout=3).status==200 else 1)" >/dev/null 2>&1
}
check_ready() { backend_health '?scope=ready'; }
check_workers() {
  backend_health '' || return 1
  # shellcheck disable=SC2086
  $COMPOSE exec -T celery-worker celery -A config inspect ping --timeout 3 >/dev/null 2>&1
}
check_paths() {
  [ -n "$URLS" ] || { echo "  CODEMIT_POSTDEPLOY_URLS 가 비었다 — 핵심 경로를 볼 수 없다"; return 1; }
  local url
  for url in $URLS; do
    curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null || return 1
  done
}

failed=""
for item in ready workers paths; do
  case "$item" in
    ready) label="준비" ;;
    workers) label="작업자" ;;
    paths) label="핵심 경로" ;;
  esac
  while :; do
    if "check_$item"; then
      echo "확인 $label: 통과 ($((SECONDS - start))초)"
      break
    fi
    if [ $((SECONDS + INTERVAL)) -gt "$deadline" ]; then
      echo "확인 $label: 실패 — ${LIMIT}초 안에 통과하지 못했다"
      failed="$failed $label"
      break
    fi
    sleep "$INTERVAL"
  done
done

if [ -n "$failed" ]; then
  echo "배포 뒤 확인 실패:$failed"
  exit 1
fi
echo "배포 뒤 확인 통과 ($((SECONDS - start))초)"
