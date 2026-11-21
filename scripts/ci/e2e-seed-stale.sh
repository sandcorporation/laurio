#!/usr/bin/env bash
# main 의 e2e 씨앗 기록이 낡았는지 본다(#1251) — 씨앗(scripts/ci/e2e-durations.json)에 없는 시험이 SEED_SLACK(e2e_durations.py)을
# 넘으면 고정 제목 이슈를 열고, 문턱 안으로 돌아오면 닫는다. 방아쇠는 e2e.yml notify 잡(main 의 전체 실행)이다.
# PR 검사의 문턱(scripts/test_e2e_plan.py)은 그 PR 이 더한 시험을 빼고 세니, main 의 빚은 여기서 따로 알린다.
# 이미 열린 이슈가 있으면 실행마다 댓글을 더하지 않는다. GH_TOKEN·GH_REPO 환경, issues: read·write 권한 필요.
# 시험: scripts/ci/e2e_seed_stale_test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
title="e2e 씨앗 기록이 낡았다"
slack=$(cd "$here" && python3 -c 'import e2e_durations; print(e2e_durations.SEED_SLACK)')
out=$(python3 "$here/e2e_durations.py" missing)
count=$(head -n1 <<<"$out")
list=$(tail -n +2 <<<"$out" | sed 's/^/- `/; s/$/`/')
echo "씨앗에 없는 시험: ${count}개 (문턱 ${slack})"
if [ "$count" -gt "$slack" ]; then
  export TITLE="$title"
  open=$(gh issue list --state open --label ci-red --limit 50 --json number,title -q '[.[]|select(.title==$ENV.TITLE)][0].number // empty')
  [ -n "$open" ] && { echo "이미 열린 이슈 #$open"; exit 0; }
  body="main 의 씨앗 기록 \`scripts/ci/e2e-durations.json\` 에 없는 시험이 ${count}개다(문턱 ${slack}). 이대로면 모든 PR 의 검사(\`scripts/test_e2e_plan.py\`)가 붉다 — PR 이 더한 시험은 세지 않으니 이 빚은 main 에서 갚는다.

빠진 시험:
${list}

다시 쓰는 법 — 가장 새 main 전체 실행의 산출물로:
\`\`\`
run=\$(gh run list --workflow e2e.yml --branch main --status success --limit 1 --json databaseId -q '.[0].databaseId')
gh run download \"\$run\" -n e2e-durations -D .e2e-durations-seed
cp .e2e-durations-seed/record.json scripts/ci/e2e-durations.json
\`\`\`"
  bash "$here/ci-issue.sh" fail "$title" "$body"
else
  bash "$here/ci-issue.sh" ok "$title" "복구됨 — 씨앗에 없는 시험 ${count}개(문턱 ${slack})"
fi
