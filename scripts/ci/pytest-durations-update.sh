#!/bin/bash
# pytest 조각의 시간 기록(scripts/ci/pytest-durations.json)을 다시 쓴다(#1083). 사람이 돌리고 결과를 커밋한다.
#
#   pytest-durations-update.sh            main 의 가장 최근 초록 release 실행에서
#   pytest-durations-update.sh RUN_ID     그 실행(PR 검사 실행도 된다)에서
#
# PR 검사의 pytest 조각 잡은 junit 을 산출물 `pytest-junit-<조각>` 으로 늘 올린다(14일). 넷을 받아 파일별 시간을 합친다.
# 언제: 조각 시간이 눈에 띄게 벌어졌을 때(가장 느린 조각 / 가장 빠른 조각 > 1.3), 큰 시험 파일을 옮기거나 나눈 뒤.
set -euo pipefail
cd "$(dirname "$0")/../.."

repo="${CODEMIT_GH_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
run="${1:-}"
if [ -z "$run" ]; then
  run=$(gh run list --repo "$repo" --workflow release.yml --branch main --status success -L 1 --json databaseId -q '.[0].databaseId')
  [ -n "$run" ] || { echo "main 의 초록 release 실행이 없다"; exit 1; }
fi

dir=$(mktemp -d)
trap 'rm -r "$dir"' EXIT
gh run download "$run" --repo "$repo" -p 'pytest-junit-*' -D "$dir"
xmls=()
while IFS= read -r f; do xmls+=("$f"); done < <(find "$dir" -name '*.xml' | sort)
[ "${#xmls[@]}" -gt 0 ] || { echo "실행 $run 에 pytest-junit 산출물이 없다"; exit 1; }
echo "실행 $run 의 junit ${#xmls[@]}개"
python3 scripts/ci/pytest_shards.py update "${xmls[@]}"
