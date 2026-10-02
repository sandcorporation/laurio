#!/bin/bash
# PR CI 가 무엇을 돌릴지 — main 에서 갈라진 뒤 바뀐 파일만 본다(2026-10-02, Jenkinsfile.pr).
#
#   scripts/ci/changed.sh <기준 커밋>   →  TESTS=0|1
#
# 문서(.md·docs/)만 바뀌었으면 TESTS=0 — 문서 검사만 돌고 곧바로 초록이 된다. 그 밖에 하나라도
# 있거나 기준을 모르면 TESTS=1. 백엔드만·앱만 바뀌었다고 한쪽을 건너뛰지는 않는다 — 백엔드
# 변경이 e2e 를 깨뜨릴 수 있다.
set -euo pipefail
base="${1:-}"
if [ -z "$base" ]; then
  echo "TESTS=1"
  exit 0
fi
files=$(git diff --name-only "$base" HEAD)
if [ -z "$files" ]; then
  echo "TESTS=1"
  exit 0
fi
# 파이프로 넘기지 않는다 — pipefail 아래에서 grep 이 먼저 끝나 printf 가 SIGPIPE 로 죽으면
# 「문서만 바뀌었다」로 읽혀 시험을 건너뛴다.
if grep -qvE '(\.md$|^docs/)' <<<"$files"; then
  echo "TESTS=1"
else
  echo "TESTS=0"
fi
