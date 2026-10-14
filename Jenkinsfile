// staging 배포 (#52) — 단계는 보이게, 논리는 `deploy.sh` 에.
//
// 각 단계의 본문은 `deploy.sh staging <명령>` 한 줄이다. 무엇을 다시 굽고 무엇을 바꿔
// 끼우는지, 왜 backend 만 갈면 안 되는지는 전부 `deploy.sh` 의 주석에 있다 — 여기에
// 논리를 두면 아무도 읽지 않는 두 번째 사본이 된다(예전 freestyle 잡 시절 빌드 #4:
// `cannot open ./deploy.sh`).
//
// 단계를 나눈 이유: 예전에는 `sh ./deploy.sh staging` 한 단계뿐이라 Jenkins 화면에서
// 어느 서비스의 빌드가, 교체가, 헬스 체크가 실패했는지 로그를 뒤져야 알았다.
// `Jenkinsfile.production` 도 같은 단계를 갖는다 — 한쪽 단계를 바꾸면 다른 쪽도 같이
// 고친다(다른 것은 agent 라벨·대상·prod 의 브랜치 검사뿐이다).
//
// **잡은 Pipeline 이다**(`scriptPath: Jenkinsfile`, 브랜치 `*/staging`).
//
// **무엇이 이 잡을 부르는가**(2026-10-02). `staging` 브랜치의 push 다(GitHub 웹훅,
// GitHubPushTrigger). 그 브랜치는 사람이 커밋하지 않는다 — main 에 들어온 커밋의 이미지 열둘과
// 부팅 가드 셋이 GitHub Actions(images.yaml)에서 초록이면 그 워크플로가 `staging` 을 그 커밋으로
// fast-forward 한다. 그래서 웹훅이 이 잡을 부르는 순간 이미지는 이미 ghcr 에 있다. 예전에는
// main 의 CI 가 `buildWithParameters` 로 DEPLOY_SHA 를 채워 불렀다(그때 잡 브랜치는 `*/main`).
//
// **초록이면 `production` 을 같은 커밋으로 앞당긴다**(아래 post success, scripts/ci/fast_forward.py)
// — 그것이 prod 잡(Jenkinsfile.production)을 부른다. staging 에서 실제로 떠서 헬스 체크를 통과한
// 커밋만 prod 로 간다.

def deployTarget = 'staging'

// 디스코드 알림에 쓸 대상 이름(아래 post 참고).
def TARGET_LABEL = 'staging'

pipeline {
  // 스택이 실제로 떠 있는 호스트 = Jenkins 컨트롤러다. `built-in` 은 컨트롤러가
  // **항상** 갖는 내장 라벨이라(Jenkins 2.307+) 사람이 노드 설정을 유지할 필요가
  // 없다 — 커스텀 라벨(`codemit-staging`)로 뒀더니 노드에 그 라벨을 붙였는데도
  // "There are no nodes with the label" 로 스케줄되지 않아 빌드가 통째로 멈췄다.
  //
  // `agent any` 로 두지 않는 이유: 이 컨트롤러에는 다른 에이전트(prod 의 `oracle` 등)도
  // 붙어 있는데 거기엔 staging 스택도 `docker/.env.staging` 도 없다.
  agent { label 'built-in' }

  // 이미지는 CI 가 굽고 ghcr 에서 받는다(2026-09-17, deploy.sh 머리 주석). ghcr·CI 가
  // 막혔을 때는 사람이 호스트에서 `DEPLOY_IMAGE_SOURCE=build sh ./deploy.sh <대상>` 으로 굽는다.
  environment {
    DEPLOY_IMAGE_SOURCE = 'registry'
  }

  parameters {
    // 켜면 staging 이 초록일 때 production 을 같은 커밋으로 앞당긴다. **기본은 꺼짐이다**(2026-10-14)
    // — 강의실 화면을 시안 v2 로 크게 고치는 동안 prod 를 붙잡아 둔다. 웹훅 빌드는 기본값으로
    // 도므로 그동안 main 의 커밋은 staging 까지만 간다. prod 로 보내려면 이 잡을 손으로
    // 「Build with Parameters」 로 켜서 돌리거나, 다시 기본값을 true 로 되돌린다. 선언형
    // 파이프라인은 이 블록을 빌드 시작 때 잡 설정에 다시 쓰므로 Jenkins 의 저장된 기본값도
    // 이 값을 따라간다.
    booleanParam(name: 'PROMOTE_PRODUCTION', defaultValue: false,
                 description: '초록이면 production 을 이 커밋으로 앞당긴다(→ prod 배포)')
  }

  options {
    timestamps()
    disableConcurrentBuilds()          // 같은 호스트의 같은 스택을 두 빌드가 밟지 않게
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  stages {
    stage('대상 확인') {
      steps {
        script {
          // 이 파일이 staging 이 아닌 브랜치로 잘못 돌면(잡 브랜치 지정 실수) 이미지가 없거나
          // 승격되지 않은 커밋을 배포하고, 끝에서 그 커밋을 production 으로 앞당긴다. 멈춘다.
          def branch = env.GIT_BRANCH ?: ''
          if (!(branch == 'staging' || branch.endsWith('/staging'))) {
            error("staging 브랜치만 staging 으로 배포한다 — 지금 브랜치: '${branch}'")
          }
          currentBuild.description = (env.GIT_COMMIT ?: '').take(12)
        }
        sh 'git -c safe.directory="$PWD" log -1 --oneline'
      }
    }

    stage('Preflight') {
      steps {
        sh "sh ./deploy.sh ${deployTarget} preflight"
      }
    }

    stage('변경 계획') {
      steps {
        sh "sh ./deploy.sh ${deployTarget} plan"
        script {
          // deploy.sh 가 남긴 `KEY=value` 줄을 읽어 뒤 단계의 when 에 쓴다.
          readFile(".jenkins-${deployTarget}-plan").split('\n').each { line ->
            def parts = line.split('=', 2)
            if (parts.length == 2) { env."${parts[0].trim()}" = parts[1].trim() }
          }
        }
      }
    }

    stage('이미지') {
      when { expression { env.DEPLOY_ANY == 'true' } }
      // 하나가 실패해도 나머지는 끝까지 굽는다 — 한 번에 실패 원인을 전부 본다.
      // 어느 하나라도 실패하면 이 단계가 빨갛고 뒤의 교체·표식에는 닿지 않는다.
      parallel {
        stage('backend') {
          when { expression { env.BUILD_BACKEND == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} image backend" }
        }
        stage('frontend') {
          when { expression { env.BUILD_FRONTEND == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} image frontend" }
        }
        stage('operator') {
          when { expression { env.BUILD_OPERATOR == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} image operator" }
        }
        stage('classroom') {
          when { expression { env.BUILD_CLASSROOM == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} image classroom" }
        }
        stage('search') {
          when { expression { env.BUILD_SEARCH == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} image search" }
        }
      }
    }

    stage('교체') {
      when { expression { env.DEPLOY_ANY == 'true' } }
      steps {
        sh "sh ./deploy.sh ${deployTarget} up"
      }
    }

    stage('확인') {
      when { expression { env.DEPLOY_ANY == 'true' } }
      stages {
        stage('컨테이너') {
          steps { sh "sh ./deploy.sh ${deployTarget} verify" }
        }
        stage('backend 응답') {
          steps { sh "sh ./deploy.sh ${deployTarget} health backend" }
        }
        stage('events 응답') {
          steps { sh "sh ./deploy.sh ${deployTarget} health events" }
        }
        stage('search 응답') {
          steps { sh "sh ./deploy.sh ${deployTarget} health search" }
        }
        stage('검색 재색인') {
          // 검색이나 backend 를 바꿨을 때만 — 스캔의 하루 제한을 보지 않고
          // 즉시 맞춘다(deploy.sh reindex, 부모 #444 스펙).
          when { expression { env.BUILD_SEARCH == 'true' || env.BUILD_BACKEND == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} reindex" }
        }
      }
    }

    stage('배포 표식') {
      steps {
        sh "sh ./deploy.sh ${deployTarget} mark"
      }
    }

    // 옛 커밋의 ghcr 이미지·오래된 빌드 캐시를 지운다(deploy.sh prune). 실패해도
    // 배포를 실패로 만들지 않는다 — 명령 자신도 언제나 0 으로 끝나지만, 여기서도
    // 실패를 삼킨다.
    stage('정리') {
      steps {
        sh "sh ./deploy.sh ${deployTarget} prune || echo '정리를 건너뛴다 — 배포 결과와 무관하다'"
      }
    }
  }

  post {
    // **빌드가 끝나면 디스코드로 결과를 보낸다**(2026-09-18). 배포는 사람이 화면을
    // 보고 있지 않을 때 도는 일이라, 끝났다는 사실이 사람에게 닿는 자리가 없었다 —
    // 실패는 더더욱 그렇다(2026-09-17 staging 배포가 정리 단계에서 빨갛게 끝난 것을
    // 한참 뒤에 알았다).
    //
    // **웹훅 주소는 저장소에 두지 않는다** — Jenkins 자격증명(Secret text)
    // `discord-deploy-webhook` 에 있고, 여기서는 이름으로만 부른다. 그 값을 아는
    // 사람은 그 채널에 아무 말이나 올릴 수 있으므로 커밋에 남기면 안 된다.
    //
    // **알림이 실패해도 빌드 결과를 뒤집지 않는다** — `|| true` 와
    // `catchError` 가 그 역할이다. 자격증명이 없는 Jenkins(새로 세운 것 등)에서도
    // 배포 자체는 그대로 돌아야 한다.
    always {
      catchError(buildResult: null, stageResult: null, message: '디스코드 알림 실패 — 배포 결과와 무관하다') {
        withCredentials([string(credentialsId: 'discord-deploy-webhook', variable: 'DISCORD_WEBHOOK')]) {
          script {
            def result = currentBuild.currentResult
            def mark = result == 'SUCCESS' ? '\u2705' : (result == 'ABORTED' ? '\u26aa' : '\u274c')
            def sha = (env.GIT_COMMIT ?: '').take(12)
            def took = currentBuild.durationString.replace(' and counting', '')
            def text = "${mark} ${TARGET_LABEL} 배포 ${result} — #${env.BUILD_NUMBER}" +
              (sha ? " (${sha})" : '') + " · ${took} · ${env.BUILD_URL}"
            // 본문은 JSON 이라 따옴표·역슬래시를 그대로 실으면 깨진다 — Groovy 가
            // 만들어 준 문자열을 셸이 다시 해석하지 않도록 파일로 넘긴다.
            writeFile file: 'discord-payload.json', text: groovy.json.JsonOutput.toJson([content: text])
            sh 'curl -sS -X POST -H "Content-Type: application/json" --data @discord-payload.json "$DISCORD_WEBHOOK" > /dev/null || true'
          }
        }
      }
    }
    // staging 에서 초록이었던 커밋을 prod 로 보낸다. `production` 이 움직이면 웹훅이 prod 잡을
    // 부른다. 토큰은 PR CI 의 자동 병합과 같은 것이다(Contents 쓰기 — 워크플로 파일을 바꾼 커밋은
    // Workflows 쓰기도 있어야 한다). 실패하면 빌드가 빨갛다 — staging 은 바뀌었는데 prod 가 따라가지
    // 않은 상태라 사람이 봐야 한다.
    success {
      script {
        if (params.PROMOTE_PRODUCTION == false) {
          echo 'PROMOTE_PRODUCTION 이 꺼져 있다 — production 은 그대로 둔다.'
        } else {
          withCredentials([usernamePassword(credentialsId: 'github-sandcorporation-token', usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
            sh 'python3 scripts/ci/fast_forward.py production "$(git -c safe.directory="$PWD" rev-parse HEAD)"'
          }
        }
      }
    }
    failure {
      echo '배포 실패 — 배포 표식은 옮기지 않았고 production 도 앞당기지 않았다. 다음 빌드가 같은 범위를 다시 시도한다.'
    }
  }
}
