#!/usr/bin/env bash
# scripts/ci/e2e-seed-stale.sh 시험 — gh 와 씨앗 판정(e2e_durations.py missing)을 흉내 낸다. 네트워크·토큰 없음.
#   bash scripts/ci/e2e_seed_stale_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/ci" "$tmp/bin"
# 스크립트는 자기 폴더의 e2e_durations.py·ci-issue.sh 를 부른다 — 판정만 가짜로 바꾼 사본 폴더에서 돌린다
cp "$here/e2e-seed-stale.sh" "$here/ci-issue.sh" "$tmp/ci/"
cat > "$tmp/ci/e2e_durations.py" <<'PY'
import os, sys
SEED_SLACK = 5
if __name__ == "__main__" and sys.argv[1:] == ["missing"]:
    n = int(os.environ["STUB_MISSING"])
    print(n)
    for i in range(n):
        print(f"e2e/a/s{i}.spec.ts")
PY
cat > "$tmp/bin/gh" <<'GH'
#!/usr/bin/env bash
echo "gh $*" >> "$STUB_LOG"
case "$1 $2" in
  "issue list") echo "$STUB_OPEN" ;;
  "issue view") echo 1 ;;
  "issue create") printf '%s\n' "$@" > "$STUB_BODY"; echo "https://example.invalid/issues/9" ;;
  *) : ;;
esac
GH
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" STUB_LOG="$tmp/log" STUB_BODY="$tmp/body"
run() { : > "$STUB_LOG"; STUB_MISSING="$1" STUB_OPEN="${2:-}" bash "$tmp/ci/e2e-seed-stale.sh" >/dev/null; }
has() { grep -q -- "$1" "$STUB_LOG" || { echo "빠짐: $1"; cat "$STUB_LOG"; exit 1; }; }
hasnt() { ! grep -q -- "$1" "$STUB_LOG" || { echo "있으면 안 됨: $1"; cat "$STUB_LOG"; exit 1; }; }
run 5;   hasnt "issue create"; hasnt "issue close"               # 문턱 안, 열린 것 없음 — 아무것도 안 함
run 6;   has "issue create"; has "e2e 씨앗 기록이 낡았다"         # 문턱 밖 — 연다
grep -q 'e2e/a/s5.spec.ts' "$STUB_BODY" && grep -q 'gh run download' "$STUB_BODY" || { echo "본문에 목록·명령 없음"; cat "$STUB_BODY"; exit 1; }
run 6 7; hasnt "issue create"; hasnt "issue comment"             # 이미 열림 — 더하지 않는다
run 3 7; has "issue comment 7"; has "issue close 7"              # 문턱 안으로 — 닫는다
echo ok
