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
#   plan                무엇을 바꿔 끼울지 정해 계획 파일(.jenkins-<대상>-plan)에 적는다
#   image <서비스>       backend|frontend|operator|classroom|search|pgbouncer 하나의 이미지를 준비한다
#                       (아래 이미지 출처에 따라 pull 또는 build)
#   pull <서비스>        ghcr 에서 그 커밋의 이미지를 받는다
#   build <서비스>       이 호스트에서 직접 굽는다(비상용)
#   up                  계획대로 인프라를 세우고 새 이미지로 바꿔 끼운다
#   verify              컨테이너가 running 인지 본다
#   health <서비스>      backend|events|search|pgbouncer 가 요청을 실제로 받는지 본다
#   reindex             공모전 검색을 전체 재색인한다(검색·backend 를 바꾼 뒤)
#   mark                배포 표식을 지금 커밋으로 옮긴다
#   all (기본값)         위를 순서대로 전부 — 사람이 손으로 배포할 때
#
# **이미지는 CI 가 굽고, 여기서는 받는다**(2026-09-17). main 에 push 하면 Jenkins `laurio` 잡의
# 앞 단계가 커밋마다 여섯 이미지를 ghcr 에 올린다(scripts/ci/images.sh — amd64 는 sub, arm64 는
# macos 가 굽고, 바뀌지 않은 서비스는 옛 이미지에 커밋 태그만 더한다, #705) — backend·
# search·pgbouncer 와 세 앱 모두 `<sha>-amd64`(staging)·`<sha>-arm64`(prod) 다 — 앱도 환경을
# 모르고 공개 값은 실행 env 로 받는다(#711, ADR-0062). compose 파일의 `image:` 가 그 이름을 가리키고, 태그의
# <sha> 는 여기서 체크아웃한 커밋이다(`CODEMIT_IMAGE_TAG`). 그래서 배포 단계는 굽지 않고, prod 는
# oracle 이 더 이상 굽지 않는다 — oracle 은 prod 서버라 빌드가 서비스 속도를 갉아먹었다.
#
# 이미지 출처는 `DEPLOY_IMAGE_SOURCE` 가 고른다: `registry`(기본값, 파이프라인) 또는
# `build`(CI·ghcr 가 막혔을 때 사람이 손으로 — 예전 방식 그대로 이 호스트에서 굽는다).
# registry 는 이 에이전트에 **미리 저장해 둔 ghcr 로그인**(read:packages PAT)을 쓴다 —
# 두 에이전트 컨테이너(sub 의 jenkins, oracle 의 jenkins-desktop-agent) 모두 /root/.docker 가
# named volume 이라 컨테이너를 다시 만들어도 남는다(oracle 은 2026-09-17 에 붙였다).
# 로그인은 scripts/ghcr-setup-wizard.sh 가 한 번 해 둔다. 토큰은 저장소에도 env 에도 없다.
#
# **논리는 여전히 이 파일에 산다.** 파이프라인에 논리를 두면 아무도 읽지 않는 두 번째
# 사본이 되고, 실제로 그렇게 한 번 어긋나 배포가 통째로 실패했다(staging 빌드 #4:
# `cannot open ./deploy.sh`). 단계는 명령을 부르기만 한다.
#
# **바뀐 것만 바꿔 끼운다.** 이미지 태그가 커밋마다 달라지므로 계획 없이 `up` 하면
# 바뀌지 않은 서비스까지 전부 다시 뜬다. 그런데 「바뀐 것」과 「바꿔 끼울 것」이
# 1:1 이 아니다 — 그 어긋남이 이 파일의 대부분이다.
#
#   backend/             -> backend + celery-worker + celery-beat + events + grader
#                                                                   (이미지 하나 — events 는 ASGI 로
#                                                                    강의실 실시간 신호만 여는 별도
#                                                                    프로세스다, ADR-0046, #380;
#                                                                    grader 는 강의실 채점
#                                                                    상주 프로세스다, ADR-0059,
#                                                                    #584)
#   frontend/            -> frontend
#   operator/            -> operator
#   classroom/           -> classroom                              (#276/#277, ADR-0037)
#   packages/            -> frontend + operator + classroom        (워크스페이스 패키지를 함께 쓴다)
#   pnpm-lock.yaml       -> frontend + operator + classroom
#   docker/search.Dockerfile -> search                              (#450/#451, 부모 #444 스펙 —
#                                                                    nori 플러그인을 넣은 OpenSearch,
#                                                                    backend 코드와 무관하게 갈린다)
#   docker/pgbouncer.Dockerfile, docker/pgbouncer/ -> pgbouncer      (#453/#458 — 연결 풀러
#                                                                    이미지 자체만 바뀐다)
#   docker/*.Dockerfile / compose.<target>.yaml -> 그 파일이 짓는 것 전부
#
# **검색이나 backend 를 바꾼 뒤에는 전체 재색인을 한 번 돌린다**(부모 #444 스펙) —
# `reindex` 명령이 `manage.py rebuild_contest_search_index`를 부른다. 스캔
# 등록부의 `contest-search-reindex`는 하루에 한 번만 실제로 도는 안전망이라
# (`contests/search_scan.py`) 배포 직후에는 이 즉시 명령으로 따로 맞춘다.
#
# **`backend` 만 바꿔 끼우는 것은 사고다.** celery-worker 와 beat 가 옛 코드로
# 계속 돈다 — 그 둘이 마감 전이·채점·배분·지급을 실제로 진행시키는 주체다
# (ADR-0003). events 도 같은 이유로 함께 간다 — 옛 코드가 URLconf 를 바꾼
# 최신 backend 와 다른 스키마·응답 모양을 돌려주면 강의실 스트림만 조용히
# 어긋난다. 새 코드가 만든 마이그레이션 위에서 옛 워커가 도는 상태가 되고,
# 그건 조용히 틀린다.
#
# **pgbouncer(연결 풀러, #453/#458)는 search 와 반대로 필수 경로다.** search 가
# 죽어도 backend 넷은 뜨고(DB 검색으로 물러난다), pgbouncer 가 죽으면 그 넷은
# 애초에 DB(정확히는 풀러)에 붙지 못해 뜨지 않는다 — 그래서 backend 넷의
# `depends_on` 은 pgbouncer 를 `db` 와 같은 `service_healthy` 로 기다린다(search 는
# `service_started` 뿐이다). 되돌리는 법: 네 프로세스의 `POSTGRES_HOST` 를 다시
# `db` 로 돌리면(그리고 `CODEMIT_DB_DISABLE_SERVER_SIDE_CURSORS` 를 `false` 로)
# 앱이 DB 를 직접 가리키던 이전 상태로 즉시 돌아간다 — 풀러 컨테이너 자체를
# 지울 필요는 없다.
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

# 오류가 어느 커밋에서 났는지 — 오류 수집기(GlitchTip)의 release 태그가 된다
# (2026-09-16). compose 가 backend 의 환경변수와 세 앱의 빌드 인자로 함께 넘긴다.
# 여기서 정하는 이유: 굽는 커밋과 표시되는 커밋이 언제나 같아야 한다.
SENTRY_RELEASE="$(git -c safe.directory="$PWD" rev-parse HEAD 2>/dev/null || echo unknown)"
export SENTRY_RELEASE

# compose 의 `image:` 태그 — CI 가 이 커밋으로 올린 이미지를 가리킨다.
CODEMIT_IMAGE_TAG="$SENTRY_RELEASE"
export CODEMIT_IMAGE_TAG

IMAGE_SOURCE="${DEPLOY_IMAGE_SOURCE:-registry}"
case "$IMAGE_SOURCE" in
  registry|build) ;;
  *) echo "알 수 없는 DEPLOY_IMAGE_SOURCE: $IMAGE_SOURCE (registry|build)"; exit 2 ;;
esac
# registry 에서 받을 때는 절대 굽지 않는다 — 이미지가 없으면 compose 가 조용히
# 이 호스트에서 굽기 시작하는 대신 멈춰야 한다(oracle 을 빌드로 느리게 만들지 않는다).
UP_FLAGS=""
if [ "$IMAGE_SOURCE" = registry ]; then UP_FLAGS="--no-build"; fi

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

# 뒤로 호환되지 않는 마이그레이션의 표식(ADR-0053). 파일 어디든 이 모양의 주석 한 줄이면
# 그 마이그레이션이 든 배포는 겹쳐 바꾸지 않는다. 같은 문자열을
# `backend/tests/test_migration_rolling_safety.py` 가 읽는다 — 바꾸면 둘을 같이 고친다.
UNSAFE_MIGRATION_MARKER='^[[:space:]]*#[[:space:]]*ROLLING-DEPLOY-UNSAFE:'

log() { echo "[deploy:${TARGET}] $*"; }

# 지금 compose 에 없는 채점 프로세스를 걷는다(#584) — `celery-scoring`(#582~#583 의 채점 워커)과
# `grader`(#584) 둘 다. compose 파일에서 서비스가 사라져도 컨테이너는 남는다(고아):
# - **첫 배포**(celery-scoring → grader): 옛 워커는 compose 에서 사라진 고아다.
# - **롤백**(grader → 옛 compose): grader 가 고아가 돼 옛 워커와 함께 돈다 — 리허설에서 보니 grader 의
#   임대 UPDATE 가 옛 워커의 행 잠금에 걸려 grader 가 통째로 멈췄다.
# 현재 `$COMPOSE config --services` 에 있는 것은 건드리지 않는다. 채점 중인 것을 마저 끝내도록 4분
# (`stop_grace_period` 와 같다) 기다려 멈추고 지운다. 없으면 아무 일도 하지 않는다.
#
# **마이그레이션보다 먼저 부른다.** 옛 워커는 벤더를 기다리는 동안 행 잠금 트랜잭션을 쥔다(분 단위).
# 그 뒤에 ALTER TABLE 이 줄을 서면 `classroom_classroomsubmission` 의 뒤 쿼리가 전부 그 뒤에 막힌다
# (리허설 실측: 마이그레이션 174초, 그동안 제출 요청이 타임아웃). 먼저 걷는 동안 backend 는 계속
# 요청을 받고, 제출은 DB 큐(`scoring_queued_at`)에서 기다린다.
# 옛 워커를 걷었으면 Redis 의 옛 큐 `classroom-scoring` 도 비운다(소비할 곳이 없다 — 시도는 DB 큐에 있다).
# 옛 deploy.sh 로 되돌릴 때는 이 함수가 없어 소용없다 — 되돌리기 전에 손으로 grader 를 내린다([배포] 문서).
retire_orphan_scoring() {
  current=$($COMPOSE config --services 2>/dev/null || true)
  retired_worker=false
  for svc in celery-scoring grader; do
    case "
$current
" in *"
$svc
"*) continue ;; esac
    old=$(docker ps -aq --filter "label=com.docker.compose.service=$svc" \
      --filter "label=com.docker.compose.project=codemit-${TARGET}" 2>/dev/null || true)
    if [ -n "$old" ]; then
      log "compose 에 없는 채점 프로세스($svc)를 걷는다 — 채점 중인 것을 마저 끝내느라 최대 4분 걸린다"
      # shellcheck disable=SC2086
      docker stop -t 240 $old >/dev/null 2>&1 || true
      # shellcheck disable=SC2086
      docker rm $old >/dev/null 2>&1 || true
      [ "$svc" = celery-scoring ] && retired_worker=true
    fi
  done
  if [ "$retired_worker" = true ]; then
    # 걷은 뒤에도 옛 backend 가 잠깐 더 넣을 수 있다 — 그것도 소비할 곳이 없다(시도는 DB 큐에 있다).
    $COMPOSE exec -T redis redis-cli -n 0 DEL classroom-scoring >/dev/null 2>&1 || true
    log "옛 채점 큐(classroom-scoring)를 비웠다"
  fi
}

# 서비스 이름 → compose 서비스들. backend 는 다섯을 함께 받는다(채점 grader 포함, #584)(아래 build 의 주석).
compose_services() {
  case "$1" in
    backend) echo "backend celery-worker celery-beat events grader" ;;
    frontend|operator|classroom|search|pgbouncer) echo "$1" ;;
    *) echo "알 수 없는 빌드 대상: $1 (backend|frontend|operator|classroom|search|pgbouncer)" >&2; return 2 ;;
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
  if [ "$IMAGE_SOURCE" = build ] && ! docker buildx version >/dev/null 2>&1; then
    echo "이 에이전트의 docker CLI 에 buildx 플러그인이 없다."
    echo "Dockerfile 의 RUN --mount(BuildKit 전용)를 구울 수 없다 — 에이전트 이미지에 docker-buildx 를 넣어라."
    exit 1
  fi

  # registry 는 ghcr 로그인이 저장돼 있어야 한다 — 없으면 pull 단계에서 「denied」 한 줄로
  # 죽어 원인이 흐려진다. 로그인 여부만 보고 토큰이 살아 있는지는 pull 이 말한다.
  if [ "$IMAGE_SOURCE" = registry ]; then
    docker_config="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
    if ! grep -q '"ghcr.io"' "$docker_config" 2>/dev/null; then
      echo "이 에이전트에 ghcr.io 로그인이 없다($docker_config) — ghcr 에서 이미지를 받을 수 없다."
      echo "read:packages 권한의 classic PAT 로 한 번 로그인해 둔다(scripts/ghcr-setup-wizard.sh 3단계):"
      echo "  docker login ghcr.io -u <GitHub 아이디> --password-stdin"
      echo "급하면 DEPLOY_IMAGE_SOURCE=build 로 이 호스트에서 굽는다."
      exit 1
    fi
  fi
  log "이미지 출처: $IMAGE_SOURCE (태그 $(echo "$CODEMIT_IMAGE_TAG" | cut -c1-12))"

  # compose 가 필수값을 전부 만족하는지 먼저 본다. 여기서 걸리는 것이 컨테이너를
  # 굽고 나서 부팅에 실패하는 것보다 싸다.
  $COMPOSE config >/dev/null
  log "preflight OK"
}

# ------------------------------------------------------- 무엇이 바뀌었나

# 직전 배포($PREVIOUS)의 compose 와 지금 것에서 풀러의 렌더된 정의가 다른가. 옛 파일은
# 지금 파일과 같은 디렉터리에 잠깐 꺼내 둔다 — 상대 경로(`build.context: ..`)와 프로젝트
# 이름이 같은 자리에서 풀려야 두 렌더가 비교된다. 무엇이든 실패하면 「바뀌었다」(참)다.
pooler_definition_changed() {
  previous_compose="docker/.jenkins-${TARGET}-previous-compose.yaml"
  if ! $GIT show "${PREVIOUS}:${COMPOSE_FILE}" > "$previous_compose" 2>/dev/null; then
    rm -f "$previous_compose"
    return 0
  fi
  before=$(docker compose -f "$previous_compose" --env-file "$ENV_FILE" config pgbouncer 2>/dev/null)
  before_status=$?
  rm -f "$previous_compose"
  [ "$before_status" -eq 0 ] || return 0
  after=$($COMPOSE config pgbouncer 2>/dev/null) || return 0
  [ "$before" != "$after" ]
}

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

  # **이미 더 새 커밋이 배포돼 있으면 아무것도 하지 않는다.** staging 은 CI 가 커밋마다
  # 이 잡을 부르므로, 늦게 끝난 옛 커밋의 실행이 새 배포를 되돌릴 수 있다.
  STALE=false
  head_sha=$($GIT rev-parse HEAD)
  if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$head_sha" ] \
     && $GIT merge-base --is-ancestor "$head_sha" "$PREVIOUS" 2>/dev/null; then
    STALE=true
    log "이 커밋($(echo "$head_sha" | cut -c1-12))보다 새 커밋($(echo "$PREVIOUS" | cut -c1-12))이 이미 배포돼 있다 — 건너뛴다."
  fi

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
  BUILD_SEARCH=false
  BUILD_PGBOUNCER=false

  if [ "$EVERYTHING" = true ]; then
    BUILD_BACKEND=true
    BUILD_FRONTEND=true
    BUILD_OPERATOR=true
    BUILD_CLASSROOM=true
    BUILD_SEARCH=true
    BUILD_PGBOUNCER=true
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

    # nori 플러그인을 넣은 OpenSearch(#450/#451) — backend 코드와 무관하게
    # 이 Dockerfile 하나로만 갈린다.
    if touched '^docker/search\.Dockerfile$'; then
      BUILD_SEARCH=true
    fi

    # 연결 풀러(pgbouncer, #453/#458) — backend 코드와 무관하게 이 Dockerfile과
    # 그 entrypoint 스크립트로만 갈린다(search와 같은 원칙).
    if touched '^docker/pgbouncer\.Dockerfile$|^docker/pgbouncer/'; then
      BUILD_PGBOUNCER=true
    fi

    # compose 파일 자체가 바뀌면 어느 서비스의 환경이 바뀌었는지 알 수 없다.
    # 전부 다시 세운다.
    #
    # **풀러만은 정의가 실제로 바뀌었을 때만 바꾼다**(2026-10-06, GlitchTip 64 재발).
    # 풀러를 바꾸는 배포는 backend·events 를 겹쳐 바꾸지 못하고 내렸다 올린다(아래
    # ROLLING_BACKEND). #582 가 다른 서비스(채점 워커)만 더했는데도 이 줄이 풀러까지
    # 바꾸게 해 prod 에서 이벤트 서비스 이름이 16초 넘게 안 풀렸고, BFF 재시도 예산(약
    # 15.8초)을 넘겨 강의실이 500 을 냈다. 직전 배포의 compose 와 지금 것을 compose 자신이
    # 렌더한 풀러 정의(그것이 기대는 db 포함)로 비교한다 — 렌더하지 못하면 바뀐 것으로 본다.
    if touched "^docker/compose\.${TARGET}\.yaml\$"; then
      log "compose.${TARGET}.yaml 이 바뀌었다 — 전부 다시 세운다."
      BUILD_BACKEND=true
      BUILD_FRONTEND=true
      BUILD_OPERATOR=true
      BUILD_CLASSROOM=true
      BUILD_SEARCH=true
      if pooler_definition_changed; then
        BUILD_PGBOUNCER=true
      else
        log "풀러(pgbouncer)의 정의는 그대로다 — 풀러는 바꾸지 않는다."
      fi
    fi
  fi

  # **없는 컨테이너는 변경 여부와 무관하게 굽는다.** 「없음」은 「최신」이 아니다.
  # 크래시 루프 끝에 사라진 것도 여기 걸린다.
  missing() {
    [ -z "$($COMPOSE ps -q "$1" 2>/dev/null | head -1)" ]
  }

  for svc in backend celery-worker celery-beat events grader; do
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
  if missing search; then
    log "search 컨테이너가 없다 — 굽는다."
    BUILD_SEARCH=true
  fi
  if missing pgbouncer; then
    log "pgbouncer 컨테이너가 없다 — 굽는다."
    BUILD_PGBOUNCER=true
  fi

  # 세 앱의 실행 env 가 바뀌었는가 (#711, 옛 #112 코드리뷰 지적 3의 토스 키 회전 감지를 넓혔다).
  # 앱 이미지는 환경을 모르고 공개 값(`CODEMIT_PUBLIC_*`)은 compose 가 .env.<target> 에서 넣는다 —
  # .env.<target> 은 gitignore 라 위 git diff 기반 감지는 값이 바뀐 것을 보지 못하고, 코드가 안
  # 바뀐 앱은 다시 띄우지 않으므로 옛 키를 문 채로 계속 돈다. 그래서 떠 있는 컨테이너에 compose 가
  # 붙여 둔 설정 해시(`com.docker.compose.config-hash`)를 **그 컨테이너의 이미지 태그·release 로
  # 다시 낸 지금 설정의 해시**와 견준다 — 커밋마다 바뀌는 그 둘을 옛 값으로 고정하면 남는 차이는
  # env 파일이 바꾼 것뿐이다. 다르면 그 앱을 다시 띄운다(같은 이미지를 받아 env 만 새로).
  app_env_drifted() {
    local cid image tag release was now
    cid=$($COMPOSE ps -q "$1" 2>/dev/null | head -1)
    [ -n "$cid" ] || return 1
    image=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null) || return 1
    tag=${image##*:}
    tag=${tag%-*}
    release=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$cid" 2>/dev/null \
      | sed -n 's/^CODEMIT_PUBLIC_SENTRY_RELEASE=//p' | head -1)
    was=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$cid" 2>/dev/null)
    now=$(CODEMIT_IMAGE_TAG="$tag" SENTRY_RELEASE="$release" $COMPOSE config --hash "$1" 2>/dev/null | awk '{print $2}')
    [ -n "$now" ] && [ "$now" != "$was" ]
  }
  if [ "$BUILD_FRONTEND" = false ] && app_env_drifted frontend; then
    log "frontend 의 실행 설정이 .env.${TARGET} 과 어긋난다(공개 값 등) — 다시 띄운다."
    BUILD_FRONTEND=true
  fi
  if [ "$BUILD_OPERATOR" = false ] && app_env_drifted operator; then
    log "operator 의 실행 설정이 .env.${TARGET} 과 어긋난다 — 다시 띄운다."
    BUILD_OPERATOR=true
  fi
  if [ "$BUILD_CLASSROOM" = false ] && app_env_drifted classroom; then
    log "classroom 의 실행 설정이 .env.${TARGET} 과 어긋난다 — 다시 띄운다."
    BUILD_CLASSROOM=true
  fi

  # **backend·events 를 겹쳐 바꿀 수 있는가**(#485, #526·ADR-0053). 겹쳐 바꾸면 옛
  # 컨테이너가 새 컨테이너와 몇 초 함께 요청을 받는다. 마이그레이션은 그 전에 새 이미지의
  # 일회성 컨테이너가 돌리므로(아래 run_migrations) **그 몇 초 동안 옛 코드가 새 스키마
  # 위에서 돈다** — 그래서 마이그레이션은 뒤로 호환되게 쓴다(ADR-0053: 추가는 그대로,
  # 삭제·이름 바꾸기·NOT NULL 은 다음 배포로 나눈다). 지키지 못한 마이그레이션은 파일에
  # `# ROLLING-DEPLOY-UNSAFE: <이유>` 를 달고, 그 표식이 배포 범위에 있으면 예전처럼
  # 넷을 내리고 올린다(`backend/tests/test_migration_rolling_safety.py` 가 표식 없는 위험
  # 연산을 막는다).
  #
  # 예전에는 **새 마이그레이션이 든 배포 전부가** 내리고 올렸다. 그 창이 공개 앱 재시도
  # 예산(약 15.8초)보다 길어 `/contests` 가 500 을 냈다(2026-10-02 prod, `0014_connected_apps`
  # — GlitchTip 75·83).
  #
  # 직전 배포 표식이 없으면 범위를 몰라 표식을 찾을 수 없다. 풀러를 바꾸는 배포는 위에서
  # 넷을 먼저 내리므로 겹칠 옛 컨테이너가 없고, 없는 컨테이너도 겹칠 대상이 없다.
  MIGRATIONS=false
  if [ "$EVERYTHING" = true ] || touched '^backend/[^/]+/migrations/'; then
    MIGRATIONS=true
  fi
  UNSAFE_MIGRATIONS=""
  if [ "$EVERYTHING" = false ]; then
    for f in $(grep -E '^backend/[^/]+/migrations/[^/]+\.py$' "$CHANGED_FILE" || true); do
      # 지워진 파일(배포 범위 안에서 사라진 것)은 볼 것이 없다.
      [ -f "$f" ] || continue
      if grep -qE "$UNSAFE_MIGRATION_MARKER" "$f"; then
        UNSAFE_MIGRATIONS="$UNSAFE_MIGRATIONS $f"
      fi
    done
  fi

  ROLLING_BACKEND=true
  ROLLING_REASON=""
  if [ "$EVERYTHING" = true ]; then
    ROLLING_BACKEND=false; ROLLING_REASON="직전 배포 표식이 없다(범위를 몰라 뒤로 호환되지 않는 마이그레이션을 찾을 수 없다)"
  elif [ -n "$UNSAFE_MIGRATIONS" ]; then
    ROLLING_BACKEND=false; ROLLING_REASON="뒤로 호환되지 않는 마이그레이션(ROLLING-DEPLOY-UNSAFE):${UNSAFE_MIGRATIONS}"
  elif [ "$BUILD_PGBOUNCER" = true ]; then
    ROLLING_BACKEND=false; ROLLING_REASON="풀러를 바꾼다"
  elif missing backend || missing events; then
    ROLLING_BACKEND=false; ROLLING_REASON="겹칠 옛 컨테이너가 없다"
  fi

  if [ "$STALE" = true ]; then
    BUILD_BACKEND=false
    BUILD_FRONTEND=false
    BUILD_OPERATOR=false
    BUILD_CLASSROOM=false
    BUILD_SEARCH=false
    BUILD_PGBOUNCER=false
  fi

  ANY=false
  if [ "$BUILD_BACKEND" = true ] || [ "$BUILD_FRONTEND" = true ] || [ "$BUILD_OPERATOR" = true ] || [ "$BUILD_CLASSROOM" = true ] || [ "$BUILD_SEARCH" = true ] || [ "$BUILD_PGBOUNCER" = true ]; then
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
    echo "BUILD_SEARCH=$BUILD_SEARCH"
    echo "BUILD_PGBOUNCER=$BUILD_PGBOUNCER"
    echo "ROLLING_BACKEND=$ROLLING_BACKEND"
    echo "PLANNED_COMMIT=$($GIT rev-parse HEAD)"
  } > "$PLAN_FILE"

  plan_word() {
    if [ "$1" = true ]; then echo "바꿔 끼운다"; else echo "건너뛴다"; fi
  }
  echo "계획"
  echo "  backend(+celery-worker,+celery-beat,+events,+grader) : $(plan_word "$BUILD_BACKEND")"
  echo "  frontend                                      : $(plan_word "$BUILD_FRONTEND")"
  echo "  operator                                      : $(plan_word "$BUILD_OPERATOR")"
  echo "  classroom                                     : $(plan_word "$BUILD_CLASSROOM")"
  echo "  search                                        : $(plan_word "$BUILD_SEARCH")"
  echo "  pgbouncer                                     : $(plan_word "$BUILD_PGBOUNCER")"
  if [ "$BUILD_BACKEND" = true ]; then
    if [ "$ROLLING_BACKEND" = true ] && [ "$MIGRATIONS" = true ]; then
      echo "  backend·events 교체 방식                      : 마이그레이션을 먼저 돌리고 겹쳐 바꾼다(끊김 없음)"
    elif [ "$ROLLING_BACKEND" = true ]; then
      echo "  backend·events 교체 방식                      : 겹쳐 바꾼다(끊김 없음)"
    else
      echo "  backend·events 교체 방식                      : 넷을 내리고 마이그레이션을 돌린 뒤 올린다 — ${ROLLING_REASON}"
    fi
  fi
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

# **backend·celery-worker·beat·events 는 같은 이미지다**(2026-09-17). 예전에는 compose
# 파일에 공유 `image:` 태그가 없어 compose 가 서비스 이름으로 이미지를 **넷** 만들었고,
# `build backend` 만 하면 나머지 셋이 옛 이미지에 남았다 — 배포는 초록으로 끝나는데
# 스캔·강의실 스트림만 옛 코드로 돌았다(빌드 23). 지금은 넷이 한 이름을 가리키므로
# 로컬로 구울 때도 backend 하나만 구우면 된다.
#
# 세 앱은 빌드 인자가 없다 — 공개 값은 실행 env 다(#711). 로컬로 구운 이미지도 레지스트리 것과 같다.
cmd_build() {
  compose_services "$1" >/dev/null
  log "$1 빌드 (이 호스트에서)"
  $COMPOSE build "$1"
}

cmd_pull() {
  services=$(compose_services "$1")
  log "$1 받기 ($services, 태그 $(echo "$CODEMIT_IMAGE_TAG" | cut -c1-12))"
  # 다섯이 같은 이미지라 실제 다운로드는 한 번이다.
  # shellcheck disable=SC2086
  if ! $COMPOSE pull $services; then
    echo "ghcr 에 이 커밋($CODEMIT_IMAGE_TAG)의 $1 이미지가 없거나 받을 수 없다."
    echo "laurio 잡의 이미지 단계가 끝났는지(prod 는 macos 노드), 저장해 둔 PAT 가 만료되지 않았는지 확인하라."
    echo "급하면 DEPLOY_IMAGE_SOURCE=build."
    exit 1
  fi
}

cmd_image() {
  if [ "$IMAGE_SOURCE" = registry ]; then cmd_pull "$1"; else cmd_build "$1"; fi
}

# 사람이 `all` 로 돌릴 때는 계획된 것을 동시에 굽는다 — 순차보다 빌드가 절반
# 가까이 짧다. 출력이 뒤섞이지 않도록 서비스별 로그로 받아 뒤에 순서대로 쏟는다.
# (파이프라인은 이 대신 서비스마다 병렬 단계를 두고 `build <서비스>` 를 부른다.)
build_planned_in_background() {
  BUILD_LOGS=$(mktemp -d)
  PIDS=""
  LABELS=""
  for label in backend frontend operator classroom search pgbouncer; do
    case "$label" in
      backend) wanted=$BUILD_BACKEND ;;
      frontend) wanted=$BUILD_FRONTEND ;;
      operator) wanted=$BUILD_OPERATOR ;;
      classroom) wanted=$BUILD_CLASSROOM ;;
      search) wanted=$BUILD_SEARCH ;;
      pgbouncer) wanted=$BUILD_PGBOUNCER ;;
    esac
    [ "$wanted" = true ] || continue
    cmd_image "$label" > "${BUILD_LOGS}/${label}.log" 2>&1 &
    PIDS="$PIDS $!:$label"
    LABELS="$LABELS $label"
    log "$label 이미지 준비 시작"
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
    echo "이미지 준비 실패:$FAILED — 배포 표식은 옮기지 않았다."
    exit 1
  fi
}

# Django(backend·events)가 요청을 받는지 한 번 본다. $1 은 exec 앞부분(`$COMPOSE exec -T
# backend` 또는 `docker exec <id>`), $2 는 포트. 헤더를 붙이는 이유는 cmd_health 주석에 있다.
django_answers() {
  # shellcheck disable=SC2086
  $1 python -c "import os,urllib.request,sys; host=(os.environ.get('DJANGO_ALLOWED_HOSTS') or '').split(',')[0].strip() or '127.0.0.1'; req=urllib.request.Request('http://127.0.0.1:${2}/api/health', headers={'Host': host, 'X-Forwarded-Proto': 'https'}); sys.exit(0 if urllib.request.urlopen(req, timeout=3).status==200 else 1)" 2>/dev/null
}

# **새 것을 먼저 띄우고 옛 것을 내린다**(#485). 예전에는 컨테이너를 내리고 새로 올려,
# 배포마다 공개 앱이 13~16초 동안 500 을 냈다(staging 실측, GlitchTip 64·74·75 —
# BFF 재시도 예산 약 15.8초보다 길었다).
#
# 1. 서비스를 잠시 둘로 늘린다(`--scale 2 --no-recreate`) — 옛 것은 그대로 두고 새 설정·
#    이미지로 하나를 더 띄운다. 그 사이 도커 DNS 는 서비스 이름에 둘을 함께 돌려준다.
# 2. **새 것이 /api/health 에 200 을 낼 때까지** 기다린다. 끝내 안 뜨면 새 것을 지우고
#    실패로 끝낸다 — 옛 것은 그대로 요청을 받는다(예전에는 이때 서비스가 비었다).
# 3. 옛 것을 멈춘다(SIGTERM — gunicorn 은 받던 요청을 마저 끝낸다). 멈추는 사이 옛
#    것으로 간 새 연결은 거부될 수 있는데, BFF 가 연결 거부를 다시 보낸다(`packages/
#    bff-shared`). 세 호스트의 compose(2.33·5.1·5.5)에서 실측: 멈추는 7초 동안 699번 중
#    거부 1번.
# 4. 새 것의 이름을 옛 이름(`…-backend-1`)으로 바꾼다 — compose 는 이름이 아니라 라벨로
#    컨테이너를 찾으므로 그대로 동작하고, 사람이 쓰는 `docker exec codemit-staging-backend-1`
#    이 배포마다 `-2`·`-1` 로 번갈아 바뀌지 않는다. 다음 교체의 번호는 compose 가 라벨의
#    최댓값 다음으로 매겨 이름이 겹치지 않는다(같은 실측).
#
# **호스트 포트를 열지 않는다** — 같은 서비스 둘이 한 호스트 포트를 잡을 수 없다. 그래서
# 두 배포 compose 의 backend 에 ports 가 없다(헬스 체크는 원래 컨테이너 안에서 친다).
# $1 서비스, $2 컨테이너 안 포트, $3 멈출 때 기다리는 초.
rolling_replace() {
  svc=$1; port=$2; grace=$3
  old=$($COMPOSE ps -q "$svc")
  if [ "$(printf '%s\n' "$old" | grep -c .)" -ne 1 ]; then
    log "$svc 컨테이너가 하나가 아니다 — 내리고 올린다"
    # shellcheck disable=SC2086
    $COMPOSE up -d --no-deps $UP_FLAGS "$svc"
    return 0
  fi
  old_name=$(docker inspect -f '{{.Name}}' "$old" | tr -d /)

  log "$svc 겹쳐 바꾼다 — 새 것을 먼저 띄운다"
  # shellcheck disable=SC2086
  $COMPOSE up -d --no-deps $UP_FLAGS --no-recreate --scale "$svc=2" "$svc"
  new=$($COMPOSE ps -q "$svc" | grep -v "$old" | head -1)
  if [ -z "$new" ]; then
    echo "$svc 의 새 컨테이너가 뜨지 않았다 — 옛 것은 그대로 둔다."
    exit 1
  fi

  i=0
  until django_answers "docker exec $new" "$port"; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "$svc 의 새 컨테이너가 150초 안에 응답하지 않았다 — 새 것을 지우고 옛 것을 그대로 둔다."
      docker logs --tail 120 "$new" || true
      docker rm -f "$new" >/dev/null 2>&1 || true
      exit 1
    fi
    sleep 5
  done
  log "$svc 새 것 응답 확인 — 옛 것을 내린다"

  docker stop -t "$grace" "$old" >/dev/null
  docker rm "$old" >/dev/null
  docker rename "$new" "$old_name"
  log "$svc 바꿨다 ($old_name)"
}

# **새 이미지의 일회성 컨테이너에서 migrate 를 돌린다**(#526, ADR-0053). `run --rm` 은
# backend 서비스와 같은 이미지·환경·네트워크로 컨테이너 하나를 띄웠다 지운다 — 떠 있는
# backend 와 별개라 겹쳐 바꾸기 전에 스키마를 먼저 바꿀 수 있다. 한 배포에 한 번만, 이
# 컨테이너 하나만 돌린다 — Django 마이그레이션은 둘이 동시에 돌면 안전하지 않은데, 배포
# compose 의 backend 기동 command 에서 migrate 를 뺐으므로 겹친 두 backend 가 같이 돌릴
# 일이 없다.
#
# **풀러를 거친다**(POSTGRES_HOST=pgbouncer, 트랜잭션 모드). 예전에도 backend 의 기동
# command 가 같은 경로로 migrate 를 돌려 왔고(10-02 prod 의 `0014_connected_apps` 도 그렇게
# 적용됐다), Django 의 migrate 는 마이그레이션 하나를 트랜잭션 하나로 돌리며 세션 상태
# (서버측 커서·advisory lock·SET)에 기대지 않는다 — `tests/test_pgbouncer_live.py` 가 풀러
# 너머로 마이그레이션을 처음부터 돌려 확인한다. 풀러에는 질의·유휴 트랜잭션 시간 제한이
# 없다(docker/pgbouncer/docker-entrypoint.sh). `--no-deps` 인 이유: db·redis·풀러는 cmd_up 이
# 이미 세웠고, 의존 서비스를 여기서 다시 세우게 두면 search 등을 건드릴 수 있다.
#
# prod 의 backend 환경에는 PROMETHEUS_MULTIPROC_DIR 가 있다 — 그 디렉터리가 없으면 지표를
# 만드는 코드가 실패할 수 있어, 있을 때만 만든다(staging 은 그 값이 없다).
run_migrations() {
  log "마이그레이션 — 새 이미지($(echo "$CODEMIT_IMAGE_TAG" | cut -c1-12))의 일회성 컨테이너에서"
  # **잠금을 기다리는 시간에 상한을 둔다**(리허설 실측, ADR-0053 「장기 트랜잭션 뒤 줄 서기」):
  # ALTER TABLE 은 테이블 잠금을 얻기까지 기다리는 동안 뒤 쿼리를 전부 막는다. 5초 안에 얻지 못하면
  # 그 마이그레이션은 되감기고(DDL 은 트랜잭션) 몇 번 다시 한다 — 그래도 안 되면 배포를 멈춘다.
  # `lock_timeout` 은 잠금 대기에만 걸려 오래 걸리는 DDL·데이터 이전 자체는 막지 않는다.
  # 풀러(pgbouncer, 트랜잭션 모드)는 `PGOPTIONS`(시작 매개변수 `options`)를 거부하므로 이 일회성
  # 컨테이너만 풀러가 붙는 **실제 DB 주소**로 직접 붙는다(풀러 컨테이너가 쓰는 값을 그대로 읽는다).
  # 풀러가 없는 compose 면 값이 없어 이전처럼 돌린다.
  set --
  dbhost=$($COMPOSE run --rm --no-deps -T --entrypoint printenv pgbouncer POSTGRES_HOST 2>/dev/null | tr -d '\r\n' || true)
  if [ -n "$dbhost" ]; then
    dbport=$($COMPOSE run --rm --no-deps -T --entrypoint printenv pgbouncer POSTGRES_PORT 2>/dev/null | tr -d '\r\n' || true)
    set -- -e "POSTGRES_HOST=$dbhost" -e "POSTGRES_PORT=${dbport:-5432}" -e "PGOPTIONS=-c lock_timeout=${MIGRATE_LOCK_TIMEOUT:-5s}"
  fi
  attempt=1
  while :; do
    out=$(mktemp)
    # shellcheck disable=SC2016
    if $COMPOSE run --rm --no-deps -T "$@" backend \
      sh -c 'if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then mkdir -p "$PROMETHEUS_MULTIPROC_DIR"; fi; exec python manage.py migrate --noinput' \
      >"$out" 2>&1; then
      cat "$out"; rm -f "$out"
      break
    fi
    cat "$out"
    if grep -q "lock timeout" "$out" && [ "$attempt" -lt "${MIGRATE_LOCK_RETRIES:-5}" ]; then
      rm -f "$out"
      log "마이그레이션이 테이블 잠금을 ${MIGRATE_LOCK_TIMEOUT:-5s} 안에 얻지 못했다(긴 트랜잭션이 쥐고 있다) — ${attempt}번째, ${MIGRATE_LOCK_RETRY_SLEEP:-10}초 뒤 다시"
      attempt=$((attempt + 1))
      sleep "${MIGRATE_LOCK_RETRY_SLEEP:-10}"
      continue
    fi
    if grep -q "lock timeout" "$out"; then
      log "마이그레이션이 ${attempt}번 모두 테이블 잠금을 얻지 못했다 — 긴 트랜잭션(옛 채점 워커 등)이 쥐고 있다. 배포를 멈춘다"
    fi
    rm -f "$out"
    return 1
  done
  log "마이그레이션 끝"
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
  # 아래 up 은 전부 $UP_FLAGS(registry 면 --no-build)를 붙인다.

  if [ "$BUILD_PGBOUNCER" = true ]; then
    # **풀러를 바꾸기 전에, 풀러를 거쳐 DB 에 붙어 있는 넷을 먼저 내린다**
    # (2026-09-22, #481~#484). 예전에는 옛 backend 넷이 풀러에 연결된 채로
    # 풀러를 갈아 끼워서, 그때 날아가던 질의가 전부
    # `server closed the connection unexpectedly` 로 끊겨 **prod 사용자에게 500**
    # 이 나갔다 — 9-21 배포에서 공모전 목록 화면 한 번이 동시에 보낸 요청 셋이
    # 같은 밀리초에 그렇게 죽었다(GlitchTip 70·71·72·73). #482 가 재현 스크립트로
    # 세 번 돌려 세 번 모두 그 메시지로 죽는 것을 보였다.
    #
    # 먼저 내리면 **반쯤 처리된 질의가 끊기지 않는다** — `stop` 은 SIGTERM 이라
    # gunicorn 이 받던 요청을 마저 끝내고 내린다. **실패 창은 남는다**: 실측
    # (2026-09-22, staging)으로 약 13초 동안 공개 앱이 500 을 내거나 응답하지
    # 않았고(Next 는 살아 있으니 502 가 아니다), 그 실패는 공개 앱의
    # `fetch failed` 로 GlitchTip 에 오른다. backend 의 OperationalError 는 다시
    # 나지 않았다.
    #
    # backend 를 먼저 내리는 이유는 HTTP 를 받는 쪽이라 거기부터 새 요청을 멈춰야
    # 해서다. events 의 SSE 는 끊기면 화면이 폴링으로 물러난다(ADR-0046).
    log "풀러를 바꾼다 — 그 전에 grader·backend·celery-worker·celery-beat·events 를 내린다"
    retire_orphan_scoring
    # 채점 워커를 먼저 따로 내린다 — 따뜻한 종료가 채점 중인 것을 마저 끝내느라 최대
    # 4분(`stop_grace_period`) 걸릴 수 있고, 그동안 backend 는 아직 요청을 받는다.
    $COMPOSE stop grader
    $COMPOSE stop backend celery-worker celery-beat events
    # shellcheck disable=SC2086
    $COMPOSE up -d --no-deps $UP_FLAGS pgbouncer
    # **풀러가 다시 들을 때까지 넷을 올리지 않는다.** 먼저 올리면 첫 요청들이 또
    # 끊긴다 — 막으려던 것이 바로 그것이다. 풀러가 끝내 안 뜨면 여기서 배포가
    # 실패로 끝나고 넷은 내려간 채 남는다: 넷은 풀러 없이는 어차피 DB 에 닿지
    # 못하므로(위 헤더 주석 "pgbouncer는 필수 경로다") 켜 두어도 500 만 낸다.
    cmd_health pgbouncer
    if [ "$BUILD_BACKEND" != true ]; then
      # 이 배포가 backend 를 바꾸지 않으면 아래 블록이 넷을 올리지 않는다 —
      # 내린 그 컨테이너를 그대로 다시 켠다(`start` 는 다시 만들지 않으므로 이미지가
      # 바뀌지 않는다). 바꾸는 배포면 아래 블록이 새 이미지로 올린다.
      $COMPOSE start backend celery-worker celery-beat events grader
    fi
  fi

  if [ "$BUILD_SEARCH" = true ]; then
    # backend·celery-worker·celery-beat·events보다 먼저 올린다 — 그 넷의
    # compose depends_on이 search를 "시작 순서"로만 기다린다(헬스는 아니다,
    # compose.staging/prod.yaml 주석 참고). 검색이 죽어도 backend는 뜬다
    # (DB 검색으로 물러난다) — 여기서 헬스를 기다리지 않는다.
    # shellcheck disable=SC2086
    $COMPOSE up -d --no-deps $UP_FLAGS search
  fi

  if [ "$BUILD_BACKEND" = true ]; then
    # **다섯을 함께 바꾼다.** backend 만 갈면 워커·beat·events·채점 워커가 옛 코드로
    # 남는다 — 앞의 둘은 스캔으로 상태를 진행시키는 주체고, events 는 강의실
    # 실시간 신호를 여는 주체다(ADR-0046, #380). grader 는 강의실 채점(ADR-0059).
    #
    # **마이그레이션은 여기서, 넷을 바꾸기 전에 한 번 돌린다**(#526, ADR-0053). 예전에는
    # backend 의 command 가 기동 때 migrate 를 돌렸는데, 그러면 겹쳐 바꾸는 동안 새
    # 컨테이너가 스키마를 바꾸는 시점을 배포가 고르지 못하고, 실패해도 옛 것이 이미
    # 내려간 뒤에야 안다. 지금 배포 compose 의 backend 는 migrate 를 부르지 않는다.
    if [ "${ROLLING_BACKEND:-false}" = true ]; then
      # 옛 넷은 그대로 요청을 받는 채로 스키마를 먼저 바꾼다 — 마이그레이션이 뒤로
      # 호환되므로 옛 코드는 새 스키마 위에서 그대로 돈다(표식이 붙은 것은 plan 이
      # 이 길로 보내지 않는다). 실패하면 아무것도 내리지 않고 끝낸다.
      # 마이그레이션보다 **먼저** 고아 채점 프로세스를 걷는다 — 옛 워커의 장기 트랜잭션 뒤에
      # ALTER TABLE 이 줄을 서면 API 가 멈춘다(`retire_orphan_scoring` 주석). backend 는 그동안
      # 요청을 계속 받고 제출은 DB 큐에서 기다린다.
      retire_orphan_scoring
      if ! run_migrations; then
        echo "마이그레이션이 실패했다 — 옛 backend·worker·beat·events 는 그대로 요청을 받는다."
        echo "실패한 것 앞의 마이그레이션은 이미 적용됐을 수 있다(뒤로 호환되므로 옛 코드는 그대로 돈다)."
        exit 1
      fi
      # 겹쳐 바꾼다(#485) — 아래 rolling_replace 주석. worker·beat 는 사용자 요청을
      # 받지 않고(태스크는 Redis 에서 기다린다) beat 는 하나여야 하므로 지금처럼 바꾼다.
      rolling_replace backend 8000 30
      # shellcheck disable=SC2086
      $COMPOSE up -d --no-deps $UP_FLAGS celery-worker celery-beat
      rolling_replace events 8001 10
      # grader 는 맨 끝에 바꾼다(#584, ADR-0059) — 옛 grader 가 채점 중인 것을 마저
      # 끝내는 따뜻한 종료를 최대 4분(`stop_grace_period`) 기다리므로, 앞에 두면
      # backend·events 교체가 그만큼 늦어진다. 그동안 큐에 넣은 시도는 DB 에서
      # 기다린다(채점 대기가 길어질 뿐 잃지 않는다).
      log "grader 를 바꾼다 — 채점 중인 것을 마저 끝내느라 최대 4분 걸린다"
      # shellcheck disable=SC2086
      $COMPOSE up -d --no-deps $UP_FLAGS grader
    else
      # **넷을 먼저 내리고 마이그레이션을 돌린다.** 뒤로 호환되지 않는 마이그레이션(표식)은
      # 옛 코드가 새 스키마 위에서 한순간도 돌면 안 된다 — 예전 순서(backend 만 다시
      # 만들고 그 기동 command 가 migrate)는 그 사이 옛 worker·beat·events 를 새 스키마
      # 위에 남겼다. 풀러를 바꾸는 배포면 위에서 이미 내려가 있다(stop 은 그대로 지나간다).
      log "grader·backend·celery-worker·celery-beat·events 를 내리고 마이그레이션을 돌린다 — 이 동안 backend 가 없다"
      # grader 를 먼저 따로 내린다 — 따뜻한 종료가 최대 4분 걸리고(위 풀러 블록과 같은
      # 이유), 그동안 backend 는 아직 요청을 받는다. backend 가 없는 창을 늘리지 않는다.
      retire_orphan_scoring
      $COMPOSE stop grader
      $COMPOSE stop backend celery-worker celery-beat events
      if ! run_migrations; then
        # 내린 그 컨테이너(옛 이미지)를 되살린다 — 서비스가 통째로 비는 것보다 낫다.
        # Postgres 의 DDL 은 트랜잭션이라 실패한 마이그레이션 자체는 되감겼지만, 그 앞의
        # 것은 적용됐을 수 있다. 사람이 `showmigrations` 로 보고 판단한다.
        echo "마이그레이션이 실패했다 — 내렸던 옛 컨테이너를 다시 켠다. 앞선 마이그레이션은 적용됐을 수 있다."
        $COMPOSE start backend celery-worker celery-beat events grader || true
        exit 1
      fi
      # shellcheck disable=SC2086
      $COMPOSE up -d --no-deps $UP_FLAGS backend
      # shellcheck disable=SC2086
      $COMPOSE up -d --no-deps $UP_FLAGS celery-worker celery-beat events grader
    fi
  fi
  # shellcheck disable=SC2086
  if [ "$BUILD_FRONTEND" = true ]; then $COMPOSE up -d --no-deps $UP_FLAGS frontend; fi
  # shellcheck disable=SC2086
  if [ "$BUILD_OPERATOR" = true ]; then $COMPOSE up -d --no-deps $UP_FLAGS operator; fi
  # shellcheck disable=SC2086
  if [ "$BUILD_CLASSROOM" = true ]; then $COMPOSE up -d --no-deps $UP_FLAGS classroom; fi
  log "바꿔 끼웠다"
}

# ------------------------------------------------------- 떴는지 확인한다

cmd_verify() {
  # 부팅 거부는 이 저장소가 **의도한** 동작이다(#83, #96) — 어댑터 값이나 OAuth
  # 자격증명이 풀리지 않으면 컨테이너가 뜨지 않는다. 그러니 "떴다"를 실제로
  # 확인해야 하고, 죽었으면 로그를 남겨야 원인을 안다.
  for svc in backend celery-worker celery-beat events grader frontend operator classroom search pgbouncer; do
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
#
# **search 는 Django 가 아니다**(#450/#451) — Host 헤더도 `/api/health` 도 없다.
# OpenSearch 자신의 클러스터 헬스 엔드포인트를 컨테이너 안에서 직접 친다(dev
# `search` 프로필의 healthcheck와 같은 것).
#
# **pgbouncer도 Django가 아니다**(#453/#458) — Postgres 와이어 프로토콜만
# 말하므로 `/api/health`가 없다. dev pgbouncer 프로필의 healthcheck와 같은
# TCP 확인(`nc -z`)을 컨테이너 안에서 직접 친다. 이 확인이 통과했다고 그
# 뒤의 실제 DB까지 붙는다는 보장은 아니다(포트만 듣고 있어도 통과한다) —
# 그건 `cmd_health backend`(그 자신이 DB 를 거쳐야 200 을 낸다)가 대신 본다.
# 그래도 이 확인은 「포트조차 안 듣는다」는 가장 흔한 실패(컨테이너가 아예
# 죽었다)를 backend 보다 먼저, 더 빨리 잡는다.
cmd_health() {
  case "$1" in
    backend|events|search|pgbouncer) ;;
    *) echo "알 수 없는 헬스 체크 대상: $1 (backend|events|search|pgbouncer)"; exit 2 ;;
  esac
  i=0
  while [ "$i" -lt 30 ]; do
    if [ "$1" = search ]; then
      if $COMPOSE exec -T search curl -sf http://127.0.0.1:9200/_cluster/health >/dev/null 2>&1; then
        log "$1 응답 확인"
        return 0
      fi
    elif [ "$1" = pgbouncer ]; then
      if $COMPOSE exec -T pgbouncer nc -z 127.0.0.1 6432 >/dev/null 2>&1; then
        log "$1 응답 확인"
        return 0
      fi
    else
      port=8000
      [ "$1" = events ] && port=8001
      if django_answers "$COMPOSE exec -T $1" "$port"; then
        log "$1 응답 확인"
        return 0
      fi
    fi
    i=$((i + 1))
    sleep 5
  done
  echo "$1 가 150초 안에 응답하지 않았다"
  $COMPOSE logs --tail 120 "$1" || true
  exit 1
}

# ------------------------------------------------------------ 검색 재색인

# 검색이나 backend 를 바꿔 끼운 뒤 부른다(부모 #444 스펙 "다시 띄운 뒤에는 전체
# 재색인을 한 번 돌린다"). 스캔 등록부의 `contest-search-reindex`는 실제
# 벽시계로 하루에 한 번만 도는 안전망이라(`contests/search_scan.py`, 반복
# 배포마다 매번 다시 도는 것을 막는 장치다) 배포 직후 즉시 맞추려면 그
# 하루 제한을 보지 않는 관리 명령을 직접 부른다.
cmd_reindex_search() {
  log "검색 전체 재색인"
  if ! $COMPOSE exec -T backend python manage.py rebuild_contest_search_index; then
    echo "검색 전체 재색인이 실패했다 — 배포는 계속한다(다음 배포나 사람이 다시 돌려야 한다)."
  fi
}

# --------------------------------------------------- 배포 표식을 옮긴다

cmd_mark() {
  # 다음 빌드의 「직전 배포」 기준점. **확인이 끝난 뒤에만** 옮긴다 — 실패한
  # 배포를 기준으로 삼으면 그 사이 변경이 다음 빌드에서 통째로 누락된다.
  # 파이프라인에서는 앞 단계가 하나라도 실패하면 이 단계에 닿지 않는다.
  #
  # **뒤로 옮기지 않는다.** 늦게 끝난 옛 커밋의 실행(plan 이 STALE 로 건너뛴 것)이
  # 표식을 옛 커밋으로 되돌리면 다음 배포의 변경 범위가 부풀고 순서 판단도 틀린다.
  head_sha=$($GIT rev-parse HEAD)
  if [ -f "$DEPLOYED" ]; then
    previous=$(cat "$DEPLOYED")
    if [ "$previous" != "$head_sha" ] && $GIT merge-base --is-ancestor "$head_sha" "$previous" 2>/dev/null; then
      rm -f "$PLAN_FILE"
      log "배포 표식은 그대로 둔다 — 더 새 커밋($(echo "$previous" | cut -c1-12))이다."
      return 0
    fi
  fi
  echo "$head_sha" > "$DEPLOYED"
  rm -f "$PLAN_FILE"
  log "배포 표식: $(cat "$DEPLOYED")"
}

# ------------------------------------------- 쓰이지 않는 이미지·캐시를 지운다

# 배포가 끝나면 이 호스트의 도커 디스크를 비운다(2026-09-17). 커밋마다 ghcr 에서
# 새 태그를 받으니 옛 커밋의 이미지가 그대로 쌓이고(서비스 다섯 × 배포 수), oracle 에는
# ghcr 로 옮기기 전 이 호스트에서 굽던 빌드 캐시가 남아 있었다(정리 전 실측: sub 이미지
# 78GB·빌드 캐시 107GB, oracle 이미지 76GB·빌드 캐시 47GB).
#
# - **이 저장소의 ghcr 이미지 중 이번 커밋 것이 아닌 것**을 지운다. 돌고 있는 컨테이너가
#   쓰는 이미지(이번 배포에서 바뀌지 않아 옛 태그로 도는 서비스)는 도커가 거절하므로
#   남는다 — 그 거절을 삼킨다. 되돌릴 때는 ghcr 에서 다시 받으면 된다.
# - 태그를 잃은 이미지와 **사흘(72h) 넘게 안 쓴 빌드 캐시**를 지운다. registry 모드에서는
#   이 호스트가 굽지 않지만, sub 는 CI 테스트 잡이 같은 데몬에서 굽고 비상구
#   (`DEPLOY_IMAGE_SOURCE=build`)도 있어 최근 캐시는 남긴다.
#
# 정리는 배포의 일부가 아니다 — 무엇이 실패해도 배포를 실패로 만들지 않는다. 다른
# 프로젝트의 이미지는 건드리지 않는다(`image prune -a` 를 쓰지 않는 이유).
cmd_prune() {
  repo="${CODEMIT_IMAGE_REPO:-ghcr.io/sandcorporation}"
  log "쓰이지 않는 이미지·빌드 캐시 정리 (남기는 태그 $(echo "$CODEMIT_IMAGE_TAG" | cut -c1-12))"
  removed=0
  kept=0
  for ref in $(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
      | grep "^${repo}/codemit-" | grep -v "^${repo}/codemit-buildcache:" \
      | grep -v ":${CODEMIT_IMAGE_TAG}-"); do
    if docker rmi "$ref" >/dev/null 2>&1; then
      removed=$((removed + 1))
    else
      kept=$((kept + 1))
    fi
  done
  log "옛 커밋 이미지: ${removed}개 지움, ${kept}개는 컨테이너가 쓰는 중이라 남김"
  docker image prune -f >/dev/null 2>&1 || true
  docker builder prune -f --filter until=72h 2>/dev/null | tail -1 || true
  docker system df 2>/dev/null || true
  return 0
}

# ------------------------------------------------------------------ 진입점

case "$COMMAND" in
  preflight) cmd_preflight ;;
  plan) cmd_plan ;;
  image|pull|build)
    [ -n "$ARG" ] || { echo "$COMMAND 에는 서비스가 필요하다 (backend|frontend|operator|classroom|search|pgbouncer)"; exit 2; }
    compose_services "$ARG" >/dev/null
    case "$COMMAND" in
      image) cmd_image "$ARG" ;;
      pull) cmd_pull "$ARG" ;;
      build) cmd_build "$ARG" ;;
    esac
    ;;
  up) cmd_up ;;
  verify) cmd_verify ;;
  health)
    [ -n "$ARG" ] || { echo "health 에는 서비스가 필요하다 (backend|events|search|pgbouncer)"; exit 2; }
    cmd_health "$ARG"
    ;;
  reindex) cmd_reindex_search ;;
  mark) cmd_mark ;;
  prune) cmd_prune ;;
  all)
    cmd_preflight
    cmd_plan
    load_plan
    if [ "$DEPLOY_ANY" = true ]; then
      build_planned_in_background
      cmd_up
      cmd_verify
      # pgbouncer 먼저 — backend·events 는 그 뒤(정확히는 DB)까지 붙어야
      # 응답하므로, 포트조차 안 듣는 가장 흔한 실패를 여기서 먼저 잡는다.
      cmd_health pgbouncer
      cmd_health backend
      cmd_health events
      cmd_health search
      if [ "$BUILD_SEARCH" = true ] || [ "$BUILD_BACKEND" = true ]; then
        cmd_reindex_search
      fi
    fi
    cmd_mark
    cmd_prune
    ;;
  *)
    echo "알 수 없는 명령: $COMMAND (preflight|plan|image|pull|build|up|verify|health|reindex|mark|prune|all)"
    exit 2
    ;;
esac
