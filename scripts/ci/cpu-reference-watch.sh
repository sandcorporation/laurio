#!/usr/bin/env bash
# CPU 기준표(backend/tests/cpu_reference.json)가 낡았는지 본다(#1222) — 문서 규칙 대신 검사가 말한다.
# 최근 초록 병합 대기열 실행 CPU_WATCH_RUNS(기본 8)번의 junit 에서 실행마다 「시험 CPU 초 / 기준」의 중앙값,
# 그 값들의 중앙값을 낸다(backend/tests/cpu_speed.py drift). 범위(0.85~1.2) 밖이면 고정 제목 ci-red 이슈를 열고,
# 이미 열려 있으면 본문을 새 값으로 바꾼다(병합마다 댓글을 쌓지 않는다). 범위 안으로 돌아오면 「복구됨」 댓글로 닫는다.
# 방아쇠는 main 병합마다 도는 release.yml 의 `cpu_reference_watch` 잡이다. GH_TOKEN·GH_REPO 환경, issues: write·actions: read.
# 시험: scripts/ci/cpu_reference_watch_test.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
title="CPU 기준표가 낡았다 — cpu-reference-update.sh"
dir=$(mktemp -d)
trap 'rm -r "$dir"' EXIT
bash scripts/ci/cpu-junit.sh "$dir" "${CPU_WATCH_RUNS:-8}" || { echo "판정하지 않는다 — 이슈는 그대로"; exit 0; }
code=0
report=$(python3 backend/tests/cpu_speed.py drift "$dir"/*/) || code=$?
echo "$report"
case "$code" in
  0) bash scripts/ci/ci-issue.sh ok "$title" "복구됨 — $report" ;;
  3)
    body="$report

기준이 낡았다 — 시험 CPU 한도의 실행기 배율이 이 값만큼 어긋난다. 다시 쓴다: \`bash scripts/ci/cpu-reference-update.sh\` → \`backend/tests/cpu_reference.json\` 을 PR 로. 범위 안으로 돌아오면 이 이슈는 저절로 닫힌다(release.yml \`cpu_reference_watch\`)."
    export TITLE="$title"
    open=$(gh issue list --state open --label ci-red --limit 50 --json number,title -q '[.[]|select(.title==$ENV.TITLE)][0].number // empty')
    if [ -n "$open" ]; then gh issue edit "$open" --body "$body"; else bash scripts/ci/ci-issue.sh fail "$title" "$body"; fi ;;
  *) exit "$code" ;;
esac
