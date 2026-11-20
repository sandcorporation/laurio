#!/bin/bash
# 워크플로 파일 자체의 문법·식 검사(#1105) — `.github/workflows/**` 가 바뀐 PR 에서만 돈다.
#
#   scripts/ci/actionlint.sh <기준 커밋>      기준을 모르면(비어 있으면) 돈다
#   scripts/ci/actionlint.sh --all            바뀐 것과 무관하게 돈다
#
# 파싱이 깨진 워크플로(빈 `env:` 등)는 검사가 아예 뜨지 않아 PR 에 이유가 안 보인다 — 여기서 먼저 잡는다.
# actionlint 는 판과 sha256 을 고정해 내려받는다(공개 저장소 — 검증 없이 실행하지 않는다).
# 이미 PATH 에 같은 판이 있으면(로컬) 내려받지 않는다.
set -euo pipefail
VERSION=1.7.12
SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 # actionlint_${VERSION}_linux_amd64.tar.gz

arg="${1:-}"
if [ "$arg" != "--all" ] && [ -n "$arg" ]; then
  if ! git diff --name-only "$arg" HEAD | grep -q '^\.github/workflows/'; then
    echo "워크플로 변경 없음 — actionlint 건너뜀"
    exit 0
  fi
fi

bin=""
if command -v actionlint >/dev/null 2>&1 && actionlint --version | head -1 | grep -qx "$VERSION"; then
  bin=$(command -v actionlint)
else
  dir=$(mktemp -d)
  curl -fsSL -o "$dir/al.tgz" "https://github.com/rhysd/actionlint/releases/download/v${VERSION}/actionlint_${VERSION}_linux_amd64.tar.gz"
  echo "$SHA256  $dir/al.tgz" | sha256sum -c -
  tar -xzf "$dir/al.tgz" -C "$dir" actionlint
  bin="$dir/actionlint"
fi
"$bin" -color
