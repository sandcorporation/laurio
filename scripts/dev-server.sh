#!/usr/bin/env bash
# 워크트리 코드를 브라우저·e2e 로 검증할 임시 앱/백엔드 서버를 띄우고 **확실히 걷는다**
# (2026-09-20).
#
# **왜 이게 필요한가.** 예전 처방은 `pnpm exec next dev -p 53100 &` 로 띄우고 `kill %1`
# 로 죽이는 것이었다. 사람이 한 셸에서 이어 칠 때는 맞지만, **에이전트는 Bash 호출마다
# 새 셸이라 `kill %1` 이 아무것도 죽이지 않는다** — 잡 테이블이 그 셸과 함께 사라진다.
# 즉 지켜질 수 없는 규칙이었고, 실제로 2026-09-20 에 병렬 체인 다섯이 남긴 호스트
# `next dev` **14개가 15.0 GiB** 를 먹어 머신이 스왑까지 말라 SSH 가 막혔다
# (`CLAUDE.local.md` 의 「사용자 슬라이스에 메모리 한도가 걸려 있다」).
#
# 그래서 잡 제어를 쓰지 않는다. **PID 파일**이 워크트리별로 남고, 어느 셸에서든
# `stop`·`stop-all`·`reap` 으로 걷을 수 있다.
#
#   scripts/dev-server.sh start front            # 이 워크트리의 공개 앱을 띄운다
#   scripts/dev-server.sh start classroom
#   scripts/dev-server.sh start --built classroom # next build 뒤 next start — RSS 가 dev 의 약 1/6(아래)
#   scripts/dev-server.sh start backend
#   scripts/dev-server.sh list                   # 이 머신에 뜬 것 전부 (어느 워크트리인지까지)
#   scripts/dev-server.sh stop-all               # 이 워크트리 것 전부
#   scripts/dev-server.sh reap                   # 고아를 걷는다 (워크트리가 사라진 것 등)
#   scripts/dev-server.sh check front            # 띄우지 않고 메모리 여유만 본다 (거절이면 종료코드 1)
#
# `start` 는 띄우기 전에 **메모리 묶음의 여유를 본다**(#976). 이 머신의 모든 세션이
# 한도 하나(`user-1000.slice` 의 memory.high)를 나눠 쓰는데, 묶음을 넘기면 커널이
# 파일 캐시를 쫓아내고 다시 읽느라 머신이 80분 멈춘다(2026-11-18, next dev 다섯).
# 거절되면 무엇을 내리면 되는지 찍는다. `CODEMIT_DEV_SERVER_FORCE=1` 은 쓰지 않는다.
#
# `start` 는 **포트를 스스로 고른다** — `docker/dev-env.sh` 가 체크아웃 경로에서
# 파생하는 값에 +10 을 더해, compose 스택이 쓰는 포트와 부딪히지 않으면서도 워크트리
# 둘이 서로를 밟지 않는다.

set -euo pipefail

# CODEMIT_DEV_SERVER_ROOT: 이 스크립트를 다른 워크트리에 대해 돌린다(전후 촬영의 before 는 옛 스크립트를 갖고 있다).
here="${CODEMIT_DEV_SERVER_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
run_dir="${CODEMIT_DEV_SERVER_DIR:-$HOME/.codemit/dev-servers}"
mkdir -p "$run_dir"

# 워크트리마다 다른 이름표. 경로를 그대로 쓰면 파일명이 지저분해져 해시를 붙인다.
tag="$(basename "$here")-$(printf '%s' "$here" | cksum | cut -d' ' -f1)"

_derived_port() {
  # dev-env.sh 가 이 체크아웃에 준 포트에 +10. 그 스크립트는 자기 위치를 기준으로
  # 삼으므로 여기서 부르면 이 워크트리의 값이 나온다.
  local var="$1" base
  base="$(cd "$here" && sh docker/dev-env.sh 2>/dev/null | sed -n "s/^export $var=//p" | head -1)"
  [ -n "$base" ] || return 1
  echo $((base + 10))
}

_stack_port() {
  # 같은 스크립트가 주는 **그 체크아웃의 compose 스택 포트**(+10 하지 않는다).
  # `_derived_port` 와 달리 컨테이너가 실제로 듣고 있는 번호다.
  local var="$1" value
  value="$(cd "$here" && sh docker/dev-env.sh 2>/dev/null | sed -n "s/^export $var=//p" | head -1)"
  [ -n "$value" ] || return 1
  echo "$value"
}

_pidfile() { echo "$run_dir/$tag.$1.pid"; }

_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# ---- 메모리 묶음 여유 검사 (#976) -------------------------------------------------
# 값을 하드코딩하지 않는다 — 한도는 이 프로세스의 cgroup 에서 위로 올라가며 찾는다.
cg_root="${CODEMIT_CGROUP_ROOT:-/sys/fs/cgroup}"
proc_cgroup="${CODEMIT_PROC_CGROUP:-/proc/self/cgroup}"
# 거절 문턱: 한도(memory.high, 없으면 memory.max)의 85%. 한도에 닿기 전에 커널이
# 회수 압력을 넣기 시작하므로 여유를 두고, 이미 80% 근처에서 돌던 묶음이 느려지는 것을 막는다.
mem_ratio_pct="${CODEMIT_DEV_SERVER_MEM_PCT:-85}"

# 앱 하나의 예상 크기(MB). 2026-11-18 실측: next dev 1.29~2.12GB(앱·작업 따라), 평균
# 약 1.5GB 에 라우트가 컴파일되며 자라므로 2GB 로 잡는다. runserver(Django)는 약 0.2GB.
_expected_mb() {
  case "$1" in
    backend) echo 200 ;;
    *)       echo 2048 ;;
  esac
}

# 한도가 숫자인 가장 가까운 조상 cgroup 디렉터리를 출력한다. 없으면 실패.
_limit_cgroup() {
  local rel dir v
  [ -r "$proc_cgroup" ] || return 1
  rel="$(sed -n 's/^0:://p' "$proc_cgroup" | head -1)"
  [ -n "$rel" ] || return 1
  dir="$cg_root$rel"
  while [ -d "$dir" ]; do
    for v in memory.high memory.max; do
      if [ -r "$dir/$v" ] && [[ "$(cat "$dir/$v")" =~ ^[0-9]+$ ]]; then
        echo "$dir"; return 0
      fi
    done
    [ "$dir" = "$cg_root" ] && break
    dir="${dir%/*}"
    [ -n "$dir" ] || dir="$cg_root"
    case "$dir" in "$cg_root"*) ;; *) break ;; esac
  done
  return 1
}

_limit_bytes() {  # $1 = cgroup 디렉터리 — memory.high 가 숫자면 그것, 아니면 memory.max
  local h
  h="$(cat "$1/memory.high" 2>/dev/null || true)"
  if [[ "$h" =~ ^[0-9]+$ ]]; then echo "$h"; else cat "$1/memory.max"; fi
}

# 나무 전체의 RSS(KB). next 는 자식 `next-server` 가 메모리를 쥔다.
_tree_rss_kb() {
  local pid="$1" sum child own
  own="$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  sum="${own:-0}"
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do sum=$((sum + $(_tree_rss_kb "$child"))); done
  echo "$sum"
}

_mem_gate() {  # $1 = 띄울 대상. 거절이면 1.
  local what="$1" dir cur lim need thr
  if [ "${CODEMIT_DEV_SERVER_FORCE:-}" = 1 ]; then
    echo "메모리 여유 검사를 건너뛴다(CODEMIT_DEV_SERVER_FORCE=1) — 쓰지 말 것." >&2; return 0
  fi
  if ! dir="$(_limit_cgroup)"; then
    echo "메모리 여유 검사 없음: cgroup v2 한도를 찾지 못했다(한도가 없는 머신·CI)." >&2; return 0
  fi
  cur="$(cat "$dir/memory.current" 2>/dev/null || true)"
  [[ "$cur" =~ ^[0-9]+$ ]] || { echo "메모리 여유 검사 없음: $dir/memory.current 를 읽지 못했다." >&2; return 0; }
  lim="$(_limit_bytes "$dir")"
  need=$(( $(_expected_mb "$what") * 1048576 ))
  thr=$(( lim / 100 * mem_ratio_pct ))
  if [ $((cur + need)) -le "$thr" ]; then return 0; fi
  {
    echo "띄우지 않았다: $what — 메모리 묶음에 여유가 없다."
    echo "  묶음 ${dir#"$cg_root"}: 지금 $((cur / 1048576))MB + $what 예상 $((need / 1048576))MB > 한도 $((lim / 1048576))MB 의 ${mem_ratio_pct}% ($((thr / 1048576))MB)"
    echo "  넘기면 커널이 파일 캐시를 쫓아내며 머신이 멎는다(2026-11-18). 아래에서 내릴 것을 고른다:"
    cmd_list | sed 's/^/  /'
    echo "  내리는 법: 그 워크트리에서 scripts/dev-server.sh stop-all (또는 stop <대상>)"
    echo "  그래도 띄워야 하면 CODEMIT_DEV_SERVER_FORCE=1 — 쓰지 말 것."
  } >&2
  return 1
}

cmd_check() {
  local what="${1:?front|operator|classroom|backend 중 하나}"
  _mem_gate "$what" && echo "여유 있음: $what"
}

cmd_start() {
  local built=0
  if [ "${1:-}" = "--built" ]; then built=1; shift; fi
  local what="${1:?front|operator|classroom|backend 중 하나}"
  local pidfile port dir log
  pidfile="$(_pidfile "$what")"

  if [ -f "$pidfile" ] && _alive "$(cat "$pidfile")"; then
    echo "이미 떠 있다: $what (pid $(cat "$pidfile"), 포트 $(cat "$run_dir/$tag.$what.port" 2>/dev/null))"
    return 0
  fi

  case "$what" in
    front)     dir="$here/frontend";  port="$(_derived_port CODEMIT_WEB_PORT)" ;;
    operator)  dir="$here/operator";  port="$(_derived_port CODEMIT_OPERATOR_WEB_PORT)" ;;
    classroom) dir="$here/classroom"; port="$(_derived_port CODEMIT_CLASSROOM_WEB_PORT)" ;;
    backend)   dir="$here/backend";   port="$(_derived_port CODEMIT_API_PORT)" ;;
    *) echo "모르는 대상: $what" >&2; return 2 ;;
  esac

  _mem_gate "$what" || return 1

  log="$run_dir/$tag.$what.log"
  if [ "$what" = "backend" ]; then
    # dev compose 의 backend 가 MinIO 를 물고 뜨므로 같은 모양으로 띄운다 — 빼면
    # 업로드 경로만 갈린다(`CLAUDE.md` 의 같은 주의).
    # **DB 포트를 5432x 로 고정해 두지 않는다**(2026-09-21). 예전 기본값이
    # `55432` 였는데 그건 **주 워크트리의 공유 dev DB** 다 — 격리된 워크트리에서
    # 이 스크립트로 백엔드를 띄운 에이전트가 자기 것인 줄 알고 사람의 dev DB 에
    # 테스트 Contest 와 계정을 만들었다(#473 작업 중, raw SQL 로 되돌렸다).
    # 이제 `docker/dev-env.sh` 가 **이 체크아웃에** 준 값을 쓴다 — 주 워크트리에서는
    # 그 값이 그대로 55432 라 동작이 같고, 워크트리에서는 자기 스택을 가리킨다.
    local db_port
    db_port="${CODEMIT_DB_PORT:-$(_stack_port CODEMIT_DB_PORT || true)}"
    if [ -z "$db_port" ]; then
      echo "CODEMIT_DB_PORT 를 정할 수 없다 — docker/dev-env.sh 가 값을 주지 않았다." >&2
      return 1
    fi
    ( cd "$dir" && CODEMIT_DB_PORT="$db_port" STORAGE_BACKEND=s3 \
        nohup uv run python manage.py runserver "0.0.0.0:$port" >"$log" 2>&1 & echo $! >"$pidfile" )
  elif [ "$built" = 1 ]; then
    # `next build` 는 끝나는 순간 프로세스가 사라진다 — 최고 RSS 는 dev 와 비슷(classroom 실측
    # 1.9GB)해도 잠깐이고, 뜬 뒤에는 `next start` 약 0.3GB 만 남는다(dev 는 2.0GB 로 붙어 있다).
    # 그래서 스크린샷 용도는 이쪽이 낫다. 빌드는 앞에서 기다리므로 next 가 둘이 되지 않는다.
    echo "빌드 중: $what (끝나야 뜬다)"
    if ! ( cd "$dir" && pnpm run build >"$log" 2>&1 ); then
      echo "빌드하지 못했다: $what — 로그 끝부분:" >&2; tail -12 "$log" | sed 's/^/    /' >&2; return 1
    fi
    ( cd "$dir" && CODEMIT_API_BASE_URL="${CODEMIT_API_BASE_URL:-http://127.0.0.1:$(_derived_port CODEMIT_API_PORT)}" \
        nohup pnpm exec next start -p "$port" >>"$log" 2>&1 & echo $! >"$pidfile" )
  else
    # 같은 이유로 백엔드 주소도 **이 스크립트가 띄우는 백엔드**를 가리킨다 —
    # 예전 기본값 `58000` 은 주 워크트리의 컨테이너였다.
    ( cd "$dir" && CODEMIT_API_BASE_URL="${CODEMIT_API_BASE_URL:-http://127.0.0.1:$(_derived_port CODEMIT_API_PORT)}" \
        nohup pnpm exec next dev -p "$port" >"$log" 2>&1 & echo $! >"$pidfile" )
  fi
  echo "$port" >"$run_dir/$tag.$what.port"
  echo "$here" >"$run_dir/$tag.worktree"

  # **떴는지 확인하고 아니면 시끄럽게 실패한다.** 조용히 죽으면 그 뒤의 e2e·브라우저
  # 확인이 「연결 거부」로만 보여 원인이 코드인지 서버인지 갈리지 않는다.
  sleep 3
  if ! _alive "$(cat "$pidfile")"; then
    echo "띄우지 못했다: $what — 로그 끝부분:" >&2
    tail -12 "$log" | sed 's/^/    /' >&2
    if grep -q "EACCES" "$log" 2>/dev/null && [ -d "$dir/.next" ] && [ ! -w "$dir/.next" ]; then
      echo "" >&2
      echo "    → .next 가 내 것이 아니다($(stat -c %U "$dir/.next") 소유)." >&2
      echo "      dev compose 컨테이너가 이 체크아웃에 root 로 쓴 흔적이다 —" >&2
      echo "      **주 워크트리는 컨테이너가 서빙하므로 호스트에서 띄울 대상이 아니다.**" >&2
      echo "      이 도구는 컨테이너가 마운트하지 않는 워크트리에서 쓴다." >&2
    fi
    rm -f "$pidfile" "$run_dir/$tag.$what.port"
    return 1
  fi

  echo "띄웠다: $what  포트 $port  pid $(cat "$pidfile")  로그 $log"
  echo "  baseURL: http://127.0.0.1:$port"
  echo "  끝나면: $0 stop-all"
}

# **프로세스 하나가 아니라 나무 전체를 죽인다.** `pnpm exec next dev` 는 자식으로
# 진짜 `next-server` 를 낳으므로, 부모만 죽이면 메모리를 쥔 쪽이 그대로 남는다 —
# 사고 당시 15 GiB 를 쥐고 있던 것이 바로 그 자식들이다.
_kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do _kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

cmd_stop() {
  local what="$1" pidfile pid
  pidfile="$(_pidfile "$what")"
  [ -f "$pidfile" ] || { echo "  $what: 기록 없음"; return 0; }
  pid="$(cat "$pidfile")"
  if _alive "$pid"; then
    _kill_tree "$pid"
    sleep 1
    _alive "$pid" && { _kill_tree "$pid"; kill -9 "$pid" 2>/dev/null || true; }
    echo "  $what: 걷었다 (pid $pid)"
  else
    echo "  $what: 이미 없다"
  fi
  rm -f "$pidfile" "$run_dir/$tag.$what.port"
}

# 이 워크트리에서 띄운 브라우저(Playwright 크롬)만 걷는다 — 촬영 스크립트가 남긴 pid 파일의
# 나무, 그리고 **cwd 가 이 워크트리 안인** chrom* 프로세스. 다른 세션의 크롬은 cwd 가
# 다르므로 건드리지 않는다. `pkill -f` 를 쓰지 않는다.
_sweep_browsers() {
  local f pid p cwd comm n=0
  for f in "$run_dir/$tag."*.shoot; do
    [ -e "$f" ] || continue
    pid="$(cat "$f" 2>/dev/null || true)"
    _alive "$pid" && { _kill_tree "$pid"; n=$((n+1)); }
    rm -f "$f"
  done
  for p in /proc/[0-9]*; do
    pid="${p#/proc/}"
    comm="$(cat "$p/comm" 2>/dev/null || true)"
    case "$comm" in chrom*|headless_shell*) ;; *) continue ;; esac
    cwd="$(readlink "$p/cwd" 2>/dev/null || true)"
    case "$cwd" in "$here"|"$here"/*) kill "$pid" 2>/dev/null && n=$((n+1)) || true ;; esac
  done
  [ "$n" = 0 ] || echo "  브라우저: 걷었다 ($n개)"
}

cmd_stop_all() {
  local f what found=0
  _sweep_browsers
  for f in "$run_dir/$tag."*.pid; do
    [ -e "$f" ] || continue
    what="$(basename "$f" .pid)"; what="${what##*.}"
    cmd_stop "$what"; found=1
  done
  [ "$found" = 1 ] || echo "  이 워크트리에서 띄운 것이 없다"
  rm -f "$run_dir/$tag.worktree"
}

cmd_list() {
  local f t pid wt port state rss n=0
  for f in "$run_dir"/*.pid; do
    [ -e "$f" ] || continue
    t="$(basename "$f" .pid)"; pid="$(cat "$f" 2>/dev/null || true)"
    wt="$(cat "$run_dir/${t%.*}.worktree" 2>/dev/null || echo '?')"
    port="$(cat "$run_dir/$t.port" 2>/dev/null || echo '?')"
    rss=""
    if _alive "$pid"; then state="살아있음"; rss="$(( $(_tree_rss_kb "$pid") / 1024 ))MB"; else state="죽었음(기록만 남음)"; fi
    printf "  %-34s 포트=%-6s pid=%-8s RSS=%-8s %-20s %s\n" "${t##*.}" "$port" "$pid" "$rss" "$state" "$wt"
    n=$((n+1))
  done
  [ "$n" -gt 0 ] || echo "  기록된 서버가 없다"
  # 기록 밖에서 도는 것도 보여준다 — 이 도구를 안 쓰고 띄운 것이 있으면 그게 다음 사고다.
  local stray
  stray="$(pgrep -fa "next-server|next dev" 2>/dev/null | grep -v "$0" || true)"
  if [ -n "$stray" ]; then
    echo "  --- 기록 밖에서 도는 next (이 도구로 띄우지 않은 것):"
    echo "$stray" | sed 's/^/      /'
  fi
}

# 고아를 걷는다. **판정은 보수적이다** — 「워크트리가 사라졌다」와 「프로세스가 이미
# 죽었다」만 본다. 나이로 자르지 않는 이유는 긴 체인이 정당하게 오래 띄워 두기
# 때문이다(그 경우를 잘못 죽이면 진단이 통째로 어긋난다).
cmd_reap() {
  local f t wt pid swept=0
  for f in "$run_dir"/*.pid; do
    [ -e "$f" ] || continue
    t="$(basename "$f" .pid)"
    wt="$(cat "$run_dir/${t%.*}.worktree" 2>/dev/null || true)"
    pid="$(cat "$f" 2>/dev/null || true)"
    if ! _alive "$pid"; then rm -f "$f" "$run_dir/$t.port"; continue; fi
    if [ -n "$wt" ] && [ ! -d "$wt" ]; then
      echo "  워크트리가 사라졌다($wt) → ${t##*.} (pid $pid) 걷는다"
      _kill_tree "$pid"; rm -f "$f" "$run_dir/$t.port"; swept=$((swept+1))
    fi
  done
  echo "걷은 서버 $swept개"
  # compose 스택도 같은 판정으로 걷는다(#1186) — 주인 워크트리가 사라진 codemit-dev* 의 컨테이너만 내린다.
  # 볼륨은 남긴다. docker 가 없거나 안 닿으면 조용히 넘어간다.
  command -v docker >/dev/null 2>&1 || return 0
  . "$here/docker/dev-stack-orphans.sh"
  local project stacks=0
  for project in $(docker ps -a --filter "label=com.docker.compose.project" \
      --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u | grep -E '^codemit-dev(-[0-9])?$' || true); do
    if dev_stack_is_orphan "$project"; then
      echo "  주인 워크트리가 사라졌다($(dev_stack_owners "$project" | tr '\n' ' ')) → 스택 $project 내린다(볼륨은 남김)"
      dev_stack_down_orphan "$project"; stacks=$((stacks+1))
    fi
  done
  echo "내린 스택 $stacks개"
  # -e2e 스택은 주인 디렉터리가 있어도 걷는다(#1192) — 띄운 test.sh 가 없으면 고아다. mac 은 타이머가 없어
  # `scripts/test.sh e2e` 시작 때 같은 걷기를 한다.
  e2e_stack_reap
  echo "내린 e2e 스택 ${E2E_REAPED:-0}개"
}

case "${1:-}" in
  start)    shift; cmd_start "$@" ;;
  stop)     shift; cmd_stop "${1:?대상}" ;;
  stop-all) cmd_stop_all ;;
  list)     cmd_list ;;
  port)     cat "$run_dir/$tag.${2:?대상}.port" ;;
  browser-pidfile) echo "$run_dir/$tag.$$.shoot" ;;
  check)    shift; cmd_check "$@" ;;
  reap)     cmd_reap ;;
  *) sed -n '1,30p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
