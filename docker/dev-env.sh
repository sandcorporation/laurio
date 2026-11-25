#!/usr/bin/env sh
# 워크트리마다 dev 스택을 통째로 가른다.
#
# 지금까지 병렬 워크트리는 **하나의 dev 스택을 공유**했다. DB·Redis·MinIO 가 하나라
# 한쪽 체인의 시드가 다른 쪽이 읽는 목록에 섞였고, 그것을 이름 접두어로 막아 왔다 —
# 그 방식은 전역 건수나 단일 행(정책·시계) 앞에서는 성립하지 않는다.
#
# 이 스크립트를 `eval` 하면 이 체크아웃 전용 포트와 compose 프로젝트 이름이 환경에
# 실린다. 그러면 `docker compose` 가 **다른 스택**을 띄우고, 컨테이너도 볼륨도 갈린다.
#
#   eval "$(sh docker/dev-env.sh)"
#   docker compose -f docker/compose.dev.yaml up -d
#
# **기본 체크아웃은 오프셋 0 이다.** CLAUDE.md 의 포트 표(55432·58000·16379·53000·
# 53001)가 그대로 살아야 하고, 이미 떠 있는 스택과 사람의 습관도 그대로여야 한다.
# 그 판정 기준은 이름이 아니라 **git 이 말하는 주 워크트리인가**이다 — 디렉터리
# 이름으로 판정하면 저장소를 다른 이름으로 클론한 사람이 조용히 오프셋을 받는다.
#
# 해시가 겹치면 두 워크트리가 같은 compose 프로젝트 이름을 받고, 그러면 나중에 뜨는 쪽의
# `up` 이 **남의 컨테이너를 다시 만든다**(#1409). 그래서 해시 칸이 다른 체크아웃 것이면
# 다음 빈 칸으로 넘긴다. 주인은 컨테이너 라벨로 본다(`dev-stack-orphans.sh`).

set -eu

# **거절은 stdout 으로도 말한다.** 이 스크립트는 `eval "$(sh docker/dev-env.sh)"` 로 불리고,
# 명령 치환 안의 종료코드는 eval 이 삼킨다 — stdout 이 빈 채 끝나면 오프셋 변수가 비어 뒤따른
# `docker compose` 가 기본(0) 스택을 다시 만든다(#1146, #1124). 그래서 거절 때는 eval 이 실행할
# 조각을 stdout 에 낸다: `docker` 를 실패하는 함수로 가려 `;` 로 이어진 compose 도 돌지 못하게
# 하고, 마지막 `false` 가 `&&` 체인과 `set -e` 를 멈춘다. 다시 eval 해 성공하면 가림이 풀린다.
refuse() {
  {
    echo "dev-env.sh: $1"
    echo "  고칠 길: 빈 오프셋을 고르거나(CODEMIT_DEV_OFFSET=<0~9>, 비우면 경로 해시), 묵은 워크트리의 스택을 정리한다(git worktree remove, docker compose -p <프로젝트> down)."
  } >&2
  printf '%s\n' \
    'docker() { echo "dev-env.sh 가 오프셋을 거절해 docker 를 돌리지 않는다 — 위 까닭을 고친 뒤 다시 eval 한다" >&2; return 1; }' \
    'false'
  exit 1
}

# **cwd 가 아니라 이 스크립트의 위치를 기준으로 삼는다.** 어디서 부르든 「이 체크아웃」이
# 답이어야 한다 — cwd 로 판정하면 다른 디렉터리에서 부른 순간 남의 스택 값을 뱉는다.
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(git -C "$script_dir" rev-parse --show-toplevel)
main_worktree=$(git -C "$script_dir" worktree list --porcelain | awk '/^worktree /{print $2; exit}')

# 어느 길로 오프셋을 받든 먼저 주인 없는 dev 스택을 내린다(#1275). 해시 길·주 워크트리 길은 주인을 보지 않아
# 고아 db 가 그대로 남아 새 작업자가 그 위에 붙었다. stdout 은 eval 이 실행하니 알림은 stderr 로만 낸다.
if command -v docker >/dev/null 2>&1; then
  . "$script_dir/dev-stack-orphans.sh"
  dev_stack_reap_orphans
fi

# 프로젝트 $1 의 주인 중 이 체크아웃($root) 밖의 첫 디렉터리. 없으면 빈 줄.
foreign_owner() {
  for _owner in $(dev_stack_owners "$1"); do
    case "$_owner" in
      "$root" | "$root"/*) ;;
      *) echo "$_owner"; return 0 ;;
    esac
  done
}

# 해시 칸 $1 부터 1~9 를 한 바퀴 돌아 offset 을 정한다(#1409). 한 칸은 dev 스택과 `-e2e` 스택을 함께 본다
# (`test.sh e2e` 는 `-e2e` 만 띄운다). 내 라벨이 붙은 칸이 있으면 그 칸(다시 불러도 같다), 없으면 비었거나
# 사라진 체크아웃의 라벨만 남은 첫 칸. 살아 있는 남의 라벨이 하나라도 있는 칸은 쓰지 않는다.
pick_hash_offset() {
  _projects=$(docker ps -a --filter "label=com.docker.compose.project" \
    --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u || true)
  _mine_slot= _free_slot= _taken= _hash_owner=
  _i=0
  while [ "$_i" -lt 9 ]; do
    _slot=$(( ($1 - 1 + _i) % 9 + 1 ))
    _i=$((_i + 1))
    _mine= _other=
    for _project in "codemit-dev-$_slot" "codemit-dev-$_slot-e2e"; do
      printf '%s\n' "$_projects" | grep -qx "$_project" || continue
      for _owner in $(dev_stack_owners "$_project"); do
        case "$_owner" in
          "$root" | "$root"/*) _mine=1 ;;
          *) if [ -d "$_owner" ]; then _other=$_owner; fi ;;
        esac
      done
    done
    if [ -n "$_other" ]; then
      _taken="$_taken $_slot($_other)"
      if [ "$_slot" -eq "$1" ]; then _hash_owner=$_other; fi
    elif [ -n "$_mine" ]; then
      _mine_slot=$_slot
      break
    elif [ -z "$_free_slot" ]; then
      _free_slot=$_slot
    fi
  done
  offset=${_mine_slot:-$_free_slot}
  [ -n "$offset" ] || refuse "오프셋 1~9 가 모두 다른 체크아웃의 스택이다:$_taken"
  if [ -n "$_hash_owner" ]; then
    echo "dev-env.sh: 해시 칸 $1 은 다른 체크아웃($_hash_owner)의 스택이라 오프셋 $offset 을 쓴다" >&2
  fi
}

if [ -n "${CODEMIT_DEV_OFFSET:-}" ]; then
  # 사람이 오프셋을 직접 고른다(#1106). 0~9 의 한 자리 숫자만 받는다.
  case "$CODEMIT_DEV_OFFSET" in
    [0-9]) offset=$CODEMIT_DEV_OFFSET ;;
    *)
      refuse "CODEMIT_DEV_OFFSET 은 0~9 여야 한다(받은 값: $CODEMIT_DEV_OFFSET)"
      ;;
  esac
  # 그 오프셋의 compose 프로젝트가 다른 체크아웃 것이면 멈춘다 — 남의 스택에 붙지 않는다.
  project=codemit-dev$( [ "$offset" -eq 0 ] || printf '%s' "-$offset" )
  if command -v docker >/dev/null 2>&1; then
    # 주인 디렉터리가 모두 사라진 스택은 고아다 — 컨테이너를 내리고(볼륨은 남긴다) 그 오프셋을 쓴다(#1186).
    if dev_stack_is_orphan "$project"; then
      echo "dev-env.sh: 오프셋 $offset($project)은 사라진 체크아웃($(echo $(dev_stack_owners "$project")))의 고아 스택이라 내렸다(볼륨은 남겼다)" >&2
      dev_stack_down_orphan "$project"
    else
      owner=$(foreign_owner "$project")
      [ -z "$owner" ] || refuse "오프셋 $offset($project)은 다른 체크아웃($owner)의 스택이다"
    fi
  fi
elif [ "$root" = "$main_worktree" ]; then
  offset=0
else
  # 0 이 아닌 1~9 로 접는다 — 0 은 주 워크트리의 몫이다.
  # **앞의 0 을 직접 뗀다.** `039` 를 그대로 넘기면 셸이 8진수로 읽어 죽고, `10#` 은
  # bash 확장이라 `sh`(dash)에서는 쓸 수 없다 — 이 스크립트는 `sh` 로 불린다.
  # macOS 에는 sha256sum 이 없다 — shasum -a 256 이 같은 값을 낸다.
  if command -v sha256sum >/dev/null 2>&1; then hash=sha256sum; else hash='shasum -a 256'; fi
  digits=$(printf '%s' "$root" | $hash | tr -dc '0-9' | cut -c1-3 | sed 's/^0*//')
  offset=$(( (${digits:-0} % 9) + 1 ))
  # docker 가 없으면 주인을 물을 곳이 없다 — 해시 칸 그대로.
  if command -v docker >/dev/null 2>&1; then
    pick_hash_offset "$offset"
  fi
fi

slot=$(( offset * 100 ))

cat <<ENV
unset -f docker 2>/dev/null || true
export COMPOSE_PROJECT_NAME=codemit-dev$( [ "$offset" -eq 0 ] || printf '%s' "-$offset" )
export CODEMIT_DB_PORT=$(( 55432 + slot ))
export CODEMIT_API_PORT=$(( 58000 + slot ))
export CODEMIT_EVENTS_PORT=$(( 58001 + slot ))
export CODEMIT_LLM_PROXY_PORT=$(( 58002 + slot ))
export CODEMIT_REDIS_PORT=$(( 16379 + slot ))
export CODEMIT_PGBOUNCER_PORT=$(( 16432 + slot ))
export CODEMIT_MINIO_PORT=$(( 19000 + slot ))
export CODEMIT_MINIO_CONSOLE_PORT=$(( 19001 + slot ))
export CODEMIT_SEARCH_PORT=$(( 19200 + slot ))
export CODEMIT_WEB_PORT=$(( 53000 + slot ))
export CODEMIT_OPERATOR_WEB_PORT=$(( 53001 + slot ))
export CODEMIT_CLASSROOM_WEB_PORT=$(( 53002 + slot ))
export CODEMIT_E2E_BASE_URL=http://127.0.0.1:$(( 53000 + slot ))
export CODEMIT_OPERATOR_E2E_BASE_URL=http://127.0.0.1:$(( 53001 + slot ))
export CODEMIT_CLASSROOM_E2E_BASE_URL=http://127.0.0.1:$(( 53002 + slot ))
export CODEMIT_API_BASE_URL=http://127.0.0.1:$(( 58000 + slot ))
ENV
