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
