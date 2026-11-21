#!/usr/bin/env bash
# PR 하나를 main 의 병합 대기열에 넣는다(#1118) — 저장소의 자동 병합이 꺼져 있어 `gh pr merge --squash` 는
# 대기열에 넣지 못하고 거절된다. 대기열이 머지 커밋으로 PR 검사를 다시 돌려 초록이면 squash 병합한다.
#
#   bash scripts/ci/enqueue.sh <PR 번호> [--wait]   # --wait: 병합·빠짐·시간 초과까지 기다린다(wait-merged.sh)
set -euo pipefail
if [ $# -lt 1 ] || [ $# -gt 2 ] || { [ $# -eq 2 ] && [ "$2" != "--wait" ]; }; then echo "사용: $0 <PR 번호> [--wait]" >&2; exit 2; fi
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
id=$(gh pr view "$1" --repo "$repo" --json id -q .id)
# shellcheck disable=SC2016  # $id 는 GraphQL 변수다 — 셸이 펼치면 안 된다
gh api graphql -f query='mutation($id: ID!) { enqueuePullRequest(input: {pullRequestId: $id}) { mergeQueueEntry { state position } } }' \
  -f id="$id" -q '.data.enqueuePullRequest.mergeQueueEntry | "대기열 \(.state) \(.position)번째"'
if [ "${2:-}" = "--wait" ]; then exec bash "$(dirname "$0")/wait-merged.sh" "$1"; fi
