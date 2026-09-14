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
// **잡은 Pipeline 이다**(`scriptPath: Jenkinsfile`, 트리거는 GitHub 웹훅, 브랜치 `*/main`).

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

  options {
    timestamps()
    disableConcurrentBuilds()          // 같은 호스트의 같은 스택을 두 빌드가 밟지 않게
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  stages {
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

    stage('빌드') {
      when { expression { env.DEPLOY_ANY == 'true' } }
      // 하나가 실패해도 나머지는 끝까지 굽는다 — 한 번에 실패 원인을 전부 본다.
      // 어느 하나라도 실패하면 이 단계가 빨갛고 뒤의 교체·표식에는 닿지 않는다.
      parallel {
        stage('backend') {
          when { expression { env.BUILD_BACKEND == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} build backend" }
        }
        stage('frontend') {
          when { expression { env.BUILD_FRONTEND == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} build frontend" }
        }
        stage('operator') {
          when { expression { env.BUILD_OPERATOR == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} build operator" }
        }
        stage('classroom') {
          when { expression { env.BUILD_CLASSROOM == 'true' } }
          steps { sh "sh ./deploy.sh ${deployTarget} build classroom" }
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
      }
    }

    stage('배포 표식') {
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
