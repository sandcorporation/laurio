#!/usr/bin/env bash
# scripts/ci/e2e-gate.sh 시험 — gh 를 흉내 낸다(실행 목록·잡 목록은 고정 JSON 에 jq). 네트워크·토큰 없음.
#   bash scripts/ci/e2e_gate_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"
cat > "$tmp/bin/gh" <<'GH'
#!/usr/bin/env bash
q=""; args=("$@")
for ((i=0; i<${#args[@]}; i++)); do [ "${args[i]}" = -q ] && q="${args[i+1]}"; done
case "$1 $2" in
  "run list") jq -r "$q" "$STUB_RUNS" ;;
  "api repos/x/y/actions/runs/"*) id="${2#repos/x/y/actions/runs/}"; id="${id%/jobs}"; jq -r "$q" "$STUB_DIR/jobs-$id.json" ;;
  *) echo "예상 밖 gh $*" >&2; exit 9 ;;
esac
GH
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" STUB_DIR="$tmp" STUB_RUNS="$tmp/runs.json" GH_REPO=x/y
iso() { date -u -d "$1 minutes ago" +%Y-%m-%dT%H:%M:%SZ; }
# 실행 하나: id status conclusion sha 몇분전 이름
runs=()
add() { runs+=("{\"databaseId\":$1,\"status\":\"$2\",\"conclusion\":\"$3\",\"headSha\":\"$4\",\"createdAt\":\"$(iso "$5")\",\"displayTitle\":\"$6\"}"); }
jobs_real() { echo '{"jobs":[{"name":"gate","conclusion":"success"},{"name":"e2e public","conclusion":"success"},{"name":"notify","conclusion":"success"}]}' > "$tmp/jobs-$1.json"; }
jobs_skipped() { echo '{"jobs":[{"name":"gate","conclusion":"success"},{"name":"e2e ${{ matrix.name }}","conclusion":"skipped"}]}' > "$tmp/jobs-$1.json"; }
flush() { (IFS=,; echo "[${runs[*]:-}]") > "$tmp/runs.json"; runs=(); }
decide() { EVENT="$1" SOURCE="${2:-}" SIM="${3:-none}" SHA=new RUN_ID=999 bash "$here/e2e-gate.sh" | tail -1; }
want() { [ "$1" = "$2" ] || { echo "기대 $2 · 실제 $1 — $3"; exit 1; }; }

flush;                                              want "$(decide schedule)" run=1 "기록이 없으면 돈다"
add 1 completed success old 120 "e2e [schedule]"; jobs_real 1; flush
want "$(decide schedule)" run=1 "두 시간 전이면 돈다"
want "$(decide workflow_dispatch merge)" run=1 "병합 사건도 돈다"
want "$(decide workflow_dispatch '' )" run=1 "수동은 늘 돈다"
want "$(decide workflow_dispatch merge fail)" run=0 "알림 시험은 e2e 를 돌지 않는다"
add 2 completed success new 90 "e2e [merge]"; jobs_real 2; flush
want "$(decide schedule)" run=0 "같은 sha 를 초록으로 돌았으면 쉰다"
want "$(decide workflow_dispatch merge)" run=0 "병합 사건도 같은 sha 면 쉰다"
want "$(decide workflow_dispatch '')" run=1 "수동은 같은 sha 여도 돈다"
add 3 completed failure old 30 "e2e [merge]"; jobs_real 3; flush
want "$(decide schedule)" run=0 "30분 전 실제 실행이 있으면 쉰다(병합 사건이 부른 것도 센다)"
want "$(decide workflow_dispatch merge)" run=0 "병합 사건끼리도 50분 창"
add 4 completed success old 60 "e2e [schedule]"; jobs_real 4; flush
want "$(decide schedule)" run=1 "50분 밖이면 돈다"
# 건너뛴 실행은 창을 늘리지 않는다 — 한 시간에 네 번 두드려 앞 시간의 건너뜀이 다음 시간을 막던 것
add 5 completed success old 15 "e2e [schedule]"; jobs_skipped 5
add 6 completed success old 45 "e2e [schedule]"; jobs_skipped 6
add 4 completed success old 60 "e2e [schedule]"; jobs_real 4; flush
want "$(decide schedule)" run=1 "건너뛴 실행은 50분 창에 안 센다"
# 수동·알림 시험 실행은 판정에 끼지 않는다
add 7 completed success old 10 "e2e [manual]"; jobs_real 7
add 8 completed success new 5 "e2e [sim]"; jobs_real 8; flush
want "$(decide schedule)" run=1 "수동·알림 시험은 창·같은 sha 판정에 안 든다"
# 도는 중인 실제 실행은 센다, 취소된 것은 안 센다
add 9 in_progress "" old 20 "e2e [merge]"; jobs_real 9; flush
want "$(decide workflow_dispatch merge)" run=0 "도는 중이면 쉰다"
add 10 completed cancelled old 20 "e2e [merge]"; jobs_real 10; flush
want "$(decide workflow_dispatch merge)" run=1 "취소된 실행은 안 센다"
# 호출자(release)는 RUN_ID=0 — 자기 자신을 거르지 않는다
add 11 completed success old 20 "e2e [merge]"; jobs_real 11; flush
want "$(EVENT=workflow_dispatch SOURCE=merge SIM=none SHA=new RUN_ID=0 bash "$here/e2e-gate.sh" | tail -1)" run=0 "호출자 판정도 같다"
echo ok
