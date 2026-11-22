#!/usr/bin/env bash
# main push 뒤 알림(#1325) — after-push.yml 이 부르고, 알림은 ci-red 이슈(scripts/ci/ci-issue.sh)로 낸다.
# 대장 메일함으로는 work 의 Orca 자동화(scripts/ci/ci_red_relay.py)가 넘긴다 — docs/ops/deploy-paths.md.
#
#   direct   표식 없는 main 직접 push — 커밋마다 이슈 하나(제목에 sha). 환경: SHA·UNMARKED·RUN_URL
#   result   뒤따른 검사의 결과 — 「핫픽스 뒤 검사 실패」 이슈 하나를 열고(이어지면 댓글) 초록이면 닫는다.
#            환경: KIND(queue|hotfix|direct)·RESULT(needs.check.result)·SHA·RUN_URL·RUN_ID(실패 잡 찾기, 없어도 된다)
#            queue 면 검사를 다시 돌지 않았지만 대기열의 같은 검사가 이 sha 에서 초록이었다 — 열린 이슈가 있으면 닫는다.
#            cancelled 인데 실패한 잡이 없으면(새 push 가 밀어냄) 아무것도 하지 않는다.
# GH_TOKEN·GH_REPO 는 환경에서, issues: write·actions: read.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
mode=${1:-}
: "${SHA:?SHA 가 필요하다}"
RUN_URL=${RUN_URL:-}
RESULT_TITLE="핫픽스 뒤 검사 실패 — main 붉음"

case "$mode" in
  direct)
    title="표식 없는 main 직접 push — ${SHA:0:7}"
    body="main 에 대기열도 핫픽스 표식(\`Hotfix:\` 꼬리말)도 없이 오른 커밋 \`${SHA}\`. 표식 없는 커밋: ${UNMARKED:-?}. 뒤따른 검사는 그대로 돈다. 핫픽스 길은 \`scripts/hotfix.py\` 다(docs/ops/deploy-paths.md). 읽었으면 닫는다. 실행: ${RUN_URL}"
    bash "$here/ci-issue.sh" fail "$title" "$body"
    ;;
  result)
    kind=${KIND:-}; result=${RESULT:-}
    if [ "$kind" = queue ]; then
      bash "$here/ci-issue.sh" ok "$RESULT_TITLE" "복구됨 \`${SHA}\` — 병합 대기열 커밋(대기열의 PR 검사가 이 sha 에서 초록). 실행: ${RUN_URL}"
      exit 0
    fi
    if [ "$result" = success ]; then
      bash "$here/ci-issue.sh" ok "$RESULT_TITLE" "복구됨 \`${SHA}\` — 뒤따른 검사 초록. 실행: ${RUN_URL}"
      exit 0
    fi
    jobs=""
    if [ -n "${RUN_ID:-}" ]; then
      jobs=$(gh run view "$RUN_ID" --json jobs -q '[.jobs[]|select(.conclusion=="failure" or .conclusion=="timed_out")|.name]|join(", ")' || true)
    fi
    if [ "$result" != failure ] && [ -z "$jobs" ]; then
      echo "검사 결과 ${result:-?}, 실패한 잡 없음 — 알리지 않는다"
      exit 0
    fi
    body="main \`${SHA}\`(${kind:-?}) 의 뒤따른 검사(PR 검사와 같은 것)가 실패했다. 실패한 잡: ${jobs:-?}. 운영은 그대로다 — 고치는 커밋을 핫픽스 길로 다시 보낸다. 되돌림은 대장이 정한다. 실행: ${RUN_URL}"
    bash "$here/ci-issue.sh" fail "$RESULT_TITLE" "$body"
    ;;
  *) echo "mode: direct|result" >&2; exit 2 ;;
esac
