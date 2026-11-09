#!/usr/bin/env bash
# 배포가 끝난 커밋 범위의 `GlitchTip: <id>` 줄을 GlitchTip 에서 해결 표시한다(#938) — oracle 의 `deploy-prod.sh` 가 mark 뒤에 부른다.
#
#   scripts/ci/glitchtip-resolve.sh <직전 배포 sha | 빈 값> <배포한 sha> [env 파일(기본 docker/.env.prod)]
#
# 예전에는 Jenkins 빌드 노드의 `build-images.sh` 가 `scripts/glitchtip_resolve.py`(지웠다)로 했다(자격은 Jenkins 의
# `glitchtip-automation-token`). 이미지를 Actions 가 굽게 되면서(#938) 빌드 노드 단계가 사라졌고, Actions 에는
# GITHUB_TOKEN 말고 비밀을 두지 않는다. 그래서 운영에 실제로 올라간 뒤 oracle 에서 한다 — 그곳 에이전트 컨테이너에는
# python3 가 없어(#849) git·curl 로만 쓴다. 읽는 줄의 꼴은 그때와 같다(줄 하나, 대소문자 무관).
#
# 자격: `GLITCHTIP_TOKEN_FOR_AUTOMATION`(스코프 event:write) — 환경변수, 없으면 env 파일의 같은 키. GlitchTip 주소는
# `GLITCHTIP_URL`, 없으면 env 파일의 `GLITCHTIP_URL`, 그것도 없으면 `SENTRY_DSN_BACKEND` 의 scheme://host 다.
# 토큰이 없으면 무엇을 못 했는지만 적고 넘어간다. **언제나 0 으로 끝난다** — 배포는 이미 끝났고, 표시가 안 된 것은
# 사람이 GlitchTip 에서 본다. 토큰은 curl 의 설정(표준 입력)으로만 넘긴다 — 명령줄·로그에 남지 않는다.
set -uo pipefail

base="${1:-}"
head="${2:?쓰는 법: $0 <직전 배포 sha | 빈 값> <배포한 sha> [env 파일]}"
env_file="${3:-docker/.env.prod}"
GIT=(git -c safe.directory="$PWD")

env_value() {  # env 파일에서 키 하나(마지막 줄, 양끝 따옴표 걷음). 없으면 빈 값.
  [ -f "$env_file" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$env_file" | tail -n 1 | sed "s/[[:space:]]*\$//; s/^[\"']//; s/[\"']\$//"
}

if [ -n "$base" ] && "${GIT[@]}" cat-file -e "${base}^{commit}" 2>/dev/null; then
  range="$base..$head"
else
  range="$head^!"
  echo "GlitchTip: 직전 배포를 모른다(${base:0:12}) — 이 커밋 하나만 본다"
fi

ids=$("${GIT[@]}" log --format=%B "$range" 2>/dev/null \
  | grep -iE '^[[:blank:]]*GlitchTip:[[:blank:]]*[0-9]+[[:blank:]]*$' \
  | grep -oE '[0-9]+' | awk '!seen[$0]++' | tr '\n' ' ' | sed 's/ $//')
if [ -z "$ids" ]; then
  echo "GlitchTip: 줄을 가진 커밋이 없다 — 표시할 것이 없다($range)"
  exit 0
fi
echo "GlitchTip 표시할 이슈: $ids"

token="${GLITCHTIP_TOKEN_FOR_AUTOMATION:-$(env_value GLITCHTIP_TOKEN_FOR_AUTOMATION)}"
if [ -z "$token" ]; then
  echo "GLITCHTIP_TOKEN_FOR_AUTOMATION 이 없다($env_file) — 표시하지 않고 넘어간다"
  exit 0
fi
url="${GLITCHTIP_URL:-$(env_value GLITCHTIP_URL)}"
if [ -z "$url" ]; then
  url=$(env_value SENTRY_DSN_BACKEND | sed -nE 's#^(https?)://([^@/]*@)?([^/]+).*#\1://\3#p')
fi
url="${url%/}"
if [ -z "$url" ]; then
  echo "GlitchTip 주소를 모른다(GLITCHTIP_URL·SENTRY_DSN_BACKEND 없음) — 표시하지 않고 넘어간다"
  exit 0
fi

failed=0
for id in $ids; do
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | curl --config - -sS -o /dev/null -w '%{http_code}' \
    --max-time 20 -X PUT -H 'Content-Type: application/json' --data '{"status":"resolved"}' "$url/api/0/issues/$id/" 2>/dev/null)
  if [ "$code" = 200 ]; then
    echo "  이슈 $id → resolved"
  else
    echo "  이슈 $id 쓰기 실패: ${code:-연결 실패}"
    failed=$((failed + 1))
  fi
done
[ "$failed" = 0 ] || echo "${failed}건을 쓰지 못했다 — GlitchTip 에서 눈으로 확인한다"
exit 0
