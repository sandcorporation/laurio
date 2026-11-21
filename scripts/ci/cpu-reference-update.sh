#!/bin/bash
# 시험 CPU 한도 배율의 기준(backend/tests/cpu_reference.json)을 다시 쓴다(#1211). 사람이 돌리고 결과를 커밋한다.
#
#   cpu-reference-update.sh        최근 초록 병합 대기열 실행 8번(전부를 돈다, #1090)의 junit 에서
#   cpu-reference-update.sh N      최근 N번에서
#
# 시험마다 CPU 초의 중앙값을 낸다 — 실행기 셋이 섞인 값이라 배율 1.0 이 가운데 무리다(`backend/tests/cpu_speed.py`).
# 언제: 무거운 시험을 많이 고치거나 옮긴 뒤, junit 의 `cpu_scale` 이 느린 조각에서도 1.0 에 붙어 있을 때.
set -euo pipefail
cd "$(dirname "$0")/../.."

repo="${CODEMIT_GH_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
count="${1:-8}"
mapfile -t runs < <(gh run list --repo "$repo" --workflow pr-check.yml --event merge_group --status success \
  -L "$count" --json databaseId -q '.[].databaseId')
[ "${#runs[@]}" -ge 3 ] || { echo "초록 병합 대기열 실행이 ${#runs[@]}번뿐이다 — 3번 이상 필요하다"; exit 1; }

dir=$(mktemp -d)
trap 'rm -r "$dir"' EXIT
for run in "${runs[@]}"; do
  gh run download "$run" --repo "$repo" -p 'pytest-junit-*' -D "$dir/$run"
done
mapfile -t xmls < <(find "$dir" -name '*.xml' | sort)
echo "실행 ${#runs[@]}번의 junit ${#xmls[@]}개"
python3 backend/tests/cpu_speed.py update "${xmls[@]}"
