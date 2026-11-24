#!/usr/bin/env bash
# 운영 경보 채널로 한 줄(#1166) — 배포 자동 되돌리기(`post-deploy-rollback.sh`·`deploy-prod.sh`)가 부른다.
#
#   bash ops-alert.sh '<한 줄>' [env 파일]      # 언제나 0 으로 끝난다
#
# 받는 곳은 backend 운영 경보(#830·#1123, `ops_metrics.alerts.post_webhook`)와 같다 — 키 `OPS_ALERT_DISCORD_WEBHOOK_URL`,
# 디스코드 웹훅에 `{"content": …}`, 소켓 한도 5초(`OPS_ALERT_DISCORD_TIMEOUT_SECONDS`). backend 컨테이너로 보내지 않고
# 호스트에서 curl 로 보내는 까닭: 되돌리기가 실패하면 알려야 할 것이 바로 backend 이고, oracle 에는 python3 가 없다(#849).
#
# 둘째 알림 목적지(`OPS_ALERT_NOTICE_WEBHOOK_URL`)가 있으면 같은 본문을 나란히 보낸다 — 비어 있으면 건너뛰고, 둘째의 실패는
# 디스코드 전송과 종료 코드에 닿지 않는다.
#
# 주소는 환경변수가 먼저, 없으면 env 파일(기본 `docker/.env.prod`)의 같은 이름 줄이다. 주소는 curl 의 설정(표준 입력)으로만
# 넘긴다 — 명령줄·로그에 남지 않는다. 주소가 없거나 보내기가 실패해도 경고 한 줄만 찍고 0 으로 끝난다 — 경보가
# 되돌리기를 막지 않는다. bash 3.2 문법만 쓴다.
set -uo pipefail

text="${1:-}"
env_file="${2:-docker/.env.prod}"
[ -n "$text" ] || { echo "경보: 보낼 줄이 없다 — 건너뛴다"; exit 0; }

# 주소는 환경변수가 먼저, 없으면 env 파일의 같은 이름 줄이다.
read_url() {
  local name="$1" value
  eval "value=\"\${$name-}\""
  if [ -z "$value" ] && [ -f "$env_file" ]; then
    value=$(sed -n "s/^$name=//p" "$env_file" | tail -n 1)
    value="${value%\"}"
    value="${value#\"}"
  fi
  printf '%s' "$value"
}

# JSON 문자열 — 역슬래시·따옴표만 이스케이프하고 줄바꿈은 빈칸으로(한 줄 경보다).
body=$(printf '%s' "$text" | tr '\n\r\t' '   ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')

# send <라벨> <주소> — 주소는 curl 설정(표준 입력)으로만 넘긴다.
send() {
  local label="$1" url="$2" code
  code=$(printf 'url = "%s"\n' "$url" | curl --config - -sS -o /dev/null -w '%{http_code}' --max-time 5 \
    -H 'Content-Type: application/json' --data-binary "{\"content\":\"$body\"}" 2>/dev/null) || code="${code:-000}"
  case "$code" in
    2??) echo "경보: ${label}보냈다" ;;
    *) echo "경보: ${label}보내지 못했다(HTTP ${code:-000}) — 되돌리기와 무관하다" ;;
  esac
}

url=$(read_url OPS_ALERT_DISCORD_WEBHOOK_URL)
notice_url=$(read_url OPS_ALERT_NOTICE_WEBHOOK_URL)
if [ -n "$notice_url" ]; then
  send "둘째 목적지 " "$notice_url"
fi
if [ -z "$url" ]; then
  echo "경보: OPS_ALERT_DISCORD_WEBHOOK_URL 이 비어 있다 — 보내지 않는다"
else
  send "" "$url"
fi
exit 0
