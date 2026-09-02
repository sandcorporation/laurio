// staging 배포 (#52).
//
// **바뀐 것만 다시 굽고 바꿔 끼운다.** 그런데 「바뀐 것」과 「바꿔 끼울 것」이
// 1:1 이 아니다 — 그 어긋남이 이 파일의 대부분이다.
//
//   backend/          -> backend + celery-worker + celery-beat   (셋이 같은 이미지)
//   frontend/         -> frontend
//   operator/         -> operator
//   packages/bff-shared/ -> frontend + operator                  (둘이 함께 쓴다)
//   pnpm-lock.yaml    -> frontend + operator
//   docker/*.Dockerfile / compose.staging.yaml -> 그 파일이 짓는 것 전부
//
// **`backend` 만 바꿔 끼우는 것은 사고다.** celery-worker 와 beat 가 옛 코드로
// 계속 돈다 — 그 둘이 마감 전이·채점·배분·지급을 실제로 진행시키는 주체다
// (ADR-0003). 새 코드가 만든 마이그레이션 위에서 옛 워커가 도는 상태가 되고,
// 그건 조용히 틀린다.
//
// 컨테이너가 없으면 변경 여부와 무관하게 굽는다 — 「없음」은 「최신」이 아니다.

pipeline {
  // 스택이 실제로 떠 있는 호스트에 고정한다. `agent any` 로 두면 여러 에이전트가
  // 있을 때 스택이 없는 머신에서 돌아 `compose ps` 가 전부 「없음」으로 나오고,
  // 그러면 매번 전부 다시 굽는다.
  agent { label 'laurio-staging' }

  environment {
    COMPOSE  = 'docker compose -f docker/compose.staging.yaml --env-file docker/.env.staging'
    // 「직전에 무엇을 배포했나」. `.env.staging` 과 같은 자리에 둔다 — 빌드
    // 디렉터리가 유지된다는 전제이고, 그 전제는 이미 시크릿이 쓰고 있다.
    //
    // git tag 로 두지 않는 이유: `git fetch --prune --tags` 나 강제 체크아웃이
    // 조용히 옮기거나 지운다. 이 값이 틀리면 배포 범위가 통째로 어긋난다.
    //
    // 이 파일이 없어지면 전부 다시 굽는다 — 느릴 뿐 틀리지는 않는다.
    DEPLOYED = '.jenkins-staging-deployed'
    // 롤백할 때 무엇으로 돌아가야 하는지 남긴다.
    TAG      = "${env.GIT_COMMIT ?: 'manual'}".take(12)
  }

  options {
    timestamps()
    disableConcurrentBuilds()          // 같은 호스트의 같은 스택을 두 빌드가 밟지 않게
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  stages {

    stage('Preflight') {
      steps {
        sh '''
          set -eu

          # 시크릿은 저장소에 없다(.gitignore) — 빌드 디렉터리에 사람이 한 번
          # 두고, 체크아웃이 그것을 지우지 않는다는 전제다. 지워지는 설정(예:
          # "Clean before checkout")으로 바뀌면 여기서 걸린다.
          test -f docker/.env.staging || {
            echo "docker/.env.staging 이 없다."
            echo "docker/staging.env.example 을 복사해 채운 뒤 빌드 디렉터리에 두고 chmod 600 해라."
            exit 1
          }
          # compose 가 필수값(${VAR:?})을 전부 만족하는지 먼저 본다. 여기서
          # 걸리는 것이 컨테이너를 굽고 나서 부팅에 실패하는 것보다 싸다.
          ${COMPOSE} config >/dev/null
        '''
      }
    }

    stage('무엇이 바뀌었나') {
      steps {
        script {
          // 직전 성공 배포와 비교한다. 그것이 없으면(첫 배포·이력 유실) 전부
          // 바뀐 것으로 본다 — 모르면 굽는 쪽이 안전하다.
          // 표식이 가리키는 커밋이 이 저장소에 실제로 있는지까지 본다 —
          // force-push 나 히스토리 재작성 뒤에는 남아 있는 SHA 가 `git diff`
          // 에서 터진다. 그때는 「모른다」로 떨어져 전부 굽는 편이 맞다.
          def previous = sh(
            script: """
              set -eu
              [ -f ${DEPLOYED} ] || exit 0
              sha=\$(cat ${DEPLOYED})
              git cat-file -e "\$sha^{commit}" 2>/dev/null && printf '%s' "\$sha" || true
            """,
            returnStdout: true,
          ).trim()

          def changed
          if (previous) {
            changed = sh(
              script: "git diff --name-only ${previous} HEAD",
              returnStdout: true,
            ).trim().split('\n') as List
            echo "직전 배포(${previous.take(12)}) 이후 변경 ${changed.size()}개 파일"
          } else {
            changed = ['<첫 배포>']
            echo '직전 배포 표식이 없다 — 전부 다시 굽는다.'
          }

          boolean everything = !previous

          // 한 경로가 여러 서비스를 건드린다. 그 팬아웃이 이 파이프라인의 전부다.
          boolean backendChanged =
            everything || changed.any { it ==~ /^(backend\/.*|docker\/backend\.Dockerfile)$/ }
          boolean sharedChanged =
            everything || changed.any {
              it ==~ /^(packages\/bff-shared\/.*|pnpm-lock\.yaml|pnpm-workspace\.yaml|package\.json)$/
            }
          boolean frontendChanged =
            everything || sharedChanged ||
            changed.any { it ==~ /^(frontend\/.*|docker\/frontend\.Dockerfile)$/ }
          boolean operatorChanged =
            everything || sharedChanged ||
            changed.any { it ==~ /^(operator\/.*|docker\/operator\.Dockerfile)$/ }

          // compose 파일 자체가 바뀌면 어느 서비스의 환경이 바뀌었는지 알 수
          // 없다. 전부 다시 세운다.
          if (changed.any { it ==~ /^docker\/compose\.staging\.yaml$/ }) {
            echo 'compose.staging.yaml 이 바뀌었다 — 전부 다시 세운다.'
            backendChanged = frontendChanged = operatorChanged = true
          }

          // **없는 컨테이너는 변경 여부와 무관하게 굽는다.** 「없음」은 「최신」이
          // 아니다. 크래시 루프로 죽어 있는 것도 여기 걸린다.
          def missing = { String svc ->
            sh(script: "${COMPOSE} ps -q ${svc} 2>/dev/null | head -1", returnStdout: true).trim() == ''
          }
          def backendServices = ['backend', 'celery-worker', 'celery-beat']
          if (backendServices.any { missing(it) }) {
            echo '백엔드 계열 컨테이너 중 없는 것이 있다 — 굽는다.'
            backendChanged = true
          }
          if (missing('frontend'))  { echo 'frontend 컨테이너가 없다 — 굽는다.';  frontendChanged = true }
          if (missing('operator'))  { echo 'operator 컨테이너가 없다 — 굽는다.';  operatorChanged = true }

          env.BUILD_BACKEND  = backendChanged  as String
          env.BUILD_FRONTEND = frontendChanged as String
          env.BUILD_OPERATOR = operatorChanged as String

          echo """계획
  backend(+celery-worker,+celery-beat) : ${backendChanged  ? '다시 굽는다' : '건너뛴다'}
  frontend                             : ${frontendChanged ? '다시 굽는다' : '건너뛴다'}
  operator                             : ${operatorChanged ? '다시 굽는다' : '건너뛴다'}"""

          if (!backendChanged && !frontendChanged && !operatorChanged) {
            echo '바뀐 것이 없다. 배포할 것이 없다.'
          }
        }
      }
    }

    stage('굽는다') {
      parallel {
        stage('backend') {
          when { environment name: 'BUILD_BACKEND', value: 'true' }
          // 셋이 같은 이미지를 쓰므로 한 번만 굽는다.
          steps { sh '${COMPOSE} build backend' }
        }
        stage('frontend') {
          when { environment name: 'BUILD_FRONTEND', value: 'true' }
          // NEXT_PUBLIC_* 는 빌드타임에 인라인된다 — build args 는 compose 가
          // .env.staging 에서 읽어 넘긴다(#85). 여기서 따로 줄 것이 없다.
          steps { sh '${COMPOSE} build frontend' }
        }
        stage('operator') {
          when { environment name: 'BUILD_OPERATOR', value: 'true' }
          steps { sh '${COMPOSE} build operator' }
        }
      }
    }

    stage('바꿔 끼운다') {
      steps {
        sh '''
          set -eu

          # 인프라는 항상 떠 있어야 한다(idempotent — 이미 떠 있으면 아무 일도
          # 일어나지 않는다).
          ${COMPOSE} up -d db redis

          if [ "${BUILD_BACKEND}" = "true" ]; then
            # **셋을 함께 바꾼다.** backend 만 갈면 워커·beat 가 옛 코드로 남는데,
            # 그 둘이 스캔으로 상태를 진행시키는 주체다.
            #
            # backend 의 command 가 migrate 를 먼저 돌리므로, 워커·beat 는 그
            # 뒤에 올린다 — 새 마이그레이션이 필요한 코드가 아직 없는 스키마
            # 위에서 스캔을 돌리는 창을 만들지 않는다.
            ${COMPOSE} up -d --no-deps backend
            ${COMPOSE} up -d --no-deps celery-worker celery-beat
          fi

          [ "${BUILD_FRONTEND}" = "true" ] && ${COMPOSE} up -d --no-deps frontend
          [ "${BUILD_OPERATOR}" = "true" ] && ${COMPOSE} up -d --no-deps operator

          true
        '''
      }
    }

    stage('떴는지 확인한다') {
      steps {
        sh '''
          set -eu

          # 부팅 거부는 이 저장소가 **의도한** 동작이다(#83) — 어댑터 값이
          # 풀리지 않으면 컨테이너가 뜨지 않는다. 그러니 "떴다"를 실제로
          # 확인해야 하고, 죽었으면 로그를 남겨야 원인을 안다.
          for svc in backend celery-worker celery-beat frontend operator; do
            cid=$(${COMPOSE} ps -q "$svc" 2>/dev/null | head -1)
            if [ -z "$cid" ]; then
              echo "[$svc] 컨테이너가 없다"; continue
            fi
            state=$(docker inspect -f '{{.State.Status}}' "$cid")
            if [ "$state" != "running" ]; then
              echo "[$svc] 상태가 running 이 아니다: $state"
              ${COMPOSE} logs --tail 80 "$svc" || true
              exit 1
            fi
          done

          # 백엔드가 요청을 실제로 받는지 본다. 컨테이너가 running 인 것과
          # gunicorn 이 응답하는 것은 다르다.
          for i in $(seq 1 30); do
            if ${COMPOSE} exec -T backend python -c \
                 "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)" 2>/dev/null; then
              echo "backend 응답 확인"
              exit 0
            fi
            sleep 5
          done
          echo "backend 가 150초 안에 응답하지 않았다"
          ${COMPOSE} logs --tail 120 backend || true
          exit 1
        '''
      }
    }

    stage('배포 표식을 옮긴다') {
      steps {
        // 다음 빌드의 「직전 배포」 기준점. **확인이 끝난 뒤에만** 옮긴다 —
        // 실패한 배포를 기준으로 삼으면 그 사이 변경이 다음 빌드에서 통째로
        // 누락된다.
        sh '''
          set -eu
          git rev-parse HEAD > "${DEPLOYED}"
          echo "배포 표식: $(cat "${DEPLOYED}")"
        '''
      }
    }
  }

  post {
    failure {
      // 진단이 먼저다 — 시크릿 정리는 `cleanup` 에서 한다. Jenkins 는
      // `always` 를 `failure` 보다 **먼저** 돌리므로, 정리를 always 에 두면
      // 이 진단이 .env.staging 없이 돌아 compose 가 필수값에서 죽는다.
      sh '${COMPOSE} ps || true'
      echo '배포 실패 — 배포 표식은 옮기지 않았다. 다음 빌드가 같은 범위를 다시 시도한다.'
    }
  }
}
