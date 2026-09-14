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
  // 스택이 실제로 떠 있는 호스트 = Jenkins 컨트롤러다. `built-in` 은 컨트롤러가
  // **항상** 갖는 내장 라벨이라(Jenkins 2.307+) 사람이 노드 설정을 유지할 필요가
  // 없다 — 커스텀 라벨(`codemit-staging`)로 뒀더니 노드에 그 라벨을 붙였는데도
  // "There are no nodes with the label" 로 스케줄되지 않아 빌드가 통째로 멈췄다.
  //
  // `agent any` 로 두지 않는 이유: 이 컨트롤러에는 `desktop` 에이전트도 붙어
  // 있는데 거기엔 스택도 `docker/.env.staging` 도 없다. 거기서 돌면 preflight 가
  // 즉시 걸려 실패는 시끄럽지만, 애초에 배차되지 않는 편이 낫다.
  agent { label 'built-in' }

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
