#!/bin/sh
# staging / prod 배포 (#52).
#
# **Jenkins 잡이 부르는 진입점이다.** 잡은 freestyle 이고 셸 스텝이
# `sh ./deploy.sh staging` 하나뿐이다 — Jenkinsfile 을 읽지 않는다. 그래서
# 배포 논리는 파이프라인 DSL 이 아니라 이 파일에 산다. `Jenkinsfile` 은 같은
# 논리를 Pipeline 잡으로 돌리고 싶어질 때를 위해 남아 있다.
#
# **바뀐 것만 다시 굽고 바꿔 끼운다.** 그런데 「바뀐 것」과 「바꿔 끼울 것」이
# 1:1 이 아니다 — 그 어긋남이 이 파일의 대부분이다.
#
#   backend/             -> backend + celery-worker + celery-beat  (같은 Dockerfile, 이미지는 셋)
#   frontend/            -> frontend
#   operator/            -> operator
#   packages/bff-shared/ -> frontend + operator                    (둘이 함께 쓴다)
#   pnpm-lock.yaml       -> frontend + operator
#   docker/*.Dockerfile / compose.<target>.yaml -> 그 파일이 짓는 것 전부
#
# **`backend` 만 바꿔 끼우는 것은 사고다.** celery-worker 와 beat 가 옛 코드로
# 계속 돈다 — 그 둘이 마감 전이·채점·배분·지급을 실제로 진행시키는 주체다
# (ADR-0003). 새 코드가 만든 마이그레이션 위에서 옛 워커가 도는 상태가 되고,
# 그건 조용히 틀린다.
#
# 컨테이너가 없으면 변경 여부와 무관하게 굽는다 — 「없음」은 「최신」이 아니다.

set -eu

TARGET="${1:-staging}"
case "$TARGET" in
  staging) ;;
  prod|production) TARGET=prod ;;
  *) echo "알 수 없는 대상: $TARGET (staging|prod)"; exit 2 ;;
esac

cd "$(dirname "$0")"

COMPOSE_FILE="docker/compose.${TARGET}.yaml"
ENV_FILE="docker/.env.${TARGET}"
COMPOSE="docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE}"

# 「직전에 무엇을 배포했나」. `.env.<target>` 과 같은 자리에 둔다 — 빌드
# 디렉터리가 유지된다는 전제이고, 그 전제는 이미 시크릿이 쓰고 있다.
#
# git tag 로 두지 않는 이유: `git fetch --prune --tags` 나 강제 체크아웃이
# 조용히 옮기거나 지운다. 이 값이 틀리면 배포 범위가 통째로 어긋난다.
#
# 이 파일이 없어지면 전부 다시 굽는다 — 느릴 뿐 틀리지는 않는다.
DEPLOYED=".jenkins-${TARGET}-deployed"

# Jenkins 워크스페이스는 체크아웃 주체와 셸 실행 주체의 uid 가 다를 수 있다.
# 그때 git 이 "dubious ownership" 으로 멈추는데, 배포와 무관한 이유로 멈추는
# 것이므로 이 저장소만 예외로 둔다.
GIT="git -c safe.directory=$PWD"

log() { echo "[deploy:${TARGET}] $*"; }

# ---------------------------------------------------------------- Preflight

# 시크릿은 저장소에 없다(.gitignore) — 빌드 디렉터리에 사람이 한 번 두고,
# 체크아웃이 그것을 지우지 않는다는 전제다. 지워지는 설정(예: "Clean before
# checkout")으로 바뀌면 여기서 걸린다.
if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE 이 없다."
  echo "docker/${TARGET}.env.example 을 복사해 채운 뒤 빌드 디렉터리에 두고 chmod 600 해라."
  exit 1
fi

# compose 가 필수값을 전부 만족하는지 먼저 본다. 여기서 걸리는 것이 컨테이너를
# 굽고 나서 부팅에 실패하는 것보다 싸다.
$COMPOSE config >/dev/null
log "preflight OK"

# ------------------------------------------------------- 무엇이 바뀌었나

# 직전 성공 배포와 비교한다. 그것이 없으면(첫 배포·이력 유실) 전부 바뀐 것으로
# 본다 — 모르면 굽는 쪽이 안전하다.
#
# 표식이 가리키는 커밋이 이 저장소에 실제로 있는지까지 본다 — force-push 나
# 히스토리 재작성 뒤에는 남아 있는 SHA 가 `git diff` 에서 터진다. 그때는
# 「모른다」로 떨어져 전부 굽는 편이 맞다.
PREVIOUS=""
if [ -f "$DEPLOYED" ]; then
  sha=$(cat "$DEPLOYED")
  if $GIT cat-file -e "${sha}^{commit}" 2>/dev/null; then
    PREVIOUS="$sha"
  else
    log "배포 표식이 가리키는 커밋($sha)이 저장소에 없다 — 전부 다시 굽는다."
  fi
fi

CHANGED_FILE=$(mktemp)
BUILD_LOGS=$(mktemp -d)
cleanup() { rm -f "$CHANGED_FILE"; rm -rf "$BUILD_LOGS"; }
trap cleanup EXIT

EVERYTHING=false
if [ -n "$PREVIOUS" ]; then
  $GIT diff --name-only "$PREVIOUS" HEAD > "$CHANGED_FILE"
  log "직전 배포($(echo "$PREVIOUS" | cut -c1-12)) 이후 변경 $(wc -l < "$CHANGED_FILE" | tr -d ' ')개 파일"
else
  EVERYTHING=true
  log "직전 배포 표식이 없다 — 전부 다시 굽는다."
fi

# 변경 목록에 패턴과 맞는 줄이 있는가.
touched() {
  [ -s "$CHANGED_FILE" ] && grep -qE "$1" "$CHANGED_FILE"
}

BUILD_BACKEND=false
BUILD_FRONTEND=false
BUILD_OPERATOR=false

if [ "$EVERYTHING" = true ]; then
  BUILD_BACKEND=true
  BUILD_FRONTEND=true
  BUILD_OPERATOR=true
else
  # 한 경로가 여러 서비스를 건드린다. 그 팬아웃이 이 스크립트의 전부다.
  if touched '^(backend/|docker/backend\.Dockerfile$)'; then
    BUILD_BACKEND=true
  fi

  SHARED=false
  if touched '^(packages/bff-shared/|pnpm-lock\.yaml$|pnpm-workspace\.yaml$|package\.json$)'; then
    SHARED=true
  fi

  if [ "$SHARED" = true ] || touched '^(frontend/|docker/frontend\.Dockerfile$)'; then
    BUILD_FRONTEND=true
  fi
  if [ "$SHARED" = true ] || touched '^(operator/|docker/operator\.Dockerfile$)'; then
    BUILD_OPERATOR=true
  fi

  # compose 파일 자체가 바뀌면 어느 서비스의 환경이 바뀌었는지 알 수 없다.
  # 전부 다시 세운다.
  if touched "^docker/compose\.${TARGET}\.yaml\$"; then
    log "compose.${TARGET}.yaml 이 바뀌었다 — 전부 다시 세운다."
    BUILD_BACKEND=true
    BUILD_FRONTEND=true
    BUILD_OPERATOR=true
  fi
fi

# **없는 컨테이너는 변경 여부와 무관하게 굽는다.** 「없음」은 「최신」이 아니다.
# 크래시 루프 끝에 사라진 것도 여기 걸린다.
missing() {
  [ -z "$($COMPOSE ps -q "$1" 2>/dev/null | head -1)" ]
}

for svc in backend celery-worker celery-beat; do
  if missing "$svc"; then
    log "백엔드 계열 컨테이너 '$svc' 가 없다 — 굽는다."
    BUILD_BACKEND=true
    break
  fi
done
if missing frontend; then
  log "frontend 컨테이너가 없다 — 굽는다."
  BUILD_FRONTEND=true
fi
if missing operator; then
  log "operator 컨테이너가 없다 — 굽는다."
  BUILD_OPERATOR=true
fi

plan() {
  if [ "$1" = true ]; then echo "다시 굽는다"; else echo "건너뛴다"; fi
}
echo "계획"
echo "  backend(+celery-worker,+celery-beat) : $(plan "$BUILD_BACKEND")"
echo "  frontend                             : $(plan "$BUILD_FRONTEND")"
echo "  operator                             : $(plan "$BUILD_OPERATOR")"

if [ "$BUILD_BACKEND" = false ] && [ "$BUILD_FRONTEND" = false ] && [ "$BUILD_OPERATOR" = false ]; then
  log "바뀐 것이 없다. 배포할 것이 없다."
  $GIT rev-parse HEAD > "$DEPLOYED"
  exit 0
fi

# ------------------------------------------------------------------ 굽는다

# 셋을 동시에 굽는다 — 순차보다 빌드가 절반 가까이 짧다. 출력이 뒤섞이지
# 않도록 서비스별 로그로 받아 뒤에 순서대로 쏟는다.
PIDS=""
SERVICES=""

# 첫 인자는 로그 이름이고, 나머지가 실제로 구울 서비스들이다.
#
# **backend·celery-worker·beat 는 같은 이미지가 아니다.** 셋 다 같은
# Dockerfile 을 가리키지만 compose 파일 어디에도 공유 `image:` 태그가 없어서,
# compose 는 서비스 이름으로 이미지를 **셋** 만든다(laurio-staging-backend,
# -celery-worker, -celery-beat). 그래서 `build backend` 는 하나만 굽고 워커
# 둘은 옛 이미지에 남는다 — 뒤의 `up -d` 도 바뀐 게 없으니 그냥 Running 이라
# 적고 지나간다. 배포는 초록으로 끝나는데 스캔만 옛 코드로 돈다.
# 실제로 그렇게 한 번 나갔다(빌드 23). 같은 레이어를 쓰므로 둘째·셋째는
# 캐시에 맞아 거의 시간이 들지 않는다.
#
# NEXT_PUBLIC_* 는 빌드타임에 인라인된다 — build args 는 compose 가
# .env.<target> 에서 읽어 넘긴다(#85). 여기서 따로 줄 것이 없다.
start_build() {
  label="$1"
  shift
  $COMPOSE build "$@" > "${BUILD_LOGS}/${label}.log" 2>&1 &
  PIDS="$PIDS $!:$label"
  SERVICES="$SERVICES $label"
  log "$label 빌드 시작"
}

if [ "$BUILD_BACKEND" = true ]; then start_build backend backend celery-worker celery-beat; fi
if [ "$BUILD_FRONTEND" = true ]; then start_build frontend frontend; fi
if [ "$BUILD_OPERATOR" = true ]; then start_build operator operator; fi

BUILD_FAILED=""
for entry in $PIDS; do
  pid="${entry%%:*}"
  svc="${entry##*:}"
  if wait "$pid"; then
    :
  else
    BUILD_FAILED="$BUILD_FAILED $svc"
  fi
done

for svc in $SERVICES; do
  echo "----- build: $svc -----"
  # 성공한 빌드는 꼬리만, 실패한 빌드는 전부 남긴다 — 원인이 로그 위쪽에 있다.
  case " $BUILD_FAILED " in
    *" $svc "*) cat "${BUILD_LOGS}/${svc}.log" ;;
    *)          tail -30 "${BUILD_LOGS}/${svc}.log" ;;
  esac
done

if [ -n "$BUILD_FAILED" ]; then
  echo "빌드 실패:$BUILD_FAILED — 배포 표식은 옮기지 않았다."
  exit 1
fi

# ------------------------------------------------------------ 바꿔 끼운다

# 인프라는 항상 떠 있어야 한다(idempotent — 이미 떠 있으면 아무 일도 일어나지
# 않는다).
$COMPOSE up -d db redis

if [ "$BUILD_BACKEND" = true ]; then
  # **셋을 함께 바꾼다.** backend 만 갈면 워커·beat 가 옛 코드로 남는데, 그
  # 둘이 스캔으로 상태를 진행시키는 주체다.
  #
  # backend 의 command 가 migrate 를 먼저 돌리므로, 워커·beat 는 그 뒤에
  # 올린다 — 새 마이그레이션이 필요한 코드가 아직 없는 스키마 위에서 스캔을
  # 돌리는 창을 만들지 않는다.
  $COMPOSE up -d --no-deps backend
  $COMPOSE up -d --no-deps celery-worker celery-beat
fi
if [ "$BUILD_FRONTEND" = true ]; then $COMPOSE up -d --no-deps frontend; fi
if [ "$BUILD_OPERATOR" = true ]; then $COMPOSE up -d --no-deps operator; fi

# ------------------------------------------------------- 떴는지 확인한다

# 부팅 거부는 이 저장소가 **의도한** 동작이다(#83, #96) — 어댑터 값이나 OAuth
# 자격증명이 풀리지 않으면 컨테이너가 뜨지 않는다. 그러니 "떴다"를 실제로
# 확인해야 하고, 죽었으면 로그를 남겨야 원인을 안다.
for svc in backend celery-worker celery-beat frontend operator; do
  cid=$($COMPOSE ps -q "$svc" 2>/dev/null | head -1)
  if [ -z "$cid" ]; then
    echo "[$svc] 컨테이너가 없다"
    continue
  fi
  state=$(docker inspect -f '{{.State.Status}}' "$cid")
  if [ "$state" != "running" ]; then
    echo "[$svc] 상태가 running 이 아니다: $state"
    $COMPOSE logs --tail 80 "$svc" || true
    exit 1
  fi
done

# 백엔드가 요청을 실제로 받는지 본다. 컨테이너가 running 인 것과 gunicorn 이
# 응답하는 것은 다르다.
#
# **Host 헤더를 붙여야 한다.** 루프백으로 치면 Host 가 `127.0.0.1` 이 되는데 그건
# ALLOWED_HOSTS 에 없으므로 Django 가 400 을 낸다 — gunicorn 이 멀쩡히 떠 있어도
# 배포가 실패한 것처럼 보인다(빌드 #5 가 실제로 그렇게 실패했다). 하드코딩 대신
# ALLOWED_HOSTS 의 첫 항목을 쓴다 — 환경마다 다르고, 그 값이 곧 「이 배포가
# 받아들이는 이름」이다.
HEALTHY=false
i=0
while [ "$i" -lt 30 ]; do
  if $COMPOSE exec -T backend python -c "import os,urllib.request,sys; host=(os.environ.get('DJANGO_ALLOWED_HOSTS') or '').split(',')[0].strip() or '127.0.0.1'; req=urllib.request.Request('http://127.0.0.1:8000/api/health', headers={'Host': host}); sys.exit(0 if urllib.request.urlopen(req, timeout=3).status==200 else 1)" 2>/dev/null; then
    HEALTHY=true
    break
  fi
  i=$((i + 1))
  sleep 5
done

if [ "$HEALTHY" != true ]; then
  echo "backend 가 150초 안에 응답하지 않았다"
  $COMPOSE logs --tail 120 backend || true
  exit 1
fi
log "backend 응답 확인"

# --------------------------------------------------- 배포 표식을 옮긴다

# 다음 빌드의 「직전 배포」 기준점. **확인이 끝난 뒤에만** 옮긴다 — 실패한
# 배포를 기준으로 삼으면 그 사이 변경이 다음 빌드에서 통째로 누락된다.
$GIT rev-parse HEAD > "$DEPLOYED"
log "배포 표식: $(cat "$DEPLOYED")"
