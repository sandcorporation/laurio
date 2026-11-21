#!/bin/bash
# 최근 초록 병합 대기열 실행(전부를 돈다, #1090)의 백엔드 junit 을 받는다 — 실행마다 <DIR>/<실행 번호>/ 아래(#1211, #1222).
#   cpu-junit.sh DIR [N]   N 기본 8. 실행이 3번 안 되면 종료 코드 1.
# cpu-reference-update.sh(기준을 다시 쓴다)와 cpu-reference-watch.sh(기준이 낡았나)가 쓴다. GH_TOKEN·actions: read 필요.
set -euo pipefail
dir=$1; count="${2:-8}"
repo="${GH_REPO:-${CODEMIT_GH_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}}"
mapfile -t runs < <(gh run list --repo "$repo" --workflow pr-check.yml --event merge_group --status success \
  -L "$count" --json databaseId -q '.[].databaseId')
[ "${#runs[@]}" -ge 3 ] || { echo "초록 병합 대기열 실행이 ${#runs[@]}번뿐이다 — 3번 이상 필요하다"; exit 1; }
for run in "${runs[@]}"; do
  gh run download "$run" --repo "$repo" -p 'pytest-junit-*' -D "$dir/$run"
done
echo "실행 ${#runs[@]}번의 junit $(find "$dir" -name '*.xml' | wc -l)개"
