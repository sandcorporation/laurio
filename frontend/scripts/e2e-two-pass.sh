#!/bin/bash
# e2e 의 두 패스 — 그 정의는 여기 하나다(#702). package.json 의 `test:public`·`test:operator`·
# `test:classroom`, CI 의 `scripts/ci/e2e.sh`, 로컬의 `scripts/test.sh e2e` 셋이 모두 이것을 부른다.
#
#   frontend/scripts/e2e-two-pass.sh <public|operator|classroom|all> [playwright 인자…]
#
# ① `--grep-invert @exclusive` — 일꾼 수는 PLAYWRIGHT_WORKERS(없으면 playwright.config 의 기본값).
# ② `--grep @exclusive --workers=1` — 전역 상태를 건드리는 스펙을 일꾼 하나로 따로.
# 첫 패스가 붉어도 둘째 패스를 돈다 — 한 번의 실행에서 실패를 더 많이 남기려는 것이다(#700).
# 어느 쪽이든 붉으면 그 종료코드로 끝난다.
#
# 출력 폴더(frontend 기준). Playwright 는 실행마다 출력 폴더를 비우므로 패스마다 따로 둔다 — 같은
# 폴더면 뒤 패스(시험 0개여도)가 앞 패스의 실패 trace 를 지운다(#699).
#   E2E_OUTPUT_DIR            ① 의 폴더(없으면 config 기본값 `test-results/`)
#   E2E_EXCLUSIVE_OUTPUT_DIR  ② 의 폴더(없으면 `test-results/exclusive/`)
#
# `--pass-with-no-tests` 는 둘째 패스에서 **classroom 에만** 붙인다 — 강의실에는 아직 `@exclusive`
# 스펙이 없어 「No tests found」로 exit 1 한다. public·operator 에는 붙이지 않는다: 그쪽 `@exclusive`
# 스펙이 태그가 바뀌어 grep 에서 빠지면 붉어져야 한다. E2E_ALLOW_EMPTY=1 이면 두 패스 모두에
# 붙인다 — 파일 하나로 좁힌 로컬 실행(`scripts/test.sh e2e <파일>`)은 그 파일에 한쪽 패스의 시험이
# 없을 수 있다.
set -uo pipefail
cd "$(dirname "$0")/.."

target=${1:?"쓰임: $0 <public|operator|classroom|all> [playwright 인자…]"}
shift
project=()
case "$target" in
  public|operator|classroom) project=(--project="$target") ;;
  all) ;;
  *) echo "모르는 대상: $target" >&2; exit 2 ;;
esac

first=(--grep-invert @exclusive)
second=(--grep @exclusive --workers=1 --output="${E2E_EXCLUSIVE_OUTPUT_DIR:-test-results/exclusive}")
[ -n "${E2E_OUTPUT_DIR:-}" ] && first+=(--output="$E2E_OUTPUT_DIR")
if [ -n "${E2E_ALLOW_EMPTY:-}" ]; then
  first+=(--pass-with-no-tests)
  second+=(--pass-with-no-tests)
elif [ "$target" = classroom ]; then
  second+=(--pass-with-no-tests)
fi

# macos 노드의 /bin/bash 는 3.2 라 `set -u` 아래 빈 배열을 펼치면 죽는다 — `${a[@]+…}` 로 감싼다.
status=0
pnpm exec playwright test ${project[@]+"${project[@]}"} "${first[@]}" "$@" || status=$?
pnpm exec playwright test ${project[@]+"${project[@]}"} "${second[@]}" "$@" || status=$?
exit "$status"
