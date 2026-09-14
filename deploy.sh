#!/bin/sh
# staging / prod 배포 (#52).
#
#   sh ./deploy.sh <staging|prod> [명령] [인자]
#
# **명령을 하나씩 부를 수 있다 — Jenkins 파이프라인이 단계마다 하나씩 부른다.**
# `Jenkinsfile`(staging)·`Jenkinsfile.production`(prod)이 「대상 확인 → preflight →
# 변경 계획 → 빌드(서비스별 병렬) → 교체 → 확인 → 배포 표식」을 각각 한 단계로
# 보여주고, 각 단계의 본문은 여기 명령 한 줄이다. 예전에는 파이프라인이 이 파일을
# 통째로 한 번 불러 Jenkins 화면에 「배포」 단계 하나만 보였고, 네 이미지의 빌드
# 로그가 한 덩어리로 쏟아져 실패 원인 줄을 찾기 어려웠다(2026-09-14 prod 빌드
# #4~#6 — 에이전트에 buildx 가 없어 네 빌드가 전부 같은 줄에서 죽었다).
#
#   preflight           env 파일과 compose 설정을 확인한다
#   plan                무엇을 다시 굽는지 정해 계획 파일(.jenkins-<대상>-plan)에 적는다
#   build <서비스>       backend|frontend|operator|classroom 하나를 굽는다
#   up                  계획대로 인프라를 세우고 새 이미지로 바꿔 끼운다
#   verify              컨테이너가 running 인지 본다
#   health <서비스>      backend|events 가 요청을 실제로 받는지 본다
#   mark                배포 표식을 지금 커밋으로 옮긴다
#   all (기본값)         위를 순서대로 전부 — 사람이 손으로 배포할 때
#
# **논리는 여전히 이 파일에 산다.** 파이프라인에 논리를 두면 아무도 읽지 않는 두 번째
# 사본이 되고, 실제로 그렇게 한 번 어긋나 배포가 통째로 실패했다(staging 빌드 #4:
# `cannot open ./deploy.sh`). 단계는 명령을 부르기만 한다.
#
# **바뀐 것만 다시 굽고 바꿔 끼운다.** 그런데 「바뀐 것」과 「바꿔 끼울 것」이
# 1:1 이 아니다 — 그 어긋남이 이 파일의 대부분이다.
#
#   backend/             -> backend + celery-worker + celery-beat + events (같은
#                                                                    Dockerfile, 이미지는 넷 —
#                                                                    events 는 ASGI 로 강의실
#                                                                    실시간 신호만 여는 별도
#                                                                    프로세스다, ADR-0046, #380)
#   frontend/            -> frontend
#   operator/            -> operator
#   classroom/           -> classroom                              (#276/#277, ADR-0037)
#   packages/            -> frontend + operator + classroom        (워크스페이스 패키지를 함께 쓴다)
#   pnpm-lock.yaml       -> frontend + operator + classroom
#   docker/*.Dockerfile / compose.<target>.yaml -> 그 파일이 짓는 것 전부
#
# **`backend` 만 바꿔 끼우는 것은 사고다.** celery-worker 와 beat 가 옛 코드로
# 계속 돈다 — 그 둘이 마감 전이·채점·배분·지급을 실제로 진행시키는 주체다
# (ADR-0003). events 도 같은 이유로 함께 간다 — 옛 코드가 URLconf 를 바꾼
# 최신 backend 와 다른 스키마·응답 모양을 돌려주면 강의실 스트림만 조용히
# 어긋난다. 새 코드가 만든 마이그레이션 위에서 옛 워커가 도는 상태가 되고,
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
COMMAND="${2:-all}"
ARG="${3:-}"

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

# `plan` 이 정한 것을 뒤 명령(`build`·`up`)과 파이프라인 단계가 읽는 자리.
# 단계마다 셸이 새로 뜨므로 변수로는 넘길 수 없다. 표식과 같은 자리에 두고
# gitignore 한다.
PLAN_FILE=".jenkins-${TARGET}-plan"

# Jenkins 워크스페이스는 체크아웃 주체와 셸 실행 주체의 uid 가 다를 수 있다.
# 그때 git 이 "dubious ownership" 으로 멈추는데, 배포와 무관한 이유로 멈추는
# 것이므로 이 저장소만 예외로 둔다.
GIT="git -c safe.directory=$PWD"

log() { echo "[deploy:${TARGET}] $*"; }

# 서비스 이름 → compose 서비스들. backend 는 넷을 함께 굽는다(아래 build 의 주석).
compose_services() {
  case "$1" in
    backend) echo "backend celery-worker celery-beat events" ;;
    frontend|operator|classroom) echo "$1" ;;
    *) echo "알 수 없는 빌드 대상: $1 (backend|frontend|operator|classroom)" >&2; return 2 ;;
  esac
}

# ---------------------------------------------------------------- preflight

cmd_preflight() {
  # 시크릿은 저장소에 없다(.gitignore) — 빌드 디렉터리에 사람이 한 번 두고,
  # 체크아웃이 그것을 지우지 않는다는 전제다. 지워지는 설정(예: "Clean before
  # checkout")으로 바뀌면 여기서 걸린다.
  if [ ! -f "$ENV_FILE" ]; then
    echo "$ENV_FILE 이 없다."
    echo "docker/${TARGET}.env.example 을 복사해 채운 뒤 빌드 디렉터리에 두고 chmod 600 해라."
    exit 1
  fi

  # **이미지를 굽는 데 buildx 가 있어야 한다.** 저장소 Dockerfile 이
  # `RUN --mount=type=cache`(BuildKit 전용)를 쓰는데, buildx 플러그인이 없으면
  # compose 가 경고 한 줄만 남기고 옛 빌더로 물러나 그 줄에서 죽는다 — 원인이
  # 빌드 로그 한가운데 묻혀 네 서비스가 전부 같은 이유로 실패한 것처럼 보인다.
  # prod 에이전트(Oracle 호스트의 jenkins-desktop-agent)가 실제로 그랬다
  # (2026-09-14 빌드 #4~#6). 굽기 전에 이유를 한 줄로 말하고 멈춘다.
  if ! docker buildx version >/dev/null 2>&1; then
    echo "이 에이전트의 docker CLI 에 buildx 플러그인이 없다."
    echo "Dockerfile 의 RUN --mount(BuildKit 전용)를 구울 수 없다 — 에이전트 이미지에 docker-buildx 를 넣어라."
    exit 1
  fi

  # compose 가 필수값을 전부 만족하는지 먼저 본다. 여기서 걸리는 것이 컨테이너를
  # 굽고 나서 부팅에 실패하는 것보다 싸다.
  $COMPOSE config >/dev/null
  log "preflight OK"
}

# ------------------------------------------------------- 무엇이 바뀌었나

cmd_plan() {
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
  trap 'rm -f "$CHANGED_FILE"' EXIT

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
  BUILD_CLASSROOM=false

  if [ "$EVERYTHING" = true ]; then
    BUILD_BACKEND=true
    BUILD_FRONTEND=true
    BUILD_OPERATOR=true
    BUILD_CLASSROOM=true
  else
    # 한 경로가 여러 서비스를 건드린다. 그 팬아웃이 이 스크립트의 전부다.
    if touched '^(backend/|docker/backend\.Dockerfile$)'; then
      BUILD_BACKEND=true
    fi

    SHARED=false
    if touched '^(packages/|pnpm-lock\.yaml$|pnpm-workspace\.yaml$|package\.json$)'; then
      SHARED=true
    fi

    if [ "$SHARED" = true ] || touched '^(frontend/|docker/frontend\.Dockerfile$)'; then
      BUILD_FRONTEND=true
    fi
    if [ "$SHARED" = true ] || touched '^(operator/|docker/operator\.Dockerfile$)'; then
      BUILD_OPERATOR=true
    fi
    if [ "$SHARED" = true ] || touched '^(classroom/|docker/classroom\.Dockerfile$)'; then
      BUILD_CLASSROOM=true
    fi

    # compose 파일 자체가 바뀌면 어느 서비스의 환경이 바뀌었는지 알 수 없다.
    # 전부 다시 세운다.
    if touched "^docker/compose\.${TARGET}\.yaml\$"; then
      log "compose.${TARGET}.yaml 이 바뀌었다 — 전부 다시 세운다."
      BUILD_BACKEND=true
      BUILD_FRONTEND=true
      BUILD_OPERATOR=true
      BUILD_CLASSROOM=true
    fi
  fi

  # **없는 컨테이너는 변경 여부와 무관하게 굽는다.** 「없음」은 「최신」이 아니다.
  # 크래시 루프 끝에 사라진 것도 여기 걸린다.
  missing() {
    [ -z "$($COMPOSE ps -q "$1" 2>/dev/null | head -1)" ]
  }

  for svc in backend celery-worker celery-beat events; do
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
  if missing classroom; then
    log "classroom 컨테이너가 없다 — 굽는다."
    BUILD_CLASSROOM=true
  fi

  # NEXT_PUBLIC_TOSS_CLIENT_KEY 회전 감지 (#112 코드리뷰 지적 3). 이 값은
  # 빌드타임에만 굳는다 — .env.<target>은 gitignore라 위 git diff 기반 변경
  # 감지는 이 값이 바뀐 것을 절대 보지 못한다. #115의 부팅 가드는 값이 "비어
  # 있으면" 부팅을 거부하지만, 있던 값을 다른 값으로 돌린(rotate) 경우는
  # 여전히 통과한다 — 이미 뜬 컨테이너는 예전 키를 문 채로 계속 돈다. 그래서
  # 이미 뜬 frontend 컨테이너가 실제로 구운 값(docker/frontend.Dockerfile의
  # runner 스테이지가 ENV로 남긴다)과, 지금 env 파일이 주는 값을 직접
  # 비교한다 — 다르면 다시 굽는다. 컨테이너가 없으면(missing) 위에서 이미
  # BUILD_FRONTEND=true다.
  if [ "$BUILD_FRONTEND" = false ] && ! missing frontend; then
    case "$TARGET" in
      staging) TOSS_KEY_VAR=TOSS_SANDBOX_CLIENT_KEY ;;
      prod) TOSS_KEY_VAR=TOSS_LIVE_CLIENT_KEY ;;
    esac
    CURRENT_TOSS_KEY=$(grep -E "^${TOSS_KEY_VAR}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)
    FRONTEND_CID=$($COMPOSE ps -q frontend 2>/dev/null | head -1)
    BAKED_TOSS_KEY=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$FRONTEND_CID" 2>/dev/null \
      | grep '^NEXT_PUBLIC_TOSS_CLIENT_KEY=' | cut -d= -f2-)
    if [ "$BAKED_TOSS_KEY" != "$CURRENT_TOSS_KEY" ]; then
      log "NEXT_PUBLIC_TOSS_CLIENT_KEY 가 .env.${TARGET} 과 어긋난다(떠 있는 컨테이너가 구운 값과 다르다) — frontend 를 다시 굽는다."
      BUILD_FRONTEND=true
    fi
  fi

  ANY=false
  if [ "$BUILD_BACKEND" = true ] || [ "$BUILD_FRONTEND" = true ] || [ "$BUILD_OPERATOR" = true ] || [ "$BUILD_CLASSROOM" = true ]; then
    ANY=true
  fi

  # 파이프라인은 이 파일을 `KEY=value` 줄로 읽어 단계의 `when` 을 정한다 — 모양을
  # 바꾸면 두 Jenkinsfile 을 같이 고친다.
  {
    echo "DEPLOY_ANY=$ANY"
    echo "BUILD_BACKEND=$BUILD_BACKEND"
    echo "BUILD_FRONTEND=$BUILD_FRONTEND"
    echo "BUILD_OPERATOR=$BUILD_OPERATOR"
    echo "BUILD_CLASSROOM=$BUILD_CLASSROOM"
    echo "PLANNED_COMMIT=$($GIT rev-parse HEAD)"
  } > "$PLAN_FILE"

  plan_word() {
    if [ "$1" = true ]; then echo "다시 굽는다"; else echo "건너뛴다"; fi
  }
  echo "계획"
  echo "  backend(+celery-worker,+celery-beat,+events) : $(plan_word "$BUILD_BACKEND")"
  echo "  frontend                                      : $(plan_word "$BUILD_FRONTEND")"
  echo "  operator                                      : $(plan_word "$BUILD_OPERATOR")"
  echo "  classroom                                     : $(plan_word "$BUILD_CLASSROOM")"
  if [ "$ANY" = false ]; then
    log "바뀐 것이 없다. 배포할 것이 없다."
  fi
}

# 계획 파일을 읽는다. 없거나 다른 커밋의 계획이면 멈춘다 — 옛 계획으로 굽고
# 바꿔 끼우면 범위가 조용히 어긋난다.
load_plan() {
  if [ ! -f "$PLAN_FILE" ]; then
    echo "계획 파일($PLAN_FILE)이 없다 — 먼저 'plan' 을 돌린다."
    exit 1
  fi
  # shellcheck disable=SC1090
  . "./$PLAN_FILE"
  head=$($GIT rev-parse HEAD)
  if [ "$PLANNED_COMMIT" != "$head" ]; then
    echo "계획 파일이 다른 커밋($PLANNED_COMMIT)의 것이다 — 지금은 $head. 'plan' 을 다시 돌린다."
    exit 1
  fi
}

# ------------------------------------------------------------------ 굽는다

# **backend·celery-worker·beat·events 는 같은 이미지가 아니다.** 넷 다 같은
# Dockerfile 을 가리키지만 compose 파일 어디에도 공유 `image:` 태그가 없어서,
# compose 는 서비스 이름으로 이미지를 **넷** 만든다(codemit-staging-backend,
# -celery-worker, -celery-beat, -events, #380). 그래서 `build backend` 는
# 하나만 굽고 나머지 셋은 옛 이미지에 남는다 — 뒤의 `up -d` 도 바뀐 게 없으니
# 그냥 Running 이라 적고 지나간다. 배포는 초록으로 끝나는데 스캔·강의실
# 스트림만 옛 코드로 돈다. 실제로 그렇게 한 번 나갔다(빌드 23, 그때는
# celery-worker/beat 둘뿐이었다). 같은 레이어를 쓰므로 둘째부터는 캐시에
# 맞아 거의 시간이 들지 않는다.
#
# NEXT_PUBLIC_* 는 빌드타임에 인라인된다 — build args 는 compose 가
# .env.<target> 에서 읽어 넘긴다(#85). 여기서 따로 줄 것이 없다.
cmd_build() {
  services=$(compose_services "$1")
  log "$1 빌드 ($services)"
  # shellcheck disable=SC2086
  $COMPOSE build $services
}

# 사람이 `all` 로 돌릴 때는 계획된 것을 동시에 굽는다 — 순차보다 빌드가 절반
# 가까이 짧다. 출력이 뒤섞이지 않도록 서비스별 로그로 받아 뒤에 순서대로 쏟는다.
# (파이프라인은 이 대신 서비스마다 병렬 단계를 두고 `build <서비스>` 를 부른다.)
build_planned_in_background() {
  BUILD_LOGS=$(mktemp -d)
  PIDS=""
  LABELS=""
  for label in backend frontend operator classroom; do
    case "$label" in
      backend) wanted=$BUILD_BACKEND ;;
      frontend) wanted=$BUILD_FRONTEND ;;
      operator) wanted=$BUILD_OPERATOR ;;
      classroom) wanted=$BUILD_CLASSROOM ;;
    esac
    [ "$wanted" = true ] || continue
    cmd_build "$label" > "${BUILD_LOGS}/${label}.log" 2>&1 &
    PIDS="$PIDS $!:$label"
    LABELS="$LABELS $label"
    log "$label 빌드 시작"
  done

  FAILED=""
  for entry in $PIDS; do
    if ! wait "${entry%%:*}"; then
      FAILED="$FAILED ${entry##*:}"
    fi
  done

  for label in $LABELS; do
    echo "----- build: $label -----"
    # 성공한 빌드는 꼬리만, 실패한 빌드는 전부 남긴다 — 원인이 로그 위쪽에 있다.
    case " $FAILED " in
      *" $label "*) cat "${BUILD_LOGS}/${label}.log" ;;
      *)            tail -30 "${BUILD_LOGS}/${label}.log" ;;
    esac
  done
  rm -rf "$BUILD_LOGS"

  if [ -n "$FAILED" ]; then
    echo "빌드 실패:$FAILED — 배포 표식은 옮기지 않았다."
    exit 1
  fi
}

# ------------------------------------------------------------ 바꿔 끼운다

cmd_up() {
  load_plan
  if [ "$DEPLOY_ANY" != true ]; then
    log "계획에 바꿔 끼울 것이 없다."
    return 0
  fi

  # 인프라는 항상 떠 있어야 한다(idempotent — 이미 떠 있으면 아무 일도 일어나지
  # 않는다).
  $COMPOSE up -d db redis

  if [ "$BUILD_BACKEND" = true ]; then
    # **넷을 함께 바꾼다.** backend 만 갈면 워커·beat·events 가 옛 코드로
    # 남는다 — 앞의 둘은 스캔으로 상태를 진행시키는 주체고, events 는 강의실
    # 실시간 신호를 여는 주체다(ADR-0046, #380).
    #
    # backend 의 command 가 migrate 를 먼저 돌리므로, 나머지 셋은 그 뒤에
    # 올린다 — 새 마이그레이션이 필요한 코드가 아직 없는 스키마 위에서 스캔·
    # 스트림을 돌리는 창을 만들지 않는다.
    $COMPOSE up -d --no-deps backend
    $COMPOSE up -d --no-deps celery-worker celery-beat events
  fi
  if [ "$BUILD_FRONTEND" = true ]; then $COMPOSE up -d --no-deps frontend; fi
  if [ "$BUILD_OPERATOR" = true ]; then $COMPOSE up -d --no-deps operator; fi
  if [ "$BUILD_CLASSROOM" = true ]; then $COMPOSE up -d --no-deps classroom; fi
  log "바꿔 끼웠다"
}

# ------------------------------------------------------- 떴는지 확인한다

cmd_verify() {
  # 부팅 거부는 이 저장소가 **의도한** 동작이다(#83, #96) — 어댑터 값이나 OAuth
  # 자격증명이 풀리지 않으면 컨테이너가 뜨지 않는다. 그러니 "떴다"를 실제로
  # 확인해야 하고, 죽었으면 로그를 남겨야 원인을 안다.
  for svc in backend celery-worker celery-beat events frontend operator classroom; do
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
  log "컨테이너 전부 running"
}

# 서비스가 요청을 실제로 받는지 본다. 컨테이너가 running 인 것과 서버가
# 응답하는 것은 다르다.
#
# **Host 헤더를 붙여야 한다.** 루프백으로 치면 Host 가 `127.0.0.1` 이 되는데 그건
# ALLOWED_HOSTS 에 없으므로 Django 가 400 을 낸다 — gunicorn 이 멀쩡히 떠 있어도
# 배포가 실패한 것처럼 보인다(빌드 #5 가 실제로 그렇게 실패했다). 하드코딩 대신
# ALLOWED_HOSTS 의 첫 항목을 쓴다 — 환경마다 다르고, 그 값이 곧 「이 배포가
# 받아들이는 이름」이다.
#
# **`X-Forwarded-Proto: https` 도 붙인다.** prod 는 `SECURE_SSL_REDIRECT` 가 켜져 있어
# 루프백 평문 요청에 301(https 로)을 돌려준다 — 앞단 TLS 프록시를 거친 요청이 아니기
# 때문이다. 헬스 체크는 그 프록시를 거친 요청처럼 보여야 한다. prod 첫 배포(Oracle
# 빌드 #8)가 gunicorn 이 멀쩡히 뜬 채 「150초 안에 응답하지 않았다」로 실패했다
# (같은 요청에 이 헤더를 붙이면 200 이었다). staging 은 리다이렉트가 없어 무해하다.
#
# events 도 같은 식으로 확인한다(ADR-0046, #380) — URLconf 는 backend 와 완전히
# 같은 코드이므로 `/api/health` 가 여기서도 그대로 선다(CLAUDE.md). 인증이 필요한
# SSE 엔드포인트 자체를 열어 보지는 않는다 — 프로세스가 요청을 받는지만 본다.
cmd_health() {
  case "$1" in
    backend) port=8000 ;;
    events) port=8001 ;;
    *) echo "알 수 없는 헬스 체크 대상: $1 (backend|events)"; exit 2 ;;
  esac
  i=0
  while [ "$i" -lt 30 ]; do
    if $COMPOSE exec -T "$1" python -c "import os,urllib.request,sys; host=(os.environ.get('DJANGO_ALLOWED_HOSTS') or '').split(',')[0].strip() or '127.0.0.1'; req=urllib.request.Request('http://127.0.0.1:${port}/api/health', headers={'Host': host, 'X-Forwarded-Proto': 'https'}); sys.exit(0 if urllib.request.urlopen(req, timeout=3).status==200 else 1)" 2>/dev/null; then
      log "$1 응답 확인"
      return 0
    fi
    i=$((i + 1))
    sleep 5
  done
  echo "$1 가 150초 안에 응답하지 않았다"
  $COMPOSE logs --tail 120 "$1" || true
  exit 1
}

# --------------------------------------------------- 배포 표식을 옮긴다

cmd_mark() {
  # 다음 빌드의 「직전 배포」 기준점. **확인이 끝난 뒤에만** 옮긴다 — 실패한
  # 배포를 기준으로 삼으면 그 사이 변경이 다음 빌드에서 통째로 누락된다.
  # 파이프라인에서는 앞 단계가 하나라도 실패하면 이 단계에 닿지 않는다.
  $GIT rev-parse HEAD > "$DEPLOYED"
  rm -f "$PLAN_FILE"
  log "배포 표식: $(cat "$DEPLOYED")"
}

# ------------------------------------------------------------------ 진입점

case "$COMMAND" in
  preflight) cmd_preflight ;;
  plan) cmd_plan ;;
  build)
    [ -n "$ARG" ] || { echo "build 에는 서비스가 필요하다 (backend|frontend|operator|classroom)"; exit 2; }
    compose_services "$ARG" >/dev/null
    cmd_build "$ARG"
    ;;
  up) cmd_up ;;
  verify) cmd_verify ;;
  health)
    [ -n "$ARG" ] || { echo "health 에는 서비스가 필요하다 (backend|events)"; exit 2; }
    cmd_health "$ARG"
    ;;
  mark) cmd_mark ;;
  all)
    cmd_preflight
    cmd_plan
    load_plan
    if [ "$DEPLOY_ANY" = true ]; then
      build_planned_in_background
      cmd_up
      cmd_verify
      cmd_health backend
      cmd_health events
    fi
    cmd_mark
    ;;
  *)
    echo "알 수 없는 명령: $COMMAND (preflight|plan|build|up|verify|health|mark|all)"
    exit 2
    ;;
esac
