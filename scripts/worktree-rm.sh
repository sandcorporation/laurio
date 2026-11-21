#!/usr/bin/env bash
# 끝난 티켓의 워크트리를 **스택·서버까지 내리고** 지운다 (#1192).
#
#   scripts/worktree-rm.sh <워크트리 경로> [브랜치]   # 브랜치를 주면 로컬 브랜치도 지운다
#
# 순서가 중요하다 — 컨테이너·dev 서버를 먼저 내리고 워크트리를 지운다. 거꾸로면 주인 디렉터리가 사라져 스택이
# 고아가 되고(오프셋이 막히고 grader 가 재시작을 되풀이한다) dev 서버가 `.vite` 같은 캐시를 다시 만든다.
# `-e2e` 스택은 볼륨까지 지우고(일회용) dev 스택 볼륨은 남긴다. 작업자가 손으로 기억할 일이 아니다.
set -euo pipefail

wt="${1:?워크트리 경로}"
branch="${2:-}"
here="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$wt" ] || { echo "워크트리가 없다: $wt"; exit 1; }
wt="$(cd "$wt" && pwd -P)"
[ "$wt" != "$(cd "$here" && pwd -P)" ] || { echo "이 스크립트가 속한 체크아웃은 지우지 않는다"; exit 1; }

# 그 워크트리의 dev 서버(next dev 등)부터.
CODEMIT_DEV_SERVER_ROOT="$wt" "$here/scripts/dev-server.sh" stop-all >/dev/null 2>&1 || true

. "$here/docker/dev-stack-orphans.sh"
dev_stack_down_owned_by "$wt"

git -C "$here" worktree remove --force "$wt"
[ -z "$branch" ] || git -C "$here" branch -D "$branch" >/dev/null 2>&1 || true
echo "워크트리 $wt 정리 끝"
