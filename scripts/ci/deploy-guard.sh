#!/usr/bin/env bash
# 프론트 배포 부팅 가드(FE-13, #38) — 방금 올린 staging 이미지가 설정 없이는 죽고, 완전한 설정으로는
# 뜨는지 본다(#705, Jenkinsfile 「부팅 가드」, sub 에서 돈다).
#
#   scripts/ci/deploy-guard.sh <frontend|operator|classroom>
#
# 예전에는 GitHub Actions(`images.yaml` 의 `*-deploy-guard` 셋)였다 — 로직은 그대로 옮겼다.
#
# **왜 실행 중인 앱을 치는 e2e 시임이 아닌가.** ADR-0017 은 프론트 시험 시임을 「실행 중인 Next 앱
# 하나」로 못 박는데, 여기서 증명할 것은 정반대다 — **앱이 뜨지 않는 것**. 그래서 배포되는 바로 그
# 이미지(ghcr 의 `<sha>-amd64`)를 받아 컨테이너로 띄우고 종료 코드와 로그를 본다. 처음에는
# instrumentation.ts 의 register() 가 throw 만 하면 될 줄 알았지만, standalone(`node server.js`)은
# 그 에러를 unhandledRejection 으로 로그만 찍고 삼켜 컨테이너가 Up 인 채 모든 요청에 500 을 냈다 —
# 그래서 instrumentation.ts 가 `process.exit(1)` 로 끊고, 이 가드는 「빌드가 됐다」가 아니라
# 「컨테이너가 실제로 죽는다」를 본다.
#
# 컨테이너 포트를 노드에 열지 않는다 — 띄운 컨테이너의 네트워크에 curl 컨테이너를 붙여
# (`--network container:<이름>`) 친다. sub 의 Jenkins 는 컨테이너라 바인드 마운트도 쓰지 않는다.
#
# 환경변수: GHCR_TOKEN/GHCR_USER(읽기에 쓴다, 없으면 노드의 로그인), CODEMIT_IMAGE_REGISTRY,
# CODEMIT_GUARD_IMAGE(받을 이미지를 통째로 바꾼다 — 로컬 시험용). bash 3.2 문법만 쓴다.
#
# 앱 이미지는 환경을 모른다(#711, ADR-0062) — 공개 값(`CODEMIT_PUBLIC_*`)은 실행 env 로 받는다. 그래서
# 이 가드도 값을 `-e` 로 주고, 그 값이 서버 렌더(/privacy)와 브라우저(`window.__CODEMIT_PUBLIC__`)에
# 닿는지 본다. 서버의 `.env.<target>` 에 값이 있는지는 compose 의 `${…:?}` 가 배포 때 본다.
set -euo pipefail

app="${1:-}"
case "$app" in
  frontend|operator|classroom) ;;
  *) echo "쓰는 법: $0 <frontend|operator|classroom>" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/../.."
# shellcheck source=scripts/ci/ghcr-login.sh
. scripts/ci/ghcr-login.sh

registry="${CODEMIT_IMAGE_REGISTRY:-ghcr.io/sandcorporation}"
sha="$(git -c safe.directory="$PWD" rev-parse HEAD)"
image="${CODEMIT_GUARD_IMAGE:-$registry/codemit-$app:$sha-amd64}"
local_image="codemit-$app-runner-ci"
box="$app-boot-ok"
probe="codemit-$app-context-probe"
curl_image="curlimages/curl:8.11.1"

fail() {
  echo "가드 실패: $*" >&2
  exit 1
}

cleanup() {
  rc=$?
  if [ "$rc" -ne 0 ]; then docker ps -a || true; fi
  docker rm -f "$box" >/dev/null 2>&1 || true
  docker rmi -f "$local_image" >/dev/null 2>&1 || true
  docker rmi -f "$probe" >/dev/null 2>&1 || true
  rm -f "$app/.env"
  rm -rf "$app/node_modules/.ci-guard-marker"
  if [ -f "$app/.env.guard-backup" ]; then mv "$app/.env.guard-backup" "$app/.env"; fi
  ghcr_logout
  exit "$rc"
}
trap cleanup EXIT
# Jenkins 가 중단하면(SIGTERM) EXIT trap 이 돌도록 — 안 그러면 컨테이너와 토큰이 담긴 임시 DOCKER_CONFIG 가 남는다.
trap 'exit 130' INT TERM

step() { echo; echo "── $*"; }

ghcr_login

step "이 커밋이 배포하는 $app 이미지를 받는다: $image"
docker pull -q "$image"
docker tag "$image" "$local_image"

# ── .dockerignore 가 시크릿과 호스트 node_modules 를 빌드 문맥에서 실제로 막는가 ────────────
step ".dockerignore 가 시크릿·호스트 node_modules 를 문맥에서 뺀다"
if [ -e "docker/$app.Dockerfile.dockerignore" ]; then
  fail "docker/$app.Dockerfile.dockerignore 가 생겼다 — 이 검사는 루트 .dockerignore 만 본다. 검사를 그 파일에 맞춰 고친다"
fi
# 로컬에서 돌릴 때 그 자리의 진짜 .env 를 지우지 않게 비켜 두고 끝에 되돌린다.
if [ -f "$app/.env" ]; then mv "$app/.env" "$app/.env.guard-backup"; fi
# 표식에 빌드마다 다른 값을 섞는다 — 이 스크립트도 문맥에 드므로, 고정 문자열이면 grep 이 이 파일에서
# 그것을 찾아 늘 빨갛다(예전 images.yaml 은 .dockerignore 가 빼는 .github/ 에 있어 몰랐다).
nonce="$$-$(date +%s)"
secret_marker="sk-ci-guard-fake-secret-$nonce"
module_marker="host-node-modules-should-not-leak-$nonce"
echo "OPENAI_API_KEY=$secret_marker" > "$app/.env"
mkdir -p "$app/node_modules/.ci-guard-marker"
echo "$module_marker" > "$app/node_modules/.ci-guard-marker/marker.txt"
printf 'FROM busybox:1.36\nCOPY . /ctx\n' | docker build -q -f - -t "$probe" . >/dev/null
docker run --rm -e APP="$app" -e SECRET_MARKER="$secret_marker" -e MODULE_MARKER="$module_marker" "$probe" sh -c '
  set -e
  if [ -f "/ctx/$APP/.env" ]; then
    echo "FOUND $APP/.env — .dockerignore가 시크릿을 막지 못했다" >&2
    exit 1
  fi
  if [ -d "/ctx/$APP/node_modules/.ci-guard-marker" ]; then
    echo "FOUND $APP/node_modules/.ci-guard-marker — .dockerignore가 호스트 node_modules를 막지 못했다" >&2
    exit 1
  fi
  if grep -rlF -e "$SECRET_MARKER" -e "$MODULE_MARKER" /ctx > /dev/null 2>&1; then
    echo "가짜 시크릿 또는 host node_modules 마커가 빌드 컨텍스트 어딘가에 들어갔다" >&2
    exit 1
  fi
  echo "confirmed: .env and host node_modules excluded from the build context"
'
rm -f "$app/.env"
rm -rf "$app/node_modules/.ci-guard-marker"
if [ -f "$app/.env.guard-backup" ]; then mv "$app/.env.guard-backup" "$app/.env"; fi

# ── 설정이 모자라면 죽는가 ─────────────────────────────────────────────────────
# 죽어야 하는 실행 — 0(떴다)이나 124(60초 동안 살아 있었다)면 가드가 깨졌다. 출력은 $out 에.
must_die() {
  local why="$1"
  shift
  local status=0
  out="$(timeout 60 docker run --rm "$@" "$local_image" 2>&1)" || status=$?
  echo "$out"
  if [ "$status" -eq 0 ] || [ "$status" -eq 124 ]; then
    fail "$why 없이도 컨테이너가 죽지 않았다(status=$status) — 부팅 가드가 깨졌다"
  fi
}
must_say() {
  local word
  for word in "$@"; do
    case "$out" in
      *"$word"*) ;;
      *) fail "에러 메시지에 원인($word)이 안 남는다" ;;
    esac
  done
}

case "$app" in
  frontend)
    origin_var=CODEMIT_WEB_ORIGIN
    origin=https://codemit.example
    staging_origin=https://staging.codemit.example
    ;;
  operator)
    origin_var=CODEMIT_OPERATOR_ORIGIN
    origin=https://operator.codemit.example
    staging_origin=https://operator.staging.codemit.example
    ;;
  classroom)
    origin_var=CODEMIT_CLASSROOM_ORIGIN
    origin=https://classroom.codemit.example
    staging_origin=https://classroom.staging.codemit.example
    ;;
esac

step "production 에서 필수 설정이 없으면 죽는다(로그만 찍지 않고)"
must_die "$origin_var/CODEMIT_API_BASE_URL" -e CODEMIT_DEPLOYMENT_TARGET=production
must_say "$origin_var" CODEMIT_API_BASE_URL
if [ "$app" = classroom ]; then must_say CODEMIT_SESSION_COOKIE_DOMAIN; fi

step "staging 에서 필수 값 하나만 빠져도 죽는다"
must_die CODEMIT_API_BASE_URL -e CODEMIT_DEPLOYMENT_TARGET=staging -e "$origin_var=$staging_origin"
must_say CODEMIT_API_BASE_URL
if [ "$app" = classroom ]; then must_say CODEMIT_SESSION_COOKIE_DOMAIN; fi

if [ "$app" = frontend ]; then
  step "production 에서 카카오 자격증명이 없으면 죽는다"
  must_die "카카오 자격증명" -e CODEMIT_DEPLOYMENT_TARGET=production \
    -e CODEMIT_WEB_ORIGIN=https://codemit.example -e CODEMIT_API_BASE_URL=http://127.0.0.1:1
  must_say KAKAO_REST_API_KEY KAKAO_SECRET_KEY KAKAO_REDIRECT_URI

  step "production 에서 토스 클라이언트 키가 없으면 죽는다"
  must_die "토스 클라이언트 키" -e CODEMIT_DEPLOYMENT_TARGET=production \
    -e CODEMIT_WEB_ORIGIN=https://codemit.example -e CODEMIT_API_BASE_URL=http://127.0.0.1:1 \
    -e KAKAO_REST_API_KEY=ci-guard-only-kakao-rest-api-key \
    -e KAKAO_SECRET_KEY=ci-guard-only-kakao-secret-key \
    -e KAKAO_REDIRECT_URI=https://codemit.example/api/auth/social/kakao/callback \
    -e CODEMIT_PUBLIC_TOSS_CLIENT_KEY=
  must_say CODEMIT_PUBLIC_TOSS_CLIENT_KEY
fi

# ── 완전한 설정으로는 뜨는가 ────────────────────────────────────────────────────
step "완전한 production 설정으로는 뜬다"
for _ in 1 2 3; do
  docker image inspect "$curl_image" >/dev/null 2>&1 && break
  docker pull -q "$curl_image" >/dev/null 2>&1 || sleep 3
done
# 띄운 컨테이너의 망에 붙은 curl. 125(docker 자신의 실패)는 잠깐 뒤 다시.
c() {
  local rc
  for _ in 1 2 3; do
    rc=0
    docker run --rm --network "container:$box" "$curl_image" "$@" || rc=$?
    [ "$rc" -ne 125 ] && return "$rc"
    sleep 2
  done
  return 125
}

docker rm -f "$box" >/dev/null 2>&1 || true
case "$app" in
  frontend)
    docker run -d --name "$box" \
      -e CODEMIT_DEPLOYMENT_TARGET=production \
      -e CODEMIT_WEB_ORIGIN=https://codemit.example \
      -e CODEMIT_API_BASE_URL=http://127.0.0.1:1 \
      -e CODEMIT_SESSION_COOKIE_DOMAIN=.codemit.example \
      -e KAKAO_REST_API_KEY=ci-guard-only-kakao-rest-api-key \
      -e KAKAO_SECRET_KEY=ci-guard-only-kakao-secret-key \
      -e KAKAO_REDIRECT_URI=https://codemit.example/api/auth/social/kakao/callback \
      -e CODEMIT_PUBLIC_TOSS_CLIENT_KEY=ci-guard-only-toss-client-key \
      -e CODEMIT_PUBLIC_SUPPORT_EMAIL=privacy-guard@codemit.example \
      -e TOSS_SECRET_KEY=ci-guard-only-toss-secret-key \
      "$local_image" >/dev/null
    ;;
  operator)
    docker run -d --name "$box" \
      -e CODEMIT_DEPLOYMENT_TARGET=production \
      -e CODEMIT_OPERATOR_ORIGIN=https://operator.codemit.example \
      -e CODEMIT_API_BASE_URL=http://127.0.0.1:1 \
      "$local_image" >/dev/null
    ;;
  classroom)
    docker run -d --name "$box" \
      -e CODEMIT_DEPLOYMENT_TARGET=production \
      -e CODEMIT_CLASSROOM_ORIGIN=https://classroom.codemit.example \
      -e CODEMIT_API_BASE_URL=http://127.0.0.1:1 \
      -e CODEMIT_SESSION_COOKIE_DOMAIN=.codemit.example \
      -e CODEMIT_WEB_ORIGIN=https://codemit.example \
      "$local_image" >/dev/null
    ;;
esac

status="000"
for _ in $(seq 1 20); do
  status="$(c -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/healthz 2>/dev/null || true)"
  status="${status:-000}"
  [ "$status" = "000" ] || break
  sleep 1
done
echo "healthz status: $status"
if [ "$status" != "200" ] && [ "$status" != "503" ]; then
  docker logs "$box" || true
  fail "완전한 프로덕션 설정인데도 컨테이너가 응답하지 않는다(status=$status)"
fi

case "$app" in
  frontend)
    step "production 쿠키에 Secure 가 붙는다"
    set_cookie="$(c -s -D - -o /dev/null -X POST http://127.0.0.1:3000/api/auth/logout -H "Origin: https://codemit.example")"
    echo "$set_cookie"
    echo "$set_cookie" | grep -qi "codemit_access=.*Secure" || fail "production인데 codemit_access 쿠키에 Secure가 없다"
    echo "$set_cookie" | grep -qi "codemit_refresh=.*Secure" || fail "production인데 codemit_refresh 쿠키에 Secure가 없다"

    step "public/ 의 정적 자산이 서빙된다"
    asset="$(c -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/kakao/kakao_login_large_wide.png 2>/dev/null || true)"
    optimized="$(c -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:3000/_next/image?url=%2Fkakao%2Fkakao_login_large_wide.png&w=640&q=75" 2>/dev/null || true)"
    echo "public asset: ${asset:-000} / optimized: ${optimized:-000}"
    if [ "${asset:-000}" != "200" ] || [ "${optimized:-000}" != "200" ]; then
      docker logs "$box" || true
      fail "public/ 의 정적 자산이 프로덕션 이미지에서 서빙되지 않는다(원본=${asset:-000}, 최적화=${optimized:-000}) — Dockerfile 의 public 복사를 확인한다"
    fi

    step "방침이 실행 env 의 문의 주소를 싣는다"
    html="$(c -sS --max-time 10 http://127.0.0.1:3000/privacy)"
    case "$html" in
      *privacy-guard@codemit.example*) echo "방침이 실행 env 의 문의 주소를 싣는다" ;;
      *) printf '%s' "$html" | head -c 2000; fail "/privacy 에 문의 주소가 없다 — CODEMIT_PUBLIC_SUPPORT_EMAIL 을 실행 때 읽지 않는가?" ;;
    esac

    step "공개 설정이 브라우저로 가고 비밀은 가지 않는다"
    # /privacy 는 백엔드 없이 그려진다(이 가드의 API 주소는 닿지 않는 곳이다) — 첫 화면은 500 이라 못 쓴다.
    case "$html" in
      *'<script id="codemit-public-config">'*ci-guard-only-toss-client-key*) echo "토스 클라이언트 키가 window.__CODEMIT_PUBLIC__ 로 간다" ;;
      *) printf '%s' "$html" | head -c 2000; fail "HTML 의 공개 설정 스크립트에 토스 클라이언트 키가 없다 — 결제창이 키 없이 열린다" ;;
    esac
    case "$html" in
      *ci-guard-only-toss-secret-key*) fail "토스 시크릿 키가 HTML 에 실렸다 — lib/public-config.ts 의 목록을 확인한다" ;;
    esac
    ;;
  operator)
    step "production 쿠키에 Secure 가 붙는다"
    set_cookie="$(c -s -D - -o /dev/null -X POST http://127.0.0.1:3000/api/auth/logout -H "Origin: https://operator.codemit.example")"
    echo "$set_cookie"
    echo "$set_cookie" | grep -qi "codemit_operator_session=.*Secure" \
      || fail "production인데 codemit_operator_session 쿠키에 Secure가 없다"
    ;;
  classroom)
    step "런타임 설정을 요청 때 읽는다(빌드에 굳지 않는다)"
    html="$(c -sS --max-time 10 http://127.0.0.1:3000/login)"
    case "$html" in
      *"https://codemit.example/login"*) ;;
      *) printf '%s' "$html" | head -c 4000; fail "/login 이 CODEMIT_WEB_ORIGIN 을 안 읽는다 — 빌드 시점 값이 구워졌는가?" ;;
    esac
    case "$html" in
      *127.0.0.1*)
        printf '%s' "$html" | grep -o "http://127[^\"']*" | head -5 || true
        fail "/login HTML 에 로컬호스트가 남아 있다 — dev 폴백이 박제됐다(#297)"
        ;;
    esac
    echo "로그인 링크가 런타임 설정을 읽는다"
    ;;
esac

echo
echo "부팅 가드 통과: $app"
