#!/usr/bin/env bash
# 포크(laurio-restructure, #1084)의 main 에 본 저장소 main 을 당겨 맞춘다 — 매일 한 번, 그리고 포크 티켓을 시작하기 전에.
#
#   bash scripts/fork/sync-upstream.sh            # PR 을 열고 병합 대기열에 넣는다
#   bash scripts/fork/sync-upstream.sh --dry-run  # 무엇을 당길지만 보인다
#
# 포크 main 은 병합 대기열(squash)로만 들어간다. squash 는 본 저장소 커밋을 조상으로 남기지 않아 `git merge` 의 기준이
# 매번 처음 갈라진 곳으로 되돌아간다. 그래서 마지막으로 당긴 본 저장소 sha 를 `scripts/fork/upstream-sha` 에 적어 두고,
# 그 sha..본 저장소 main 의 차이만 3-way 로 얹는다(본 저장소 main 은 squash 만이라 곧은 줄이다).
#
# 충돌이 나면 멈춘다 — 임시 워크트리에서 손으로 풀고 커밋·push·PR 하거나, 그 자리를 포크 티켓에서 먼저 정리한다.
# 이 폴더(scripts/fork/)는 포크에만 있다. 본 저장소로 되돌리는 PR 에는 싣지 않는다.
set -euo pipefail

UPSTREAM_URL=https://github.com/sandcorporation/laurio
FORK=sandcorporation/laurio-restructure
STATE=scripts/fork/upstream-sha
dry=0
[ "${1:-}" = --dry-run ] && dry=1

root=$(git rev-parse --show-toplevel)
cd "$root"
git fetch -q origin main
git fetch -q "$UPSTREAM_URL" main
new=$(git rev-parse FETCH_HEAD)
last=$(git show "origin/main:$STATE" | tr -d '[:space:]')

if [ "$last" = "$new" ]; then
  echo "이미 맞다: 본 저장소 main ${new:0:12}"
  exit 0
fi
if ! git merge-base --is-ancestor "$last" "$new"; then
  echo "기록된 sha ${last:0:12} 가 본 저장소 main 의 조상이 아니다 — $STATE 를 확인한다" >&2
  exit 1
fi

echo "당길 본 저장소 커밋 ($(git rev-list --count "$last..$new")개, ${last:0:12}..${new:0:12}):"
git log --oneline "$last..$new"
[ "$dry" = 1 ] && exit 0

branch="sync/upstream-${new:0:12}"
wt=$(mktemp -d "${TMPDIR:-/tmp}/fork-sync.XXXXXX")
git worktree add -q -b "$branch" "$wt" origin/main
cd "$wt"
if ! git diff --binary "$last" "$new" | git apply -3 --index; then
  echo "충돌 — 워크트리 $wt (브랜치 $branch)에서 풀고 이어 간다" >&2
  exit 1
fi
printf '%s\n' "$new" >"$STATE"
git add "$STATE"
git commit -q -m "본 저장소 main 당겨 맞추기 ${last:0:12}..${new:0:12}"
git push -q -u origin "$branch"
body=$(printf '본 저장소 main %s..%s 를 당긴다(`scripts/fork/sync-upstream.sh`).\n\n%s\n' \
  "${last:0:12}" "${new:0:12}" "$(git log --oneline "$last..$new" | sed 's/^/- /')")
url=$(gh pr create --repo "$FORK" --base main --head "$branch" \
  --title "본 저장소 main 당겨 맞추기 ${new:0:12}" --body "$body")
echo "$url"
cd "$root"
git worktree remove --force "$wt"
# 검사가 끝나기 전에는 대기열이 받지 않는다(「mergeability check has not yet completed」)
gh pr checks "${url##*/}" --repo "$FORK" --watch --fail-fast >/dev/null
bash "$root/scripts/fork/enqueue.sh" "${url##*/}"
echo "대기열에 넣었다: $url"
