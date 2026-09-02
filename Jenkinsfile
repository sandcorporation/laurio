// staging 배포 (#52) — **얇은 껍데기다.**
//
// 배포 논리는 여기가 아니라 `deploy.sh` 에 산다. 이 저장소의 Jenkins 잡이
// Pipeline 이 아니라 freestyle 이고 셸 스텝이 `sh ./deploy.sh staging` 하나뿐이기
// 때문이다 — 그래서 Jenkinsfile 에 논리를 두면 **아무도 읽지 않는 두 번째 사본**이
// 되고, 실제로 그렇게 한 번 어긋나서 배포가 통째로 실패했다(빌드 #4:
// `cannot open ./deploy.sh`).
//
// 무엇을 다시 굽고 무엇을 바꿔 끼우는지, 왜 backend 만 갈면 안 되는지는 전부
// `deploy.sh` 의 주석에 있다.
//
// 이 파일은 잡을 Pipeline 으로 바꿀 때를 위해 남아 있다. 바꿔도 동작은 같다.

pipeline {
  // 스택이 실제로 떠 있는 호스트에 고정한다. `agent any` 로 두면 여러 에이전트가
  // 있을 때 스택이 없는 머신에서 돌아 `compose ps` 가 전부 「없음」으로 나오고,
  // 그러면 매번 전부 다시 굽는다.
  agent { label 'laurio-staging' }

  options {
    timestamps()
    disableConcurrentBuilds()          // 같은 호스트의 같은 스택을 두 빌드가 밟지 않게
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  stages {
    stage('배포') {
      steps {
        sh 'sh ./deploy.sh staging'
      }
    }
  }

  post {
    failure {
      echo '배포 실패 — 배포 표식은 옮기지 않았다. 다음 빌드가 같은 범위를 다시 시도한다.'
    }
  }
}
