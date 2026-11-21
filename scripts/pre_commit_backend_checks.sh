#!/usr/bin/env bash
# 커밋 훅의 백엔드 빠른 검사(#1226) — CI 에서야 잡히던 실수를 몇 초로 당긴다. `.githooks/pre-commit` 이
# backend/**/*.py 가 staged 일 때 부른다. 앞 검사가 실패하면 뒤 것은 돌리지 않는다(문법이 깨지면
# Django 검사·시험은 같은 말만 한다).
#  1. 문법(닫히지 않은 docstring — CI `plan` 잡)
#  2. Django 검사(CI `checks static` 의 `manage.py check --fail-level WARNING`. `--deploy`·마이그레이션
#     호환은 설정·DB 가 있어야 해 뺐다)
#  3. DB 없이 도는 구조 시험 셋 — 「등록 누락」을 잡는다(금칙어 필드 등록 등). `-n 0` 은 DB 템플릿을 미리
#     만들지 않게 하는 길이고, `CODEMIT_TEST_ENTRY` 는 입구 스크립트(칸 대기)를 건너뛰는 표지다 —
#     DB 를 안 쓰는 2초짜리라 칸을 잡을 까닭이 없다.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)/backend"
echo "pre-commit: backend 변경 감지 — 문법·Django 검사·구조 시험을 돈다."

fail=0
uv run --quiet python ../scripts/check_staged_python_syntax.py || fail=1
[ "$fail" -ne 0 ] || uv run --quiet python manage.py check --fail-level WARNING || fail=1
[ "$fail" -ne 0 ] || CODEMIT_TEST_ENTRY=pre-commit uv run --quiet pytest -p no:cacheprovider -n 0 -q \
  tests/test_banned_word_field_registration.py tests/test_app_boundaries.py \
  tests/test_classroom_instructor_scope_structure.py || fail=1

if [ "$fail" -ne 0 ]; then
  echo "pre-commit: 백엔드 빠른 검사가 실패했다 — 커밋을 거절한다. (--no-verify 로 넘어갈 수 있으나 CI 가 같은 것을 돈다)" >&2
  exit 1
fi
