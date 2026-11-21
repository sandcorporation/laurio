#!/usr/bin/env bash
# 대기열에 넣은 PR 이 병합되거나 대기열에서 빠질 때까지 기다린다(#1156).
#
#   bash scripts/ci/wait-merged.sh <PR 번호>        # 기본 40분
#   WAIT_MERGED_TIMEOUT=600 WAIT_MERGED_INTERVAL=10 bash scripts/ci/wait-merged.sh <PR>
#
# 종료 코드: 0 병합됨(병합 sha 를 찍는다) / 1 대기열에서 빠짐(까닭·실패 잡·실행 주소를 찍는다) / 2 시간 초과·사용법.
# 병합은 `mergedAt`, 대기열 상태는 `mergeQueueEntry{state}`, 빠짐은 타임라인
# `RemovedFromMergeQueueEvent.reason` 으로 읽는다 — `gh pr view --json` 에는 대기열 필드가 없다.
set -euo pipefail
[ $# -eq 1 ] || { echo "사용: $0 <PR 번호>" >&2; exit 2; }
pr="$1"
timeout="${WAIT_MERGED_TIMEOUT:-2400}"
interval="${WAIT_MERGED_INTERVAL:-20}"
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
owner="${repo%%/*}" name="${repo##*/}"

# shellcheck disable=SC2016  # $o·$n·$p 는 GraphQL 변수다
query='query($o: String!, $n: String!, $p: Int!) { repository(owner: $o, name: $n) { pullRequest(number: $p) {
  mergedAt mergeCommit { oid } mergeQueueEntry { state }
  timelineItems(last: 5, itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT]) { nodes { ... on RemovedFromMergeQueueEvent { createdAt reason } } } } } }'

# 빠진 뒤 줄에 다시 넣었으면(entry 가 있으면) 옛 빠짐 기록은 무시한다 — 아래 루프가 entry 를 먼저 본다.
report_removed() {
  local reason="$1" runs run url jobs
  echo "대기열에서 빠졌다 — 까닭: ${reason:-알 수 없음}"
  runs=$(gh run list --repo "$repo" --event merge_group --limit 30 \
    --json databaseId,url,conclusion,headBranch \
    -q "[.[] | select(.headBranch | test(\"/pr-${pr}-\")) | select(.conclusion==\"failure\")][0] | [.databaseId // \"\", .url // \"\"] | @tsv" 2>/dev/null || true)
  run="${runs%%$'\t'*}" url="${runs#*$'\t'}"
  if [ -n "$run" ]; then
    jobs=$(gh run view "$run" --repo "$repo" --json jobs \
      -q '[.jobs[] | select(.conclusion=="failure") | .name] | join(", ")' 2>/dev/null || true)
    echo "실패한 잡: ${jobs:-알 수 없음}"
    echo "실행: $url"
    if gh run view "$run" --repo "$repo" --log-failed 2>/dev/null | grep -qF '시험 본문이 CPU'; then
      echo "CPU 한도(#1014) 시험이 실패했다"
    fi
  else
    echo "대기열 실행을 찾지 못했다 — gh run list --event merge_group"
  fi
}

deadline=$(( $(date +%s) + timeout ))
while :; do
  out=$(gh api graphql -f query="$query" -f o="$owner" -f n="$name" -F p="$pr" \
    -q '.data.repository.pullRequest | [.mergedAt // "", .mergeCommit.oid // "", .mergeQueueEntry.state // "", (.timelineItems.nodes[-1].reason // "")] | join("|")' 2>&1) || {
    echo "조회 실패(다시 시도): $out" >&2; out='|||'
  }
  IFS='|' read -r merged sha state reason <<<"$out"
  if [ -n "$merged" ]; then echo "병합됨 $sha"; exit 0; fi
  if [ -z "$state" ] && [ -n "$reason" ]; then report_removed "$reason"; exit 1; fi
  if [ "$(date +%s)" -ge "$deadline" ]; then echo "시간 초과(${timeout}초) — 대기열 상태: ${state:-없음}" >&2; exit 2; fi
  sleep "$interval"
done
