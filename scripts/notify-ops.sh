#!/usr/bin/env bash
# 운영 담당에게 Orca 메일 한 통을 보낸다 — 운영 알림(ci-red·제보·자동화 실패)이 모두 이 하나를 부른다(#1374).
#
#   scripts/notify-ops.sh <제목> <본문 파일>
#
# 받는 곳은 저장소에 적지 않는다(공개 저장소). 환경변수 CODEMIT_OPS_NOTIFY_ON(Orca 기계)·CODEMIT_OPS_NOTIFY_TO(받는 이)로
# 받고, 비어 있으면 `${XDG_CONFIG_HOME:-$HOME/.config}/codemit/ops-notify.env` 의 같은 이름 줄(KEY=값)을 읽는다.
# 둘 다 없으면 「받는 곳 설정 없음」을 표준오류에 쓰고 2 로 끝난다 — 조용히 넘어가지 않는다.
#
# 성공 판정: orca 가 0 으로 끝나고 출력에 `messageId=` 줄이 있을 때만 보낸 것이다(0). 아니면 1.
# `orca` 경로는 CODEMIT_ORCA(기본 orca)로 바꿔 끼운다 — 시험이 가짜를 꽂는다.
set -uo pipefail

[ "$#" -eq 2 ] || { sed -n '2,3p' "$0" >&2; exit 64; }
subject="$1"; body_file="$2"
[ -f "$body_file" ] || { echo "본문 파일이 없다: $body_file" >&2; exit 64; }

on="${CODEMIT_OPS_NOTIFY_ON:-}"; to="${CODEMIT_OPS_NOTIFY_TO:-}"
conf="${XDG_CONFIG_HOME:-$HOME/.config}/codemit/ops-notify.env"
if { [ -z "$on" ] || [ -z "$to" ]; } && [ -r "$conf" ]; then
  while IFS='=' read -r k v; do
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    case "$k" in
      CODEMIT_OPS_NOTIFY_ON) [ -n "$on" ] || on="$v" ;;
      CODEMIT_OPS_NOTIFY_TO) [ -n "$to" ] || to="$v" ;;
    esac
  done < "$conf"
fi
if [ -z "$on" ] || [ -z "$to" ]; then
  echo "받는 곳 설정 없음: CODEMIT_OPS_NOTIFY_ON·CODEMIT_OPS_NOTIFY_TO 환경변수나 $conf 가 필요하다" >&2
  exit 2
fi

rc=0
out="$("${CODEMIT_ORCA:-orca}" orchestration send --on "$on" --to "$to" --type status \
        --subject "$subject" --body-file "$body_file" 2>&1)" || rc=$?
printf '%s\n' "$out"
[ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q 'messageId=' && exit 0
exit 1
