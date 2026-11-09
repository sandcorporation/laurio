#!/bin/bash
# CI 이미지 안에서 도는 home 쪽 검사 전부 — `scripts/ci/sub-checks.sh` 가 부른다.
#
# 하나가 실패해도 나머지는 끝까지 돈다(어디가 깨졌는지 한 번에 본다). 단계마다 결과와 걸린
# 시간을 test-results/summary.txt 에 적고, 하나라도 실패하면 1 로 끝난다.
set -uo pipefail
cd /repo
mkdir -p test-results
summary=test-results/summary.txt
: >"$summary"
failed=0

step() {
  local name="$1"
  shift
  local started=$SECONDS
  echo "::: $name"
  if ( "$@" ); then
    echo "통과  $name ($((SECONDS - started))초)" | tee -a "$summary"
  else
    echo "실패  $name ($((SECONDS - started))초)" | tee -a "$summary"
    failed=1
  fi
}

# 생성물이 커밋된 것과 같은가 — 다시 만들어 비교한다(이미지에는 .git 이 없다).
same_after() {
  local file="$1"
  shift
  cp "$file" /tmp/before
  "$@" >/dev/null && cmp -s /tmp/before "$file" || {
    echo "$file 이 최신이 아니다 — 다시 생성해 함께 커밋한다."
    diff /tmp/before "$file" | head -20
    return 1
  }
}

deploy_check() {
  set -a
  # shellcheck disable=SC1091
  . scripts/ci/deploy-check.env
  set +a
  cd backend && uv run python manage.py check --deploy --fail-level WARNING
}

# 어느 묶음을 돌릴지 — 인자 없이는 전부(로컬·한 번에 도는 길). GitHub Actions 는 matrix 로 나눠 부른다(#932):
#   static          Django 검사·배포 구성 검사·생성물 최신성·문서/언어/고정 대기 검사(파이썬 스크립트)
#   pytest [I/N]    백엔드 pytest — I/N 이면 정렬한 시험 파일을 순번 % N 으로 나눈 I번째(1부터) 조각
#   web             단위 시험(packages·세 앱)과 세 앱 타입 검사
group="${1:-all}"
shard="${2:-}"
case "$group" in all|static|pytest|web) ;; *) echo "알 수 없는 묶음: $group (static|pytest [I/N]|web)" >&2; exit 2 ;; esac
want() { [ "$group" = all ] || [ "$group" = "$1" ]; }

pytest_run() {
  local idx total files
  if [ -z "$shard" ]; then
    ( cd backend && CODEMIT_TEST_CPU_LIMIT=1.5 uv run pytest -p no:cacheprovider \
        --junitxml=/repo/test-results/backend-junit.xml )
    return
  fi
  idx="${shard%/*}"; total="${shard#*/}"
  files=$(cd backend && find tests -name 'test_*.py' | LC_ALL=C sort | awk -v i="$idx" -v n="$total" '(NR - 1) % n == i - 1')
  [ -n "$files" ] || { echo "조각 $shard 에 시험 파일이 없다"; return 1; }
  # shellcheck disable=SC2086
  ( cd backend && CODEMIT_TEST_CPU_LIMIT=1.5 uv run pytest -p no:cacheprovider \
      --junitxml="/repo/test-results/backend-junit-${idx}of${total}.xml" $files )
}

if want static; then
  step "Django 검사" bash -c 'cd backend && uv run python manage.py check --fail-level WARNING'
  step "배포 구성 검사(check --deploy)" deploy_check
fi
if want pytest; then
  step "문법 검사 문법 받기" bash -c 'cd backend && uv run python manage.py prefetch_syntax_grammars --skip-checks'
  step "백엔드 pytest ${shard:-전체}" pytest_run
fi
if want static; then
  step "API 타입 최신성" same_after packages/bff-client/src/schema.gen.ts pnpm --dir frontend generate:api
  step "금칙어 생성물 최신성" same_after packages/banned-words/src/generated/banned-words.gen.ts \
    pnpm --dir packages/banned-words run generate
  step "ADR 상태" python3 scripts/check_adr_status.py
  step "화면 언어" python3 scripts/check_screen_language.py
  step "화면 언어 검사기 자체" python3 scripts/test_check_screen_language.py
  step "GlitchTip precheck 청소 판정" python3 scripts/test_glitchtip_pick.py
  step "이미지 문맥 해시(건너뛰기)" python3 scripts/test_image_context.py
  step "ghcr 정리가 살아 있는 커밋을 남긴다" python3 scripts/test_ghcr_prune.py
  step "배포 이미지 스크립트(건너뛰기·e2e 태그)" python3 scripts/test_ci_images.py
  step "백엔드 오류 문구 언어" python3 scripts/check_backend_error_language.py
  step "시험의 고정 대기 금지" python3 scripts/check_test_waits.py
  step "고정 대기 검사기 자체" python3 scripts/test_check_test_waits.py
fi
if want web; then
  for pkg in packages/bff-shared packages/markdown packages/banned-words; do
    step "단위 시험 $pkg" pnpm --dir "$pkg" run test
  done
  for app in frontend operator classroom; do
    step "단위 시험 $app" pnpm --dir "$app" run test:unit
    step "타입 검사 $app" pnpm --dir "$app" run typecheck
  done
fi

echo
cat "$summary"
exit "$failed"
