#!/usr/bin/env bash
# Orca 자동화의 진입 스크립트(#1252) — main 체크아웃을 origin/main 으로 따라잡은 뒤 본 명령을 부르고,
# 「정상 종료 코드」가 아닌 실패는 운영 담당 Orca 메일(scripts/notify-ops.sh)로 드러낸다.
#
#   scripts/automation-run.sh <이름> [--ok 0,1] -- <명령> [인자…]
#
#   이름      알림 상태 파일 이름이자 메일 제목에 붙는다(feedback-relay · glitchtip-triage …).
#   --ok      본 명령의 정상 종료 코드(기본 0,1). 이 안의 코드는 그대로 돌려주고 알리지 않는다 —
#             precheck 의 「있음(0)」「없음(1)」이다. 그 밖의 코드(127·2·3…)는 알리고 그 코드로 끝난다.
#
# 왜: Orca 는 precheck 가 0 이 아니면 어떤 코드든 `skipped_precheck` 로 넘긴다. 체크아웃이 묵어 스크립트가 없어도
# (127) 운영에 못 닿아도(2) 「제보 없음」(1)과 똑같이 조용했다. 또 이 체크아웃을 따라잡는 장치가 없어 26커밋 묵은
# 코드로 돌았다(#1252).
#
# 따라잡기: 체크아웃이 main 에 있고, 추적 파일이 깨끗하고, origin/main 보다 앞서지 않을 때만 `merge --ff-only`.
# 아니면 건드리지 않고 알린다 — 이 체크아웃에서 다른 세션이 main 에 커밋하기도 한다. 그 커밋을 버리지 않는다.
# (따라잡기에 실패하면 본 명령을 돌리지 않는다. 묵은 코드로 도는 것이 조용한 고장이다.)
#
# 잠금(#1280): 같은 저장소를 매분 자동화 여럿이 따라잡고 조율자·작업자도 fetch 한다. 같은 순간 fetch 하면 ref 갱신이
# 경합해 「incorrect old value provided」로 진다. 따라잡기 전체(fetch + ff-only)를 `<git-common-dir>/codemit-fetch.lock`
# 안에서 돈다 — scripts/git-fetch-locked.sh 와 같은 파일. 못 잡으면 재시도 없이 「잠금 대기 초과」로 실패한다.
#
# 알림: 같은 원인(sync·rc<코드>)은 처음 한 번, 이어지면 1시간마다 한 번. 정상으로 돌아오면 한 번.
# 상태는 `~/.cache/codemit-automation/<이름>.state` 한 파일(`원인 마지막_알림_epoch`).
# 받는 곳은 scripts/notify-ops.sh 의 설정(환경변수·설정 파일)을 따른다.
set -uo pipefail

REPO="${CODEMIT_AUTOMATION_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${CODEMIT_AUTOMATION_STATE_DIR:-$HOME/.cache/codemit-automation}"
REMOTE="${CODEMIT_AUTOMATION_REMOTE:-origin}"
BRANCH="${CODEMIT_AUTOMATION_BRANCH:-main}"
REPEAT_SECS="${CODEMIT_AUTOMATION_REPEAT_SECS:-3600}"
LOCK_WAIT="${CODEMIT_AUTOMATION_LOCK_WAIT:-60}"
NOTIFY_OPS="${CODEMIT_NOTIFY_OPS:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/notify-ops.sh}"

# 스크립트 자신이 따라잡기로 바뀌어도 읽던 자리가 흐트러지지 않게 전부 함수 안에서 돌고 끝에서 빠진다.
usage() { sed -n '2,10p' "$0" >&2; exit 2; }

notify() { # notify <제목> <본문> — 보냈으면 0
  local bodyf rc=0
  bodyf="$(mktemp)"
  printf '%s\n' "$2" > "$bodyf"
  bash "$NOTIFY_OPS" "$1" "$bodyf" >/dev/null 2>&1 || rc=$?
  rm -f "$bodyf"
  return "$rc"
}

# problem <원인> <한 줄 설명> <자세히> — 같은 원인이면 REPEAT_SECS 안에는 다시 보내지 않는다.
problem() {
  local cause="$1" summary="$2" detail="$3" now last="" prev=""
  now="$(date +%s)"
  if [ -f "$STATE_FILE" ]; then read -r prev last < "$STATE_FILE" || true; fi
  if [ "$prev" = "$cause" ] && [ -n "$last" ] && [ $((now - last)) -lt "$REPEAT_SECS" ]; then
    return 0
  fi
  if notify "[codemit] 자동화 실패 $NAME — $summary" "$summary
$detail
(같은 원인은 $((REPEAT_SECS / 60))분마다 한 번, 회복하면 한 번 알린다)"; then
    mkdir -p "$STATE_DIR" && printf '%s %s\n' "$cause" "$now" > "$STATE_FILE"
  else
    echo "운영 담당에게 알리지 못했다: $summary" >&2
  fi
}

recovered() {
  [ -f "$STATE_FILE" ] || return 0
  if notify "[codemit] 자동화 회복 $NAME" "$NAME 이 다시 정상으로 돈다."; then
    : > "$STATE_FILE" && rm -f "$STATE_FILE"
  fi
}

# 따라잡기 — 성공이면 0, 실패면 까닭 한 줄을 표준출력에 내고 1.
catch_up() {
  cd "$REPO" 2>/dev/null || { echo "체크아웃을 찾지 못했다: $REPO"; return 1; }
  local cur err common
  command -v flock >/dev/null || { echo "flock 이 없다"; return 1; }
  common="$(git rev-parse --path-format=absolute --git-common-dir)" || { echo "git 저장소가 아니다: $REPO"; return 1; }
  exec 9>"$common/codemit-fetch.lock"  # 서브셸이 끝나면 잠금도 풀린다.
  flock -w "$LOCK_WAIT" 9 || { echo "잠금 대기 초과: ${LOCK_WAIT}초 안에 $common/codemit-fetch.lock 을 못 잡았다"; return 1; }
  cur="$(git symbolic-ref --short -q HEAD || true)"
  [ "$cur" = "$BRANCH" ] || { echo "체크아웃이 $BRANCH 에 있지 않다(${cur:-분리된 HEAD})"; return 1; }
  err="$(git fetch -q "$REMOTE" "$BRANCH" 2>&1)" || { echo "git fetch 실패: $(printf '%s' "$err" | tail -n 3)"; return 1; }
  git rev-parse -q --verify "$REMOTE/$BRANCH" >/dev/null || { echo "$REMOTE/$BRANCH 를 찾지 못했다"; return 1; }
  if git merge-base --is-ancestor "$REMOTE/$BRANCH" HEAD; then
    # origin/main 이 HEAD 의 조상이다 — 같거나 앞서 있다.
    if [ "$(git rev-parse HEAD)" != "$(git rev-parse "$REMOTE/$BRANCH")" ]; then
      echo "체크아웃이 $REMOTE/$BRANCH 보다 앞서 있다(푸시되지 않은 커밋)"; return 1
    fi
    return 0
  fi
  git merge-base --is-ancestor HEAD "$REMOTE/$BRANCH" || { echo "체크아웃이 $REMOTE/$BRANCH 와 갈라졌다"; return 1; }
  [ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "체크아웃에 커밋하지 않은 변경이 있어 따라잡지 않았다"; return 1; }
  err="$(git merge -q --ff-only "$REMOTE/$BRANCH" 2>&1)" || { echo "merge --ff-only 실패: $(printf '%s' "$err" | tail -n 3)"; return 1; }
}

main() {
  [ "$#" -ge 3 ] || usage
  NAME="$1"; shift
  [[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || usage
  STATE_FILE="$STATE_DIR/$NAME.state"
  local ok="0,1"
  if [ "${1:-}" = "--ok" ]; then ok="${2:-}"; shift 2; fi
  [ "${1:-}" = "--" ] || usage
  shift
  [ "$#" -gt 0 ] || usage

  local reason
  if ! reason="$(catch_up)"; then
    echo "$reason" >&2
    problem sync "체크아웃을 최신 main 으로 따라잡지 못했다" "$reason
체크아웃: $REPO"
    return 70
  fi

  cd "$REPO"  # catch_up 은 서브셸에서 돌았다 — 본 명령은 체크아웃에서 돈다.
  local errfile rc=0
  errfile="$(mktemp)"
  "$@" 2>"$errfile" || rc=$?
  cat "$errfile" >&2
  if [[ ",$ok," == *",$rc,"* ]]; then
    recovered
  else
    problem "rc$rc" "명령이 종료 코드 $rc 로 끝났다" "명령: $*
종료 코드: $rc
표준오류 끝: $(tail -n 5 "$errfile")"
  fi
  rm -f "$errfile"
  return "$rc"
}

{ main "$@"; exit $?; }
