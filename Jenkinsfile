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
// **잡은 Pipeline 이다**(`scriptPath: Jenkinsfile`, 브랜치 `*/main`).
//
// **무엇이 이 잡을 부르는가**(2026-09-17). CI 다 — main 의 CI 가 staging 이미지를 ghcr 에
// 올리고 나머지 잡이 전부 초록이면 `deploy-staging` 잡이 `buildWithParameters` 로
// DEPLOY_SHA 를 채워 부른다. 그 커밋을 정확히 배포하려고 워크스페이스를 그 커밋으로
// 되돌린다. 예전 트리거인 GitHub 웹훅은 이미지가 올라가기 **전에** 이 잡을 부르므로,
// 웹훅으로 불린 빌드(DEPLOY_SHA 없음)는 아무것도 하지 않고 끝난다 — 잡 설정에서
// 웹훅 트리거를 꺼도 되고 켜 둬도 해가 없다. 사람이 파라미터를 비우고 누르면 main 의
// 끝을 배포한다(그 커밋의 이미지가 ghcr 에 있어야 한다).

def deployTarget = 'staging'

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
    string(name: 'DEPLOY_SHA', defaultValue: '', trim: true,
           description: 'CI 가 채운다 — 이 커밋(40자리)의 이미지로 배포한다. 비우면 main 의 끝.')
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
          def sha = params.DEPLOY_SHA ?: ''
          if (!sha && !currentBuild.getBuildCauses('com.cloudbees.jenkins.GitHubPushCause').isEmpty()) {
            env.SKIP_DEPLOY = 'true'
            currentBuild.description = 'GitHub push — CI 가 이미지를 올린 뒤 다시 부른다'
            echo 'GitHub 웹훅으로 불렸다 — 이 커밋의 이미지가 아직 없을 수 있어 배포하지 않는다.'
            return
          }
          if (sha) {
            if (!(sha ==~ /[0-9a-f]{40}/)) {
              error("DEPLOY_SHA 는 40자리 커밋 해시여야 한다: '${sha}'")
            }
            // 빌드 시작 때 체크아웃한 main 의 끝이 그 커밋을 품고 있어야 한다 — main 에
            // 없는 커밋(강제 push 로 사라진 것 등)은 배포하지 않는다. fetch 는 하지 않는다:
            // 잡의 체크아웃만 자격증명을 갖는다.
            sh "git -c safe.directory=\"\$PWD\" merge-base --is-ancestor ${sha} HEAD"
            sh "git -c safe.directory=\"\$PWD\" checkout --quiet --detach ${sha}"
            currentBuild.description = sha.take(12)
          }
        }
        sh 'git -c safe.directory="$PWD" log -1 --oneline'
      }
    }

    stage('Preflight') {
      when { expression { env.SKIP_DEPLOY != 'true' } }
      steps {
        sh "sh ./deploy.sh ${deployTarget} preflight"
      }
    }

    stage('변경 계획') {
      when { expression { env.SKIP_DEPLOY != 'true' } }
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
      when { expression { env.SKIP_DEPLOY != 'true' } }
      steps {
        sh "sh ./deploy.sh ${deployTarget} mark"
      }
    }
  }

  post {
    failure {
      echo '배포 실패 — 배포 표식은 옮기지 않았다. 다음 빌드가 같은 범위를 다시 시도한다.'
    }
  }
}
