#!/usr/bin/env bash
# 포크 PR 하나를 병합 대기열에 넣는다(#1084) — 포크는 자동 병합이 꺼져 있어 `gh pr merge` 가 거절한다.
#
#   bash scripts/fork/enqueue.sh <PR 번호>
set -euo pipefail
FORK=sandcorporation/laurio-restructure
id=$(gh pr view "$1" --repo "$FORK" --json id -q .id)
gh api graphql -f query='mutation($id: ID!) { enqueuePullRequest(input: {pullRequestId: $id}) { mergeQueueEntry { state position } } }' \
  -f id="$id" -q '.data.enqueuePullRequest.mergeQueueEntry | "대기열 \(.state) \(.position)번째"'
