#!/bin/bash
# PR CI 가 무엇을 돌릴지 — main 에서 갈라진 뒤 바뀐 파일만 본다(2026-10-02, Jenkinsfile.pr).
#
#   scripts/ci/changed.sh <기준 커밋> [끝 커밋=HEAD]   →  TESTS=0|1  BACK=0|1  FRONT=0|1
#
# 바뀐 경로를 세 묶음으로 가른다(#1082):
#   문서     .md · docs/                                 → 이것만이면 TESTS=0 (문서 검사만, 곧바로 초록)
#   백엔드   backend/ · docker/ (uv.lock 포함)            → BACK=1 : pytest 조각·celery·agent-grader
#   프런트   frontend/ · operator/ · classroom/ · packages/ → FRONT=1 : web (static 은 TESTS=1 이면 늘 돈다)
#   그 밖    .github/ · scripts/ · 루트 설정·pnpm-lock 등 공통 → 전부(BACK=1 FRONT=1)
# 기준을 모르거나 바뀐 파일이 없으면(main push) 전부 1.
set -euo pipefail
all() { echo "TESTS=1"; echo "BACK=1"; echo "FRONT=1"; }
base="${1:-}"
if [ -z "$base" ]; then
  all
  exit 0
fi
files=$(git diff --name-only "$base" "${2:-HEAD}")
if [ -z "$files" ]; then
  all
  exit 0
fi
tests=0 back=0 front=0
# 파이프로 넘기지 않는다 — 읽기 루프는 here-string 으로(pipefail·SIGPIPE 로 「문서만」으로 잘못 읽히는 것을 막는다).
while IFS= read -r f; do
  case "$f" in
    *.md | docs/*) ;;
    backend/* | docker/*) tests=1; back=1 ;;
    frontend/* | operator/* | classroom/* | packages/*) tests=1; front=1 ;;
    *) tests=1; back=1; front=1 ;;
  esac
done <<<"$files"
echo "TESTS=$tests"
echo "BACK=$back"
echo "FRONT=$front"
