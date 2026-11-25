# dev 스택 칸 예약(#1411) — dev-env.sh 와 worktree-rm.sh 가 같이 쓴다. `.` 로 읽어 쓴다(`sh`·bash 3.2).
#
# 컨테이너 라벨은 컨테이너가 있을 때만 주인을 말한다. 그래서 칸마다 파일 하나(`$DEV_SLOTS_DIR/<칸>`, 내용은 체크아웃
# 경로 한 줄)를 저장소 밖에 둔다. 적힌 경로가 사라진 예약은 고아다. 읽고 쓰는 쪽은 잠금 하나 안에서 한다.

DEV_SLOTS_DIR="${XDG_STATE_HOME:-${HOME:-}/.local/state}/codemit/dev-slots"
DEV_SLOTS_LOCK_TIMEOUT="${CODEMIT_DEV_SLOT_LOCK_TIMEOUT:-60}"
DEV_SLOTS_LOCKED=

# 칸 $1 에 적힌 경로. 예약이 없으면 빈 줄.
dev_slot_owner() {
  head -n 1 "$DEV_SLOTS_DIR/$1" 2>/dev/null || true
}

# 체크아웃 $1 의 예약을 푼다. $2 를 주면 그 칸은 남긴다.
dev_slot_release_owned_by() {
  for _file in "$DEV_SLOTS_DIR"/[0-9]; do
    [ -f "$_file" ] || continue
    [ "$_file" != "$DEV_SLOTS_DIR/${2:-}" ] || continue
    if [ "$(head -n 1 "$_file")" = "$1" ]; then rm -f "$_file"; fi
  done
}

# 칸 $1 을 체크아웃 $2 몫으로 적는다. 한 체크아웃은 한 칸만 쥔다 — 전에 쥔 칸은 푼다.
dev_slot_reserve() {
  printf '%s\n' "$2" > "$DEV_SLOTS_DIR/.tmp.$$" &&
    mv -f "$DEV_SLOTS_DIR/.tmp.$$" "$DEV_SLOTS_DIR/$1" &&
    dev_slot_release_owned_by "$2" "$1"
}

# 파일 $1 을 **없을 때만** 만들고 내 pid 를 적는다. 셸의 noclobber(`O_EXCL`)로 만든다 — `mkdir` 명령에 기대지 않는다.
# uutils coreutils 의 mkdir 은 동시에 부르면 둘 다 성공할 때가 있다(2026-11-25 실측, 1000번 중 13번).
_dev_slots_create_pid_file() {
  (set -C; echo "$$" > "$1") 2>/dev/null
}

# 쥔 프로세스가 죽은 잠금을 치운다. 치우는 쪽도 하나뿐이어야 방금 새로 잡힌 잠금을 지우지 않는다.
_dev_slots_reclaim_dead_lock() {
  _dev_slots_create_pid_file "$DEV_SLOTS_DIR/.lock.reclaim" || return 0
  _holder=$(cat "$DEV_SLOTS_DIR/.lock.pid" 2>/dev/null || true)
  # 죽은 것을 본 **뒤에** 다시 읽는다 — 그 사이 정상으로 놓였다가 남이 새로 잡았으면 pid 가 다르다.
  if [ -n "$_holder" ] && ! kill -0 "$_holder" 2>/dev/null &&
    [ "$(cat "$DEV_SLOTS_DIR/.lock.pid" 2>/dev/null || true)" = "$_holder" ]; then
    rm -f "$DEV_SLOTS_DIR/.lock.pid"
  fi
  rm -f "$DEV_SLOTS_DIR/.lock.reclaim"
}

# 잠금을 잡는다. 0 = 잡음, 1 = 시간 초과, 2 = 예약 폴더에 쓸 수 없다.
# Linux 는 flock(fd 9), flock 이 없는 macOS 는 pid 파일.
dev_slots_lock() {
  mkdir -p "$DEV_SLOTS_DIR" 2>/dev/null && [ -w "$DEV_SLOTS_DIR" ] || return 2
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$DEV_SLOTS_DIR/.lock"
    if ! flock -w "$DEV_SLOTS_LOCK_TIMEOUT" 9; then exec 9>&-; return 1; fi
    DEV_SLOTS_LOCKED=flock
    return 0
  fi
  _waited=0
  while ! _dev_slots_create_pid_file "$DEV_SLOTS_DIR/.lock.pid"; do
    _dev_slots_reclaim_dead_lock
    [ "$_waited" -lt "$DEV_SLOTS_LOCK_TIMEOUT" ] || return 1
    sleep 1
    _waited=$((_waited + 1))
  done
  DEV_SLOTS_LOCKED=pidfile
}

# 내가 잡은 잠금만 놓는다. 잡지 않았으면 아무것도 하지 않는다(EXIT trap 에서 불러도 된다).
dev_slots_unlock() {
  case "$DEV_SLOTS_LOCKED" in
    flock) exec 9>&- ;;
    pidfile) rm -f "$DEV_SLOTS_DIR/.lock.pid" ;;
  esac
  DEV_SLOTS_LOCKED=
}
