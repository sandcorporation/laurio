#!/usr/bin/env bash
# 전후 비교 스크린샷을 **차례로** 찍는다(#976). before·after 서버를 동시에 띄우지 않는다 —
# 앱 하나의 before 를 빌드해 띄워 찍고 내린 뒤, after 를 그렇게 한다. 같은 시각에 뜬 next 는 하나.
#
#   scripts/shoot-before-after.sh --app classroom --before origin/main \
#       --paths /login,/ --sizes 1440,390 --themes light,dark --out /tmp/shots
#
#   --app      front|operator|classroom (필수)
#   --before   비교할 git 참조(기본 origin/main). 스크립트가 임시 워크트리를 만들고 끝나면 지운다
#   --paths    쉼표로 나눈 경로(기본 /)         --sizes   너비(기본 1440,390)
#   --themes   light,dark(기본 둘 다)           --out     그림 폴더(기본 ./shots)
# after 는 이 스크립트가 있는 워크트리다. 파일명: <before|after>-<경로>-<너비>-<테마>.png
#
# 서버는 `dev-server.sh start --built`(빌드 뒤 next start — RSS 약 0.3GB)로 띄운다. 메모리
# 여유가 없으면 dev-server.sh 가 거절하고 이 스크립트도 멈춘다. 끝나면 항상 stop-all.

set -euo pipefail
after_root="$(cd "$(dirname "$0")/.." && pwd)"
app="" before="origin/main" paths="/" sizes="1440,390" themes="light,dark" out="./shots"
while [ $# -gt 0 ]; do
  case "$1" in
    --app) app="$2" ;; --before) before="$2" ;; --paths) paths="$2" ;;
    --sizes) sizes="$2" ;; --themes) themes="$2" ;; --out) out="$2" ;;
    *) echo "모르는 인자: $1" >&2; exit 2 ;;
  esac; shift 2
done
[ -n "$app" ] || { echo "--app 이 필요하다" >&2; exit 2; }
case "$app" in front) dir=frontend ;; operator|classroom) dir="$app" ;; *) echo "모르는 앱: $app" >&2; exit 2 ;; esac
mkdir -p "$out"; out="$(cd "$out" && pwd)"

before_root="$after_root/../.shoot-before-$$"
cleanup() {
  [ -d "$before_root" ] && { CODEMIT_DEV_SERVER_ROOT="$before_root" "$after_root/scripts/dev-server.sh" stop-all >/dev/null 2>&1 || true
    git -C "$after_root" worktree remove --force "$before_root" >/dev/null 2>&1 || true; }
  "$after_root/scripts/dev-server.sh" stop-all >/dev/null 2>&1 || true
}
trap cleanup EXIT

shoot() {  # $1 = 워크트리 루트, $2 = before|after
  local root="$1" label="$2" port
  CODEMIT_DEV_SERVER_ROOT="$root" "$after_root/scripts/dev-server.sh" start --built "$app"
  port="$(CODEMIT_DEV_SERVER_ROOT="$root" "$after_root/scripts/dev-server.sh" port "$app")"
  SHOOT_PIDFILE="$(CODEMIT_DEV_SERVER_ROOT="$root" "$after_root/scripts/dev-server.sh" browser-pidfile)" \
    node "$after_root/scripts/shoot.mjs" "http://127.0.0.1:$port" "$out" "$label" "$paths" "$sizes" "$themes" "$after_root"
  CODEMIT_DEV_SERVER_ROOT="$root" "$after_root/scripts/dev-server.sh" stop-all
}

echo "== before ($before)"
git -C "$after_root" worktree add --detach "$before_root" "$before" >/dev/null
( cd "$before_root" && pnpm install --frozen-lockfile --offline >/dev/null )
shoot "$before_root" before
git -C "$after_root" worktree remove --force "$before_root"
echo "== after"
shoot "$after_root" after
echo "끝: $out"
