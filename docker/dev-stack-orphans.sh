# dev compose 스택의 「고아」 판정 — dev-env.sh 와 dev-server.sh reap 이 같이 쓴다(#1186). `.` 로 읽어 쓴다.
#
# 스택의 주인은 컨테이너 라벨 `com.docker.compose.project.working_dir`(꺼진 것 포함)다. 그 디렉터리가
# **이미 사라졌으면** 남의 스택이 아니라 고아다 — 워크트리를 지울 때 스택을 안 내려 오프셋이 영영
# 막히던 것을 이 판정이 푼다. 디렉터리가 있으면 주인이 살아 있으니 건드리지 않는다.

# 프로젝트의 주인 디렉터리들(중복 없이, 줄마다 하나).
dev_stack_owners() {
  docker ps -a --filter "label=com.docker.compose.project=$1" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null | sort -u || true
}

# 고아 스택이면 0, 아니면 1. 주인 디렉터리가 하나라도 남아 있거나 주인을 알 수 없으면 고아가 아니다.
dev_stack_is_orphan() {
  _owners=$(dev_stack_owners "$1")
  [ -n "$_owners" ] || return 1
  for _o in $_owners; do
    [ -d "$_o" ] && return 1
  done
  return 0
}

# 고아 스택의 컨테이너를 내린다. **볼륨은 지우지 않는다**(`-v`·`--volumes` 를 쓰지 않는다).
dev_stack_down_orphan() {
  docker compose -p "$1" down --remove-orphans >/dev/null 2>&1 || docker ps -a -q --filter "label=com.docker.compose.project=$1" | xargs -r docker rm -f >/dev/null 2>&1 || true
}

# ── e2e 스택(`<dev 프로젝트>-e2e`, #1192) ────────────────────────────────────────────────────
# `-e2e` 스택은 늘 일회용이다 — `scripts/test.sh e2e` 가 띄우고 EXIT trap 으로 내린다. 그런데 셸이 SIGKILL 로
# 죽으면(세션 종료·배경 셸 강제 종료·시간 초과) trap 이 안 돌아 스택이 남고, 위 판정은 주인 디렉터리가 있으면
# 건드리지 않는다. 그래서 띄우는 쪽이 표식을 남긴다: `$E2E_STATE_DIR/<프로젝트>.owner`(= test.sh 의 pid),
# `CODEMIT_E2E_KEEP` 이면 `.keep`(= 남긴 시각, 초). 판정:
#   · .keep 이 있으면 E2E_KEEP_MAX_SECONDS(기본 12시간)까지만 남긴다.
#   · .owner 의 pid 가 살아 있고 test.sh 이면 시험 중이다.
#   · .owner 가 없으면(표식 없는 옛 test.sh 가 띄웠다) 컨테이너가 한 시간 넘게 떠 있을 때만 고아다.
E2E_STATE_DIR="${CODEMIT_DEV_SERVER_DIR:-$HOME/.codemit/dev-servers}"
E2E_KEEP_MAX_SECONDS="${CODEMIT_E2E_KEEP_MAX_SECONDS:-43200}"

# test.sh 가 띄우기 직전에 부른다. $1 = 프로젝트, $2 = test.sh 의 pid, $3 = KEEP 여부(비면 아님).
e2e_stack_mark() {
  mkdir -p "$E2E_STATE_DIR"
  echo "$2" > "$E2E_STATE_DIR/$1.owner"
  if [ -n "${3:-}" ]; then date +%s > "$E2E_STATE_DIR/$1.keep"; else rm -f "$E2E_STATE_DIR/$1.keep"; fi
}

e2e_stack_unmark() { rm -f "$E2E_STATE_DIR/$1.owner" "$E2E_STATE_DIR/$1.keep"; }

_e2e_pid_is_test_sh() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null && ps -p "$1" -o command= 2>/dev/null | grep -q 'test\.sh'
}

# 고아면 까닭을 한 줄 찍고 0, 아니면 1.
e2e_stack_is_orphan() {
  _p="$1"
  _keep=$(cat "$E2E_STATE_DIR/$_p.keep" 2>/dev/null || true)
  if [ -n "$_keep" ]; then
    [ $(( $(date +%s) - _keep )) -gt "$E2E_KEEP_MAX_SECONDS" ] && { echo "KEEP 로 남긴 지 ${E2E_KEEP_MAX_SECONDS}초를 넘었다"; return 0; }
    return 1
  fi
  _pid=$(cat "$E2E_STATE_DIR/$_p.owner" 2>/dev/null || true)
  if [ -n "$_pid" ]; then
    _e2e_pid_is_test_sh "$_pid" && return 1
    echo "띄운 test.sh(pid $_pid)가 없다"; return 0
  fi
  if docker ps -a --filter "label=com.docker.compose.project=$_p" --format '{{.RunningFor}}' 2>/dev/null | grep -Eq 'hour|day|week|month'; then
    echo "표식 없이 한 시간 넘게 떠 있다"; return 0
  fi
  return 1
}

# 모든 고아 -e2e 스택을 내린다(볼륨까지 — 일회용이다). 내린 개수를 E2E_REAPED 에 둔다.
e2e_stack_reap() {
  command -v docker >/dev/null 2>&1 || return 0
  E2E_REAPED=0
  for _p in $(docker ps -a --filter "label=com.docker.compose.project" \
      --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u | grep -E '^codemit-dev(-[0-9])?-e2e$' || true); do
    if _why=$(e2e_stack_is_orphan "$_p"); then
      echo "  e2e 스택 $_p 고아($_why) → 내린다"
      docker compose -p "$_p" down -v --remove-orphans >/dev/null 2>&1 || \
        docker ps -a -q --filter "label=com.docker.compose.project=$_p" | xargs -r docker rm -f >/dev/null 2>&1 || true
      e2e_stack_unmark "$_p"; E2E_REAPED=$((E2E_REAPED + 1))
    fi
  done
}

# 워크트리 $1 을 주인으로 둔 모든 codemit-dev* 스택을 내린다 — `-e2e` 만 볼륨까지(일회용), dev 스택 볼륨은 남긴다.
dev_stack_down_owned_by() {
  command -v docker >/dev/null 2>&1 || return 0
  _wt=$(cd "$1" 2>/dev/null && pwd -P || echo "$1")
  for _p in $(docker ps -a --filter "label=com.docker.compose.project" \
      --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u | grep -E '^codemit-dev(-[0-9])?(-e2e)?$' || true); do
    for _o in $(dev_stack_owners "$_p"); do
      # compose 의 working_dir 은 compose 파일이 있는 `<워크트리>/docker` 다 — 워크트리 밑이면 그 주인이다.
      case "$_o" in "$_wt"|"$_wt"/*|"$1"|"$1"/*) ;; *) continue ;; esac
      case "$_p" in
        *-e2e) echo "  스택 $_p 내린다(볼륨까지)"; docker compose -p "$_p" down -v --remove-orphans >/dev/null 2>&1 || true; e2e_stack_unmark "$_p" ;;
        *)     echo "  스택 $_p 내린다(볼륨은 남김)"; dev_stack_down_orphan "$_p" ;;
      esac
      break
    done
  done
}
