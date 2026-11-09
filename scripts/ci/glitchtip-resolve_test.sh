#!/usr/bin/env bash
# scripts/ci/glitchtip-resolve.sh 시험 — 임시 git 저장소와 가짜 curl. 네트워크·토큰 없음.
#   bash scripts/ci/glitchtip-resolve_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
script="$here/glitchtip-resolve.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/bin" "$tmp/repo/docker"
# 가짜 curl: 받은 설정(표준 입력)과 주소를 적고, 이슈 9 만 실패시킨다.
cat >"$tmp/bin/curl" <<'SH'
#!/usr/bin/env bash
cfg=$(cat)
url="${@: -1}"
printf '%s | %s | %s\n' "$cfg" "$url" "$*" >>"$CURL_LOG"
case "$url" in */issues/9/) printf 500 ;; *) printf 200 ;; esac
SH
chmod +x "$tmp/bin/curl"
export PATH="$tmp/bin:$PATH" CURL_LOG="$tmp/curl.log"
unset GLITCHTIP_TOKEN_FOR_AUTOMATION GLITCHTIP_URL

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_GLOBAL=/dev/null
cd "$tmp/repo"
git init -q -b main .
commit() { git commit -q --allow-empty -m "$1"; git rev-parse HEAD; }
A=$(commit "a")
B=$(commit "$(printf 'b 고침\n\nGlitchTip: 42')")
C=$(commit "$(printf 'c\n\n  glitchtip: 7 \nGlitchTip: 42')")
D=$(commit "$(printf 'd\n\nGlitchTip: 9\n본문 GlitchTip: 5 는 줄 머리가 아니다')")

pass=0 fail=0
check() {  # 이름, 출력에 있어야 할 말, 명령...
  local name="$1" want="$2"; shift 2
  local out rc=0
  : >"$CURL_LOG"
  out="$("$@" 2>&1)" || rc=$?
  if [ "$rc" = 0 ] && grep -qF -- "$want" <<<"$out"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1)); echo "실패: $name (rc=$rc)"; printf '  | %s\n' "$out"
  fi
}
env_file="$tmp/repo/docker/.env.prod"

: >"$env_file"
check '토큰이 없으면 넘어간다' 'GLITCHTIP_TOKEN_FOR_AUTOMATION 이 없다' bash "$script" "$A" "$C" "$env_file"
check '줄이 없으면 표시할 것이 없다' '표시할 것이 없다' bash "$script" "$D" "$D" "$env_file"

printf 'GLITCHTIP_TOKEN_FOR_AUTOMATION="tok-secret"\nSENTRY_DSN_BACKEND=https://k@gt.example.com/3\n' >"$env_file"
check '범위의 줄을 새 커밋부터 한 번씩' '표시할 이슈: 7 42' bash "$script" "$A" "$C" "$env_file"
if [ "$(wc -l <"$CURL_LOG")" = 2 ] && grep -qF 'https://gt.example.com/api/0/issues/42/' "$CURL_LOG" \
  && grep -qF 'Bearer tok-secret' "$CURL_LOG" && ! grep -qF -- '-H Authorization' "$CURL_LOG" \
  && ! cut -d'|' -f3 "$CURL_LOG" | grep -qF 'tok-secret'; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); echo "실패: DSN 주소·토큰은 설정으로만"; cat "$CURL_LOG"
fi
check '쓰기 실패에도 0' '1건을 쓰지 못했다' bash "$script" "$C" "$D" "$env_file"
check '직전 배포를 모르면 이 커밋 하나' '표시할 이슈: 42' bash "$script" "" "$B" "$env_file"
check '환경변수 주소가 먼저' 'resolved' env GLITCHTIP_URL=https://other.example.com/ bash "$script" "$A" "$B" "$env_file"
grep -qF 'https://other.example.com/api/0/issues/42/' "$CURL_LOG" && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "실패: GLITCHTIP_URL"; }

echo "glitchtip-resolve.sh 시험: 통과 $pass, 실패 $fail"
[ "$fail" = 0 ]
