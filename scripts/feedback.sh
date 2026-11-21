#!/usr/bin/env bash
# 운영 건의·버그 제보를 대장 메일함으로 넘긴다(#1240). Orca 자동화(docs/ops/feedback-relay.md)가 쓴다.
# daypage 건의함 길(scripts/suggestions.sh)을 본떴다 — 다른 것은 배정 기록이 이 컴퓨터의 파일이 아니라
# 운영 DB(FeedbackReport.taken_at·forwarded_at)에 있다는 것뿐이다.
#
#   feedback.sh check            전달할 제보가 있으면 0, 없으면 1, 운영에 못 닿으면 2  ← Orca 자동화의 precheck
#   feedback.sh list             전달할 제보를 JSON 한 줄씩 {"id","kind","app","received_at"} (기록을 바꾸지 않는다)
#   feedback.sh take [N]         list 와 같되 집은 것으로 기록한다(N 기본 20). 15분 안에 전달되지 않으면 다시 나온다.
#   feedback.sh forward ID       대장 메일함(switchboard sandcorp/boss)으로 번호·갈래·앱·받은 시각만 보낸다.
#                                switchboard 가 0 으로 끝나고 「#번호」를 찍어야 보낸 것이다 — 그때만 전달 표시를
#                                하고, 아니면 되돌려(untake) 0 이 아닌 코드로 끝난다.
#   feedback.sh untake ID…       집은 기록을 지운다(다음 check 에서 다시 잡힌다)
#   feedback.sh mark ID…         보내지 않고 전달 표시만 한다(처음 켤 때 지난 제보를 거르는 용도)
#   feedback.sh show ID          제보 하나를 읽는다(내용·상태·이력, 스크린샷은 있는지만)
#   feedback.sh status ID received|in_progress|deployed|declined "처리 글"
#                                상태를 바꾼다 — 운영자 화면과 같은 길이라 제보자에게 앱 안 알림이 간다.
#
# 운영 접근은 work → ssh oracle → 운영 backend 컨테이너의 `manage.py feedback_report` 하나다. 컨테이너 이름은
# 교체 배포 중에 잠시 바뀌므로 compose 표지(project·service)로 그때그때 찾는다.
set -euo pipefail

SSH_HOST="${CODEMIT_FEEDBACK_SSH_HOST:-oracle}"
SSH="${CODEMIT_FEEDBACK_SSH:-ssh}"
COMPOSE_PROJECT="${CODEMIT_FEEDBACK_COMPOSE_PROJECT:-codemit-prod}"
RELAY_TO="${CODEMIT_FEEDBACK_RELAY_TO:-sandcorp/boss}"
RELAY_PROFILE="${CODEMIT_FEEDBACK_RELAY_PROFILE:-codemit-coordinator}"
RELAY_TASK="${CODEMIT_FEEDBACK_RELAY_TASK:-codemit-feedback}"
SWITCHBOARD="${CODEMIT_SWITCHBOARD:-$HOME/.local/bin/switchboard}"

# remote 인자… — 운영 backend 에서 `manage.py feedback_report 인자…`. 인자는 숫자·상태 이름·`-` 만 온다(아래에서 거른다).
remote() {
  "$SSH" -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST" \
    "c=\$(docker ps --filter label=com.docker.compose.project=$COMPOSE_PROJECT --filter label=com.docker.compose.service=backend --format '{{.Names}}' | head -n1); [ -n \"\$c\" ] || { echo 'backend 컨테이너를 찾지 못했다' >&2; exit 3; }; docker exec -i \"\$c\" python manage.py feedback_report $*"
}

need_ids() {
  [ "$#" -gt 0 ] || { echo "제보 번호가 필요하다" >&2; exit 2; }
  for id in "$@"; do [[ "$id" =~ ^[0-9]+$ ]] || { echo "제보 번호는 숫자다: $id" >&2; exit 2; }; done
}

kind_label() { case "$1" in suggestion) echo 건의 ;; bug) echo 버그 ;; *) echo "$1" ;; esac; }
app_label() { case "$1" in contest) echo 공모전 ;; classroom) echo 강의실 ;; *) echo "$1" ;; esac; }
field() { python3 -c 'import json,sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$1"; }

case "${1:-}" in
  check)
    out="$(remote list --limit 1)" || exit 2
    [ -n "$out" ]
    ;;
  list)
    remote list --limit 100
    ;;
  take)
    n="${2:-20}"
    [[ "$n" =~ ^[0-9]+$ ]] || { echo "개수는 숫자다: $n" >&2; exit 2; }
    remote take --limit "$n"
    ;;
  forward)
    id="${2:-}"
    need_ids "$id"
    summary="$(remote summary "$id")"
    kind="$(kind_label "$(printf '%s' "$summary" | field kind)")"
    app="$(app_label "$(printf '%s' "$summary" | field app)")"
    at="$(printf '%s' "$summary" | field received_at)"
    subject="[제보] codemit #$id $kind · $app"
    body="제보 #$id · $kind · $app · 받은 시각 $at
scripts/feedback.sh show $id"
    rc=0
    out="$(SWITCHBOARD_PROFILE="$RELAY_PROFILE" "$SWITCHBOARD" send --to "$RELAY_TO" --task "$RELAY_TASK" \
             --subject "$subject" --body "$body" 2>&1)" || rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -Eq '^#[0-9]+ '; then
      remote mark-forwarded "$id"
    else
      remote untake "$id" || true
      echo "대장에게 못 보내 제보 #$id 를 되돌렸다(다음 check 에서 다시 잡힌다)" >&2
      exit 1
    fi
    ;;
  untake)
    shift
    need_ids "$@"
    for id in "$@"; do remote untake "$id"; done
    ;;
  mark)
    shift
    need_ids "$@"
    for id in "$@"; do remote mark-forwarded "$id"; done
    ;;
  show)
    need_ids "${2:-}"
    remote show "$2"
    ;;
  status)
    id="${2:-}"; to="${3:-}"; note="${4:-}"
    need_ids "$id"
    case "$to" in received|in_progress|deployed|declined) ;;
      *) echo "상태는 received·in_progress·deployed·declined 가운데 하나다" >&2; exit 2 ;; esac
    # 처리 글은 표준 입력으로 넘겨 따옴표·한글이 ssh 를 거치며 깨지지 않게 한다.
    printf '%s' "$note" | remote status "$id" "$to" --note -
    ;;
  *)
    sed -n '2,17p' "$0" >&2
    exit 2
    ;;
esac
