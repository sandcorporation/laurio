#!/usr/bin/env bash
# scripts/ci/e2e-stale.sh 시험 — gh 를 흉내 낸다. 네트워크·토큰 없음.
#   bash scripts/ci/e2e_stale_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"
cat > "$tmp/bin/gh" <<'GH'
#!/usr/bin/env bash
echo "gh $*" >> "$STUB_LOG"
case "$1 $2" in
  "run list") echo "$STUB_LAST" ;;
  "issue list") echo "$STUB_OPEN" ;;
  *) echo "https://example.invalid/issues/9" ;;
esac
GH
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" STUB_LOG="$tmp/log"
iso() { date -u -d "$1 hours ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-"$1"H +%Y-%m-%dT%H:%M:%SZ; }
run() { : > "$STUB_LOG"; STUB_LAST="$1" STUB_OPEN="${2:-}" bash "$here/e2e-stale.sh" >/dev/null; }
has() { grep -q "$1" "$STUB_LOG" || { echo "빠짐: $1"; cat "$STUB_LOG"; exit 1; }; }
hasnt() { ! grep -q "$1" "$STUB_LOG" || { echo "있으면 안 됨: $1"; cat "$STUB_LOG"; exit 1; }; }
run "$(iso 1)";  hasnt "issue create"; hasnt "issue comment"          # 최근 — 열린 이슈 없으니 아무것도 안 함
run "$(iso 1)" 7; has "issue comment 7"; has "issue close 7"          # 복구 — 열린 이슈를 닫는다
run "$(iso 5)";  has "issue create"                                   # 5시간 — 연다
run "$(iso 5)" 7; hasnt "issue create"; hasnt "issue comment"         # 이미 열림 — 더하지 않는다
run "";          has "issue create"                                   # 예약 실행 없음
echo ok
