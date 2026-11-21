#!/usr/bin/env bash
# main 의 전체 e2e 를 지금 돌아야 하는가(#1154) — e2e.yml 의 gate 잡과 release.yml 의 e2e_dispatch 잡이 같은 판정을 쓴다.
# 「main 의 전체 실행」 = 예약(schedule)과 main 병합 사건이 부른 dispatch(`-f source=merge`). 둘 다 실행 이름이 `e2e [schedule]`·`e2e [merge]` 로 시작한다
# (e2e.yml 의 run-name — gh 는 workflow_dispatch 입력으로 거를 수 없어 이름에 새긴다). 수동 실행·알림 시험은 판정에 끼지 않는다.
# 쉬는 경우: 알림 시험 / 직전에 실제로 e2e 를 돈 전체 실행이 같은 sha 를 초록으로 끝냈다 / 50분 안에 실제로 e2e 를 돈(또는 도는 중인) 다른 전체 실행이 있다.
# 「실제로」 = e2e 조각 잡이 skipped 가 아니다 — 건너뛴 실행(gate 가 쉰 것)은 50분 창을 늘리지 않는다(늘리면 한 시간에 네 번 두드릴 때 다음 시간 두드림까지 쉬어 영영 안 돈다).
# 수동 실행(`workflow_dispatch` 에 source 없음)·다른 사건은 늘 돈다.
# 환경: EVENT·SIM(none|fail|ok)·SOURCE(merge|…)·SHA·RUN_ID(이 실행, 호출자가 실행이 아니면 0)·GH_TOKEN·GH_REPO. 출력: `run=0|1` 한 줄(마지막), 앞에 이유.
# 시험: scripts/ci/e2e_gate_test.sh
set -euo pipefail
event=${EVENT:-}
sim=${SIM:-none}
source_=${SOURCE:-}
sha=${SHA:-}
run_id=${RUN_ID:-0}
window=${E2E_WINDOW_MINUTES:-50}

run=1
[ "$sim" = none ] || run=0

if [ "$run" = 1 ] && { [ "$event" = schedule ] || { [ "$event" = workflow_dispatch ] && [ "$source_" = merge ]; }; }; then
  cut=$(date -u -d "${window} minutes ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-"${window}"M +%Y-%m-%dT%H:%M:%SZ)
  export CUT="$cut" SELF="$run_id"
  # 최근 전체 실행(새것부터): 번호·상태·결론·sha·시각
  # shellcheck disable=SC2016  # $ENV 는 jq 식이다
  rows=$(gh run list --workflow e2e.yml --branch main --limit 30 \
    --json databaseId,status,conclusion,headSha,createdAt,displayTitle \
    -q '.[]|select(.displayTitle|test("^e2e \\[(schedule|merge)\\]"))|select(.databaseId != ($ENV.SELF|tonumber))|[.databaseId,.status,.conclusion,.headSha,.createdAt]|@tsv' || true)

  # 이 실행이 e2e 조각을 실제로 돌았는가(건너뛴 실행 제외)
  real() {
    local n
    n=$(gh api "repos/${GH_REPO}/actions/runs/$1/jobs" --paginate \
      -q '[.jobs[]|select(.name|startswith("e2e "))|select(.conclusion != "skipped")]|length' | awk '{s+=$1} END{print s+0}')
    [ "${n:-0}" -gt 0 ]
  }

  decided_last=0
  recent=0
  while IFS=$'\t' read -r id status conclusion head created; do
    [ -n "$id" ] || continue
    # 창 밖이고 직전 결과도 이미 정했으면 더 안 본다(API 호출을 줄인다)
    [ "$decided_last" = 1 ] && [[ ! "$created" > "$cut" ]] && break
    # 취소된 실행은 e2e 를 끝까지 돈 것이 아니다
    [ "$conclusion" = cancelled ] && continue
    real "$id" || continue
    if [ "$status" != completed ]; then
      recent=$((recent + 1)); continue
    fi
    if [ "$decided_last" = 0 ] && { [ "$conclusion" = success ] || [ "$conclusion" = failure ]; }; then
      decided_last=1
      echo "직전 실제 실행: #$id $conclusion $head"
      [ "$conclusion" = success ] && [ "$head" = "$sha" ] && run=0
    fi
    [[ "$created" > "$cut" ]] && recent=$((recent + 1))
  done <<<"$rows"
  echo "${window}분 안의 실제 전체 실행: $recent"
  [ "$recent" -gt 0 ] && run=0
fi
echo "run=$run"
