#!/usr/bin/env bash
# CI 빨강 알림 — 라벨 ci-red 이슈, 종류(제목)마다 열린 것 하나(#1015). 열린 ci-red 이슈 = 지금 빨강.
#   fail <제목> <본문>  같은 제목의 열린 이슈가 있으면 댓글, 없으면 연다(라벨이 없으면 만든다)
#   ok   <제목> <본문>  있으면 댓글을 달고 닫는다
# GH_TOKEN·GH_REPO 는 환경에서, issues: write 권한 필요.
set -euo pipefail
mode=$1; export TITLE=$2; body=$3; label=ci-red
n=$(gh issue list --state open --label "$label" --limit 50 --json number,title -q '[.[]|select(.title==$ENV.TITLE)][0].number // empty' || true)
case "$mode" in
  fail)
    if [ -n "$n" ]; then
      gh issue comment "$n" --body "$body"
    else
      gh label create "$label" --color D93F0B --description "지금 빨간 CI" >/dev/null 2>&1 || true
      gh issue create --title "$TITLE" --label "$label" --body "$body"
    fi ;;
  ok)
    if [ -n "$n" ]; then gh issue comment "$n" --body "$body"; gh issue close "$n"; fi ;;
  *) echo "mode: fail|ok" >&2; exit 2 ;;
esac
