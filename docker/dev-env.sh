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
# 해시가 겹치면 두 워크트리가 같은 포트를 받고, 그러면 나중에 뜨는 쪽이 **포트 바인딩
# 실패로 죽는다.** 그 편이 낫다 — 조용히 남의 스택에 붙어 서로의 데이터를 보는 것보다
# 못 뜨는 것이 언제나 진단하기 쉽다.

set -eu

# **cwd 가 아니라 이 스크립트의 위치를 기준으로 삼는다.** 어디서 부르든 「이 체크아웃」이
# 답이어야 한다 — cwd 로 판정하면 다른 디렉터리에서 부른 순간 남의 스택 값을 뱉는다.
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(git -C "$script_dir" rev-parse --show-toplevel)
main_worktree=$(git -C "$script_dir" worktree list --porcelain | awk '/^worktree /{print $2; exit}')

if [ "$root" = "$main_worktree" ]; then
  offset=0
else
  # 0 이 아닌 1~9 로 접는다 — 0 은 주 워크트리의 몫이다.
  # **앞의 0 을 직접 뗀다.** `039` 를 그대로 넘기면 셸이 8진수로 읽어 죽고, `10#` 은
  # bash 확장이라 `sh`(dash)에서는 쓸 수 없다 — 이 스크립트는 `sh` 로 불린다.
  digits=$(printf '%s' "$root" | sha256sum | tr -dc '0-9' | cut -c1-3 | sed 's/^0*//')
  offset=$(( (${digits:-0} % 9) + 1 ))
fi

slot=$(( offset * 100 ))

cat <<ENV
export COMPOSE_PROJECT_NAME=laurio-dev$( [ "$offset" -eq 0 ] || printf '%s' "-$offset" )
export LAURIO_DB_PORT=$(( 55432 + slot ))
export LAURIO_API_PORT=$(( 58000 + slot ))
export LAURIO_REDIS_PORT=$(( 16379 + slot ))
export LAURIO_MINIO_PORT=$(( 19000 + slot ))
export LAURIO_MINIO_CONSOLE_PORT=$(( 19001 + slot ))
export LAURIO_WEB_PORT=$(( 53000 + slot ))
export LAURIO_OPERATOR_WEB_PORT=$(( 53001 + slot ))
export LAURIO_E2E_BASE_URL=http://127.0.0.1:$(( 53000 + slot ))
export LAURIO_OPERATOR_E2E_BASE_URL=http://127.0.0.1:$(( 53001 + slot ))
export LAURIO_API_BASE_URL=http://127.0.0.1:$(( 58000 + slot ))
ENV
