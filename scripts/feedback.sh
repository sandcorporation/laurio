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
#   feedback.sh screenshot ID    스크린샷을 이 컴퓨터의 임시 폴더(저장소 밖, 700)에 파일(600)로 받고 경로만 찍는다(#1347).
#                                제보 없음 4 · 스크린샷 없음 5 · 저장소에 그림 없음 6 · 운영에 못 닿음 2.
#                                받은 지 24시간 지난 파일은 다음 screenshot 때 지워진다.
#   feedback.sh screenshot-rm [ID…]  받은 그림을 지운다(번호를 주지 않으면 전부). 일이 끝나면 부른다.
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
# 스크린샷을 받는 곳 — 저장소 밖, 이 사용자만(#1347). 그림에는 학생 정보가 찍힐 수 있다.
_tmp="${TMPDIR:-/tmp}"
SHOT_DIR="${CODEMIT_FEEDBACK_SHOT_DIR:-${_tmp%/}/codemit-feedback-shots-$(id -u)}"
SHOT_TTL_MIN="${CODEMIT_FEEDBACK_SHOT_TTL_MIN:-1440}"

# remote 인자… — 운영 backend 에서 `manage.py feedback_report 인자…`. 인자는 숫자·상태 이름·`-` 만 온다(아래에서 거른다).
# 실패하면 진짜 종료 코드와 한 줄 까닭(`원격 실패 rc=…`)을 표준오류에 남기고 그 코드를 돌려준다(#1280). 다시 시도하지 않는다.
remote() {
  local rc=0
  "$SSH" -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST" \
    "c=\$(docker ps --filter label=com.docker.compose.project=$COMPOSE_PROJECT --filter label=com.docker.compose.service=backend --format '{{.Names}}' | head -n1); [ -n \"\$c\" ] || { echo 'backend 컨테이너를 찾지 못했다' >&2; exit 3; }; docker exec -i \"\$c\" python manage.py feedback_report $*" || rc=$?
  [ "$rc" -eq 0 ] || echo "원격 실패 rc=$rc: $(remote_reason "$rc")" >&2
  return "$rc"
}

remote_reason() {
  case "$1" in
    255) echo "ssh 가 운영에 닿지 못했다" ;;
    3) echo "backend 컨테이너가 없다(배포 중 컨테이너 교체로 보인다)" ;;
    4) echo "그런 제보가 없다" ;;
    5) echo "그 제보에는 스크린샷이 없다" ;;
    6) echo "스크린샷이 저장소에 없다(보존 기간이 지났을 수 있다)" ;;
    129|130|131|137|143) echo "시그널($(($1 - 128)))로 종료됐다(배포 중 컨테이너 교체로 보인다)" ;;
    *) echo "운영 명령이 실패했다" ;;
  esac
}

need_ids() {
  [ "$#" -gt 0 ] || { echo "제보 번호가 필요하다" >&2; exit 2; }
  for id in "$@"; do [[ "$id" =~ ^[0-9]+$ ]] || { echo "제보 번호는 숫자다: $id" >&2; exit 2; }; done
}

# 받는 폴더를 이 사용자 것(700)으로 세우고 묵은 그림을 지운다. 남의 것이거나 링크면 쓰지 않는다.
shot_dir() {
  if [ -L "$SHOT_DIR" ]; then echo "스크린샷 폴더가 링크다 — 쓰지 않는다: $SHOT_DIR" >&2; exit 2; fi
  mkdir -p -m 700 "$SHOT_DIR"
  [ -O "$SHOT_DIR" ] || { echo "스크린샷 폴더가 내 것이 아니다: $SHOT_DIR" >&2; exit 2; }
  chmod 700 "$SHOT_DIR"
  find "$SHOT_DIR" -maxdepth 1 -type f -name 'report-*' -mmin "+$SHOT_TTL_MIN" -delete
}

# 그림의 앞 바이트로 확장자를 고른다(서버가 올릴 때 png·jpeg·webp 만 받는다).
shot_ext() {
  python3 -c '
import sys
h = open(sys.argv[1], "rb").read(12)
print("png" if h.startswith(b"\x89PNG") else "jpg" if h.startswith(b"\xff\xd8\xff")
      else "webp" if h[:4] == b"RIFF" and h[8:12] == b"WEBP" else "bin")' "$1"
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
  screenshot)
    id="${2:-}"
    need_ids "$id"
    umask 077
    shot_dir
    part="$SHOT_DIR/.report-$id.part"
    rc=0
    # 바이트를 셸 변수로 받지 않는다(NUL 이 잘린다) — 곧장 파일로.
    remote screenshot "$id" > "$part" || rc=$?
    if [ "$rc" -ne 0 ]; then
      rm -f "$part"
      case "$rc" in 4|5|6) exit "$rc" ;; *) exit 2 ;; esac
    fi
    dest="$SHOT_DIR/report-$id.$(shot_ext "$part")"
    rm -f "$SHOT_DIR/report-$id".*
    mv "$part" "$dest"
    chmod 600 "$dest"
    printf '%s\n' "$dest"
    ;;
  screenshot-rm)
    shift
    [ "$#" -eq 0 ] || need_ids "$@"
    [ -d "$SHOT_DIR" ] || exit 0
    if [ "$#" -eq 0 ]; then
      find "$SHOT_DIR" -maxdepth 1 -type f \( -name 'report-*' -o -name '.report-*' \) -delete
    else
      for id in "$@"; do rm -f "$SHOT_DIR/report-$id".* "$SHOT_DIR/.report-$id.part"; done
    fi
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
    sed -n '2,21p' "$0" >&2
    exit 2
    ;;
esac
