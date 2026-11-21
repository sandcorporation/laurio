#!/usr/bin/env bash
# scripts/ci/cpu-reference-watch.sh 시험 — gh 를 흉내 낸다. junit 은 지금 기준표의 시험들에 STUB_RATIO 를 곱해 만든다. 네트워크·토큰 없음.
#   bash scripts/ci/cpu_reference_watch_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"
cat > "$tmp/bin/gh" <<'GH'
#!/usr/bin/env bash
echo "gh $*" >> "$STUB_LOG"
case "$1 $2" in
  "run list") printf '%s\n' $STUB_RUNS ;;
  "run download")
    shift 2; while [ "$1" != -D ]; do shift; done; mkdir -p "$2/pytest-junit-1"
    python3 - "$2/pytest-junit-1/junit.xml" "$STUB_RATIO" "$STUB_REF" <<'PY'
import json, sys
from xml.sax.saxutils import quoteattr as q
out, ratio, ref = sys.argv[1], float(sys.argv[2]), json.load(open(sys.argv[3]))
cases = "".join(
    f'<testcase classname={q(k.split("::", 1)[0])} name={q(k.split("::", 1)[1])}><properties>'
    f'<property name="cpu_seconds" value="{v * ratio:.3f}"/></properties></testcase>'
    for k, v in ref.items()
)
open(out, "w").write(f'<testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>')
PY
    ;;
  "issue list") echo "$STUB_OPEN" ;;
  *) echo "https://example.invalid/issues/9" ;;
esac
GH
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" STUB_LOG="$tmp/log" GH_REPO=o/r STUB_REF="$here/../../backend/tests/cpu_reference.json"
run() { : > "$STUB_LOG"; STUB_RATIO="$1" STUB_OPEN="${2:-}" STUB_RUNS="${3:-1 2 3}" bash "$here/cpu-reference-watch.sh" >/dev/null; }
has() { grep -q "$1" "$STUB_LOG" || { echo "빠짐: $1"; cat "$STUB_LOG"; exit 1; }; }
hasnt() { ! grep -q "$1" "$STUB_LOG" || { echo "있으면 안 됨: $1"; cat "$STUB_LOG"; exit 1; }; }
run 1.0;      hasnt "issue create"; hasnt "issue edit"; hasnt "issue close"   # 범위 안 — 열린 이슈 없으니 아무것도 안 함
run 0.7;      has "issue create"                                             # 기준보다 빠르다(낡음) — 연다
run 1.3;      has "issue create"                                             # 기준보다 느리다(낡음) — 연다
run 1.3 7;    has "issue edit 7"; hasnt "issue create"; hasnt "issue comment" # 이미 열림 — 본문을 새 값으로
run 1.0 7;    has "issue comment 7"; has "issue close 7"                    # 범위 안으로 돌아옴 — 닫는다
run 1.3 7 "1 2"; hasnt "issue "                                              # 실행 3번 미만 — 판정하지 않는다
echo ok
