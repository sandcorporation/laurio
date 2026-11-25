#!/usr/bin/env bash
# 끝난 티켓의 워크트리를 **스택·서버까지 내리고** 지운다 (#1192, #1275).
#
#   scripts/worktree-rm.sh <워크트리 경로> [브랜치]   # 브랜치를 주면 로컬 브랜치도 지운다
#
# 어디서 불러도 된다 — main 체크아웃이 묵어 이 파일이 없어도, 지울 워크트리 안의 사본으로, 그 워크트리 안에
# 선 채로도 돈다. 순서가 중요하다 — 컨테이너·dev 서버를 먼저 내리고 워크트리를 지운다. 거꾸로면 주인 디렉터리가
# 사라져 스택이 고아가 되고(오프셋이 막힌다) dev 서버가 `.vite` 같은 캐시를 다시 만든다.
# `-e2e` 스택은 볼륨까지 지우고(일회용) dev 스택 볼륨은 남긴다. 작업자가 손으로 기억할 일이 아니다.
# 그 워크트리의 dev 칸 예약(#1411)도 푼다.
set -euo pipefail

wt="${1:?워크트리 경로}"
branch="${2:-}"
[ -d "$wt" ] || { echo "워크트리가 없다: $wt"; exit 1; }
wt="$(cd "$wt" && pwd -P)"

# 지울 워크트리가 이 스크립트가 든 곳일 수 있다 — 필요한 파일을 지우기 전에 임시 폴더로 옮겨 두고 거기서 쓴다.
src="$(cd "$(dirname "$0")/.." && pwd -P)"
aux="$(mktemp -d "${TMPDIR:-/tmp}/worktree-rm.XXXXXX")"
trap 'rm -f "$aux"/* 2>/dev/null; rmdir "$aux" 2>/dev/null || true' EXIT
cp "$src/docker/dev-stack-orphans.sh" "$aux/dev-stack-orphans.sh"
cp "$src/docker/dev-slots.sh" "$aux/dev-slots.sh"
[ ! -f "$src/scripts/dev-server.sh" ] || cp "$src/scripts/dev-server.sh" "$aux/dev-server.sh"

# git 에 지우기를 시키는 기준은 주 워크트리다(= git-common-dir 의 부모). 지울 워크트리가 곧 셸 위치여도 거기서 나온다.
common="$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir)"
main="$(cd "$common/.." && pwd -P)"
[ "$wt" != "$main" ] || { echo "주 워크트리는 지우지 않는다: $wt"; exit 1; }
cd "$main"

# 그 워크트리의 dev 서버(next dev 등)부터. dev-server.sh 는 `here` 를 자기 위치로 잡으니 옮긴 사본이 아니라 그 체크아웃의 것을 쓴다.
if [ -f "$wt/scripts/dev-server.sh" ]; then
  CODEMIT_DEV_SERVER_ROOT="$wt" "$wt/scripts/dev-server.sh" stop-all >/dev/null 2>&1 || true
elif [ -f "$aux/dev-server.sh" ]; then
  CODEMIT_DEV_SERVER_ROOT="$wt" bash "$aux/dev-server.sh" stop-all >/dev/null 2>&1 || true
fi

. "$aux/dev-stack-orphans.sh"
dev_stack_down_owned_by "$wt"

# 이미 root 소유 파일이 남았으면(옛 dev 컨테이너의 .pnpm-store 등, #1220) 일회용 컨테이너로 지우고 이어 간다.
if ! git -C "$main" worktree remove --force "$wt" >/dev/null 2>&1; then
  echo "지우지 못한 파일이 있다 — 일회용 컨테이너로 지운다"
  # 이미 내려받은 이미지를 우선 쓴다(오프라인 대비). 워크트리 경로 말고는 아무것도 출력하지 않는다.
  img="$(docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -m1 -E '^(alpine|busybox):' || true)"
  [ -n "$img" ] || img="$(docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -v '<none>' | head -1)"
  [ -n "$img" ] || img=alpine
  docker run --rm --entrypoint sh -v "$wt:/w" "$img" -c 'find /w -mindepth 1 -delete' >/dev/null 2>&1 || true
  # git 이 일부만 지우고 멈췄을 수 있다 — 등록 정보를 정리하고 빈 디렉터리를 치운다.
  git -C "$main" worktree remove --force "$wt" >/dev/null 2>&1 || true
  git -C "$main" worktree prune
  rmdir "$wt" 2>/dev/null || true
fi
# 칸 예약은 디렉터리가 사라진 뒤에 푼다 — 위 dev-server.sh 가 포트를 물으며 다시 적을 수 있다. 못 풀어도 경로가
# 사라진 예약은 고아라 다음 dev-env.sh 가 회수한다.
. "$aux/dev-slots.sh"
if [ ! -d "$wt" ] && dev_slots_lock; then
  dev_slot_release_owned_by "$wt"
  dev_slots_unlock
fi

[ -z "$branch" ] || git -C "$main" branch -D "$branch" >/dev/null 2>&1 || true
echo "워크트리 $wt 정리 끝"
