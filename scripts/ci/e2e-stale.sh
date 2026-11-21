#!/usr/bin/env bash
# main 의 전체 e2e 가 멈췄는지 본다(#1122, #1154 에서 「예약만」이던 기준을 「전체 실행」으로) — GitHub 예약(cron)은 부하 때 실행을 건너뛴다.
# 마지막 전체 실행(예약 + 병합 사건 dispatch, 건너뛴 실행 포함 — 판정이 돈 흔적이다)이 E2E_STALE_HOURS(기본 3)시간보다 오래면 고정 제목 이슈를 열고,
# 다시 돌았으면 「복구됨」 댓글을 달고 닫는다. 방아쇠는 main 병합마다 도는 release.yml 의 `e2e_watch` 잡(e2e_dispatch 가 부른 뒤)이다.
# 전체 실행은 실행 이름이 `e2e [schedule]`·`e2e [merge]` 로 시작한다(e2e.yml run-name).
# 이미 열린 이슈가 있으면 병합마다 댓글을 더하지 않는다. GH_TOKEN·GH_REPO 환경, issues: read·write 권한 필요.
# 시험: scripts/ci/e2e_stale_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
title="e2e 가 멈췄다 — main 의 전체 화면 시험이 돌지 않는다"
max=${E2E_STALE_HOURS:-3}
last=$(gh run list --workflow e2e.yml --branch main --limit 30 --json createdAt,displayTitle \
  -q '[.[]|select(.displayTitle|test("^e2e \\[(schedule|merge)\\]"))][0].createdAt // empty')
now=$(date -u +%s)
if [ -n "$last" ]; then
  age=$(( (now - $(date -u -d "$last" +%s 2>/dev/null || date -u -j -f %Y-%m-%dT%H:%M:%SZ "$last" +%s)) / 3600 ))
else
  age=999
fi
echo "마지막 전체 실행: ${last:-없음} (${age}시간 전, 한도 ${max}시간)"
if [ "$age" -ge "$max" ]; then
  export TITLE="$title"
  open=$(gh issue list --state open --label ci-red --limit 50 --json number,title -q '[.[]|select(.title==$ENV.TITLE)][0].number // empty')
  [ -n "$open" ] && { echo "이미 열린 이슈 #$open"; exit 0; }
  bash "$here/ci-issue.sh" fail "$title" "e2e.yml 의 마지막 전체 실행(예약·병합 사건)이 ${last:-없음}(${age}시간 전)이다 — \`gh workflow run e2e.yml --ref main -f source=merge\` 로 지금 돌릴 수 있다. 이 시각 뒤에 병합된 커밋은 전체 화면 시험을 거치지 않았다."
else
  bash "$here/ci-issue.sh" ok "$title" "복구됨 — 마지막 전체 실행 ${last}"
fi
