#!/bin/bash
# PR CI 가 무엇을 돌릴지 — main 에서 갈라진 뒤 바뀐 파일만 본다(2026-10-02, Jenkinsfile.pr).
#
#   scripts/ci/changed.sh <기준 커밋> [끝 커밋=HEAD]   →  TESTS=0|1  BACK=0|1  FRONT=0|1
#
# 경로 표는 scripts/ci/paths.py 하나다(#1088 — e2e_plan·pytest_plan 과 같은 표). 묶음(#1082):
#   문서     .md · docs/                                 → 이것만이면 TESTS=0 (문서 검사만, 곧바로 초록)
#   백엔드   backend/ · docker/ (uv.lock 포함)            → BACK=1 : pytest 조각·celery·agent-grader
#   프런트   frontend/ · operator/ · classroom/ · packages/ → FRONT=1 : web (static 은 TESTS=1 이면 늘 돈다)
#   그 밖    .github/ · scripts/ · 루트 설정·pnpm-lock 등 공통 → 전부(BACK=1 FRONT=1)
# 기준을 모르거나 바뀐 파일이 없으면(main push) 전부 1.
set -euo pipefail
exec python3 "$(dirname "$0")/paths.py" "$@"
