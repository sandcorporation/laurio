#!/bin/bash
# 시험 CPU 한도 배율의 기준(backend/tests/cpu_reference.json)을 다시 쓴다(#1211). 사람이 돌리고 결과를 커밋한다.
#
#   cpu-reference-update.sh        최근 초록 병합 대기열 실행 8번(전부를 돈다, #1090)의 junit 에서
#   cpu-reference-update.sh N      최근 N번에서
#
# 시험마다 CPU 초의 중앙값을 낸다 — 실행기 셋이 섞인 값이라 배율 1.0 이 가운데 무리다(`backend/tests/cpu_speed.py`).
# 언제: 「CPU 기준표가 낡았다」 ci-red 이슈가 열렸을 때(release.yml 의 cpu_reference_watch 잡, #1222).
set -euo pipefail
cd "$(dirname "$0")/../.."

dir=$(mktemp -d)
trap 'rm -r "$dir"' EXIT
bash scripts/ci/cpu-junit.sh "$dir" "${1:-8}"
mapfile -t xmls < <(find "$dir" -name '*.xml' | sort)
python3 backend/tests/cpu_speed.py update "${xmls[@]}"
