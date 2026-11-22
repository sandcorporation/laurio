#!/usr/bin/env bash
# 같은 저장소의 fetch 를 한 줄로 세운다(#1280) — 자동화·조율자·작업자가 같은 체크아웃(워크트리는 ref 를 공유한다)에
# 같은 순간 fetch 하면 `incorrect old value provided` 로 뒤에 쓴 쪽이 진다. 재시도로 덮지 않고 잠금으로 막는다.
#
#   scripts/git-fetch-locked.sh [fetch 인자…]        예) scripts/git-fetch-locked.sh -q origin main
#
# 잠금은 `<git-common-dir>/codemit-fetch.lock`(scripts/automation-run.sh 의 따라잡기와 같은 파일)이다.
# CODEMIT_FETCH_LOCK_WAIT(초, 기본 60) 안에 못 잡으면 「잠금 대기 초과」로 75 로 끝난다.
# 저장소는 현재 디렉터리, 아니면 CODEMIT_FETCH_REPO.
set -uo pipefail

repo="${CODEMIT_FETCH_REPO:-.}"
wait_secs="${CODEMIT_FETCH_LOCK_WAIT:-60}"
command -v flock >/dev/null || { echo "flock 이 없다(mac 은 brew install flock)" >&2; exit 2; }
common="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
  || { echo "git 저장소가 아니다: $repo" >&2; exit 2; }
exec 9>"$common/codemit-fetch.lock"
flock -w "$wait_secs" 9 || { echo "잠금 대기 초과: ${wait_secs}초 안에 $common/codemit-fetch.lock 을 못 잡았다" >&2; exit 75; }
git -C "$repo" fetch "$@"
