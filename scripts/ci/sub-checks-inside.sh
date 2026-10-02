#!/bin/bash
# CI 이미지 안에서 도는 sub 쪽 검사 전부 — `scripts/ci/sub-checks.sh` 가 부른다.
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

step "Django 검사" bash -c 'cd backend && uv run python manage.py check --fail-level WARNING'
step "배포 구성 검사(check --deploy)" deploy_check
step "문법 검사 문법 받기" bash -c 'cd backend && uv run python manage.py prefetch_syntax_grammars --skip-checks'
step "백엔드 pytest" bash -c 'cd backend && CODEMIT_TEST_CPU_LIMIT=1.5 uv run pytest -p no:cacheprovider \
  --junitxml=/repo/test-results/backend-junit.xml'
step "API 타입 최신성" same_after packages/bff-client/src/schema.gen.ts pnpm --dir frontend generate:api
step "금칙어 생성물 최신성" same_after packages/banned-words/src/generated/banned-words.gen.ts \
  pnpm --dir packages/banned-words run generate
step "ADR 상태" python3 scripts/check_adr_status.py
step "화면 언어" python3 scripts/check_screen_language.py
step "화면 언어 검사기 자체" python3 scripts/test_check_screen_language.py
step "백엔드 오류 문구 언어" python3 scripts/check_backend_error_language.py
for pkg in packages/bff-shared packages/markdown packages/banned-words; do
  step "단위 시험 $pkg" pnpm --dir "$pkg" run test
done
for app in frontend operator classroom; do
  step "단위 시험 $app" pnpm --dir "$app" run test:unit
  step "타입 검사 $app" pnpm --dir "$app" run typecheck
done

echo
cat "$summary"
exit "$failed"
