#!/usr/bin/env bash
# CI 빨강 알림 — 라벨 ci-red 이슈, 종류(제목)마다 열린 것 하나(#1015). 열린 ci-red 이슈 = 지금 빨강.
#   fail <제목> <본문>  같은 제목의 열린 이슈가 있으면 댓글, 없으면 연다(라벨이 없으면 만든다)
#   ok   <제목> <본문>  있으면 댓글을 달고 닫는다
# 담당(#1113): CI_RED_ASSIGNEE(저장소 변수 — 계정 이름은 코드에 적지 않는다)가 있으면 이슈를 연 뒤·담당 없는 열린 이슈에
#   댓글을 달 때 담당으로 지정한다. 지정은 이슈 만들기와 따로, 실패해도 경고만(이슈는 반드시 열린다). 비면 요약에 경고.
# GH_TOKEN·GH_REPO 는 환경에서, issues: write 권한 필요.
set -euo pipefail
mode=$1; export TITLE=$2; body=$3; label=ci-red
n=$(gh issue list --state open --label "$label" --limit 50 --json number,title -q '[.[]|select(.title==$ENV.TITLE)][0].number // empty' || true)
assignee=${CI_RED_ASSIGNEE:-}
assign() {  # $1 = 이슈 번호 또는 URL
  if [ -z "$assignee" ]; then
    echo "::warning::CI_RED_ASSIGNEE 가 비어 있어 담당을 지정하지 않았다"
    echo "⚠️ 저장소 변수 CI_RED_ASSIGNEE 가 비어 있어 ci-red 이슈에 담당이 없다" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    return 0
  fi
  gh issue edit "$1" --add-assignee "$assignee" || echo "::warning::담당 지정 실패 — 이슈는 담당 없이 열려 있다"
}
case "$mode" in
  fail)
    if [ -n "$n" ]; then
      gh issue comment "$n" --body "$body"
      cnt=$(gh issue view "$n" --json assignees -q '.assignees|length' || echo 1)
      if [ "$cnt" = 0 ]; then assign "$n"; fi
    else
      gh label create "$label" --color D93F0B --description "지금 빨간 CI" >/dev/null 2>&1 || true
      url=$(gh issue create --title "$TITLE" --label "$label" --body "$body")
      echo "$url"
      assign "${url##*/}"
    fi ;;
  ok)
    if [ -n "$n" ]; then gh issue comment "$n" --body "$body"; gh issue close "$n"; fi ;;
  *) echo "mode: fail|ok" >&2; exit 2 ;;
esac
