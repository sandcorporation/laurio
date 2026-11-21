#!/usr/bin/env bash
# scripts/ci/wait-merged.sh 시험 — gh 를 흉내 낸다. 실제 대기열·PR 을 쓰지 않는다.
#   bash scripts/ci/wait-merged_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"
# 가짜 gh: GQL_OUT(graphql 의 -q 결과 한 줄 = 병합시각|sha|상태|빠짐까닭), RUN_LIST·RUN_JOBS·RUN_LOG 를 그대로 돌려준다.
cat > "$tmp/bin/gh" <<'GH'
#!/usr/bin/env bash
case "$1 $2" in
  "repo view") echo "o/r" ;;
  "api graphql") printf '%b\n' "$GQL_OUT" ;;
  "run list") printf '%b\n' "${RUN_LIST:-}" ;;
  "run view") if [[ " $* " == *" --log-failed "* ]]; then printf '%s\n' "${RUN_LOG:-}"; else printf '%s\n' "${RUN_JOBS:-}"; fi ;;
esac
GH
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" WAIT_MERGED_INTERVAL=0

pass=0 fail=0
check() {  # 이름, 기대 종료코드, 출력에 있어야 할 말, 환경변수(VAR=값)...
  local name="$1" want_rc="$2" want_out="$3"; shift 3
  local out rc=0
  out="$(env "$@" bash "$here/wait-merged.sh" 7 2>&1)" || rc=$?
  if [ "$rc" = "$want_rc" ] && grep -qF -- "$want_out" <<<"$out"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1)); echo "실패: $name (rc=$rc 기대 $want_rc)"; printf '  | %s\n' "$out"
  fi
}

check '병합됨' 0 '병합됨 abc123' 'GQL_OUT=2026-11-21T00:00:00Z|abc123||'
check '빠짐 — 까닭·실패 잡·실행 주소' 1 'FAILED_CHECKS' \
  'GQL_OUT=|||FAILED_CHECKS' 'RUN_LIST=111\thttps://example.test/runs/111' 'RUN_JOBS=pytest 3, guard' 'RUN_LOG=boom'
check '빠짐 — 실패 잡 이름' 1 '실패한 잡: pytest 3, guard' \
  'GQL_OUT=|||FAILED_CHECKS' 'RUN_LIST=111\thttps://example.test/runs/111' 'RUN_JOBS=pytest 3, guard' 'RUN_LOG=boom'
check '빠짐 — 실행 주소' 1 'https://example.test/runs/111' \
  'GQL_OUT=|||FAILED_CHECKS' 'RUN_LIST=111\thttps://example.test/runs/111' 'RUN_JOBS=x' 'RUN_LOG=boom'
check '빠짐 — CPU 한도 한 줄' 1 'CPU 한도(#1014)' \
  'GQL_OUT=|||FAILED_CHECKS' 'RUN_LIST=111\thttps://example.test/runs/111' 'RUN_JOBS=x' 'RUN_LOG=시험 본문이 CPU 2.10초를 썼다'
check '빠짐 — 실행을 못 찾음' 1 '대기열 실행을 찾지 못했다' 'GQL_OUT=|||FAILED_CHECKS'
check '대기열에 있는 동안은 옛 빠짐 기록을 무시하고 시간 초과' 2 '시간 초과' \
  'GQL_OUT=||QUEUED|FAILED_CHECKS' WAIT_MERGED_TIMEOUT=0
check '시간 초과' 2 '시간 초과' 'GQL_OUT=||QUEUED|' WAIT_MERGED_TIMEOUT=0
echo "wait-merged.sh 시험: 통과 $pass, 실패 $fail"
[ "$fail" = 0 ]
