#!/bin/bash
# PR 검사가 「바뀐 것」을 잴 기준 커밋(#1210) — PR 이 가는 브랜치(base)와 HEAD 의 merge-base.
#
#   scripts/ci/pr-base.sh [base 커밋]   →  기준 커밋 한 줄(못 찾으면 빈 줄 — changed.sh 가 「전부」로 읽는다)
#
# pr-check.yml 의 plan 이 `github.event.pull_request.base.sha`(대기열이면 `merge_group.base_sha`)를 준다.
#   main 으로 가는 PR      → main 과의 merge-base — 예전(`git merge-base origin/main HEAD`)과 같다
#   spec/* 으로 가는 티켓 PR → 스펙 브랜치와의 merge-base — 스펙에 먼저 모인 티켓은 「바뀐 것」에 들지 않는다
# base 를 안 줬거나 이 클론에 그 커밋이 없으면 origin/main 과의 merge-base 로 돌아간다 — 더 넓게 고를 뿐 덜 고르지 않는다.
set -uo pipefail
target="${1:-}"
if [ -n "$target" ] && git cat-file -e "$target^{commit}" 2>/dev/null; then
  git merge-base "$target" HEAD 2>/dev/null || true
else
  git merge-base origin/main HEAD 2>/dev/null || true
fi
