// main 의 커밋 하나의 여정 전부 (#52 → #705 → #779) — 이미지 → 부팅 가드 → `staging` 앞당기기 → staging 배포 →
// (PROMOTE_PRODUCTION 이면) prod 배포 → `production` 앞당기기. 단계는 보이게, 논리는 스크립트에.
//
// **잡 `codemit-deploy-staging`(#708 전에는 `laurio`)은 Pipeline 이다**(`scriptPath: Jenkinsfile`, 브랜치 `*/main`, GitHub 웹훅
// `GitHubPushTrigger`). 2026-10-15 까지는 GitHub Actions(`.github/workflows/images.yaml`)가 이미지
// 열둘과 부팅 가드 셋을 돌리고 `staging` 을 앞당겼고, 이 잡은 `staging` push 에서 배포만 했다 —
// 조직의 Actions 분량(Free, 월 2,000분)이 바닥나 `staging` 이 멈춘 뒤 Actions 를 떠났다(ADR-0061).
// 이제 커밋 하나가 이 잡의 빌드 하나에 다 보인다.
//
//   대상 확인(built-in)     main 인지, 마지막 staging 배포 뒤로 문서만 바뀌었는지(`scripts/ci/changed.sh` —
//                           그러면 여기서 초록)
//   이미지                  macos 가 arm64 여섯(prod), sub 가 amd64 여섯(staging) — `scripts/ci/images.sh`.
//                           앱도 환경을 모른다 — 공개 값은 서버의 `.env.<target>` 에서 실행 때(#711, ADR-0062).
//                           바뀌지 않은 서비스는 굽지 않고 커밋 태그만 더한다(빌드 문맥 해시 = `ctx-` 태그).
//                           열차를 거쳐 온 커밋은 열차가 같은 트리로 굽고 병합 전에 ctx 를 붙여 두어 전부 건너뛴다
//                           (#712) — 그러면 「대상 확인」이 커밋 태그만 더하고 가지는 노드를 잡지 않는다(#729)
//   부팅 가드(sub)          이번에 구운 앱만 — `scripts/ci/deploy-guard.sh`
//   문맥 태그(sub)          여기까지 초록이면 이번에 구운 것에 `ctx-` 태그 — `scripts/ci/images-ctx.sh`. 그래서
//                           「건너뛴다」는 언제나 앞 빌드가 가드까지 초록으로 본 이미지다(#709)
//   staging 앞당기기         `scripts/ci/fast_forward.py staging <sha>` — 배포 기록이자 브랜치의 뜻은 그대로
//   staging 배포(built-in)  Preflight → 변경 계획 → 이미지 받기 → 교체 → 확인 → 배포 표식 → 정리 — 각 단계는
//                           `deploy.sh staging <명령>` 한 줄이다. 무엇을 바꿔 끼우는지는 전부 deploy.sh 주석에
//                           있다(여기에 논리를 두면 아무도 읽지 않는 두 번째 사본이 된다 — 예전 freestyle 잡
//                           시절 빌드 #4: `cannot open ./deploy.sh`)
//   prod 배포(oracle)        PROMOTE_PRODUCTION 이면 같은 단계를 `deploy.sh prod <명령>` 으로 — 노드는 prod 스택이
//                           떠 있는 Oracle A1 호스트의 인바운드 에이전트 `oracle`, 워크스페이스는 `codemit-deploy-prod`
//                           (아래 그 단계의 주석). 2026-10-23(#779) 전에는 별도 잡 `codemit-deploy-prod`
//                           (`Jenkinsfile.production`, 이 파일의 배포 단계를 복제한 198줄)이 `production` 의 웹훅으로 돌았다
//   production 앞당기기      prod 배포가 초록으로 끝난 **뒤** `production` 을 같은 커밋으로 — 「prod 에 배포된 커밋」의
//                           기록이자 `ghcr_prune.py` 의 보호 대상. 이제 이 push 는 아무 잡도 깨우지 않는다
//
// prod 만 다시 돌리고 싶으면 이 잡을 PROMOTE_PRODUCTION=true 로 다시 돌린다 — staging 단계는 `deploy.sh plan` 이
// 「이미 배포됨」으로 비우고 prod 단계만 일한다.
//
// **IMAGES_ONLY** 를 켜면 이미지·부팅 가드까지만 돌고 앞당기기·배포는 건너뛴다 — 브랜치를 가리지 않는다.
// 이 파일을 바꾼 PR 을 병합 전에 돌려 보는 길이다(PR 브랜치를 가리키는 임시 잡). PR CI 는 이 파일을 보지 못한다.
//
// **노드마다 같은 커밋을 쓴다.** 단계마다 제 노드에서 다시 체크아웃하므로, 그 사이 main 이 움직였으면
// 다른 커밋을 받을 수 있다 — 첫 단계가 적은 DEPLOY_SHA 로 되돌려 놓는다(pin()).

def deployTarget = 'staging'
def prodTarget = 'prod'

// 이 노드의 체크아웃을 첫 단계가 고른 커밋으로 맞춘다. main 은 앞으로만 가므로 그 커밋은 언제나 있다.
def pin() {
  sh '''
    git -c safe.directory="$PWD" cat-file -e "${DEPLOY_SHA}^{commit}" \
      || { echo "이 노드의 체크아웃에 ${DEPLOY_SHA} 가 없다 — main 이 강제로 바뀌었는가?"; exit 1; }
    git -c safe.directory="$PWD" checkout -q --detach "${DEPLOY_SHA}"
    git -c safe.directory="$PWD" log -1 --oneline
  '''
}

// images.sh 가 남긴 `서비스=built|skipped|failed` 를 env 로 — 부팅 가드가 이번에 구운 앱만 고른다.
def readImageResult(String arch) {
  readFile(".images-${arch}.result").split('\n').each { line ->
    def parts = line.split('=', 2)
    if (parts.length == 2) { env."IMAGE_${arch.toUpperCase()}_${parts[0].trim().toUpperCase()}" = parts[1].trim() }
  }
}

// 「대상 확인」의 retag 결과가 그 아키텍처의 여섯 전부 `skipped` 인가.
def allSkipped(String arch) {
  if (!fileExists(".images-${arch}.result")) { return false }
  def lines = readFile(".images-${arch}.result").trim().split('\n')
  if (lines.length == 0) { return false }
  for (line in lines) {
    if (!line.trim().endsWith('=skipped')) { return false }
  }
  return true
}

pipeline {
  // 단계마다 노드가 다르다 — 배포는 스택이 떠 있는 컨트롤러(`built-in`), 이미지는 macos·sub, 가드는 sub.
  //
  // `built-in` 은 컨트롤러가 **항상** 갖는 내장 라벨이라(Jenkins 2.307+) 사람이 노드 설정을 유지할
  // 필요가 없다 — 커스텀 라벨(`codemit-staging`)로 뒀더니 노드에 그 라벨을 붙였는데도 "There are no
  // nodes with the label" 로 스케줄되지 않아 빌드가 통째로 멈췄다. 배포를 `agent any` 로 두지 않는
  // 이유: 이 컨트롤러에는 다른 에이전트(prod 의 `oracle` 등)도 붙어 있는데 거기엔 staging 스택도
  // `docker/.env.staging` 도 없다.
  agent none

  // 이미지는 이 잡이 앞 단계에서 굽고 배포는 ghcr 에서 받는다(deploy.sh 머리 주석). ghcr 가 막혔을
  // 때는 사람이 호스트에서 `DEPLOY_IMAGE_SOURCE=build sh ./deploy.sh <대상>` 으로 굽는다.
  environment {
    DEPLOY_IMAGE_SOURCE = 'registry'
  }

  parameters {
    // 켜면 staging 이 초록일 때 같은 빌드가 prod 로 배포하고 production 을 같은 커밋으로 앞당긴다. **기본은 꺼짐이다**(2026-10-14)
    // — 강의실 화면을 시안 v2 로 크게 고치는 동안 prod 를 붙잡아 둔다. 웹훅 빌드는 기본값으로
    // 도므로 그동안 main 의 커밋은 staging 까지만 간다. prod 로 보내려면 이 잡을 손으로
    // 「Build with Parameters」 로 켜서 돌리거나, 다시 기본값을 true 로 되돌린다. 선언형
    // 파이프라인은 이 블록을 빌드 시작 때 잡 설정에 다시 쓰므로 Jenkins 의 저장된 기본값도
    // 이 값을 따라간다.
    booleanParam(name: 'PROMOTE_PRODUCTION', defaultValue: false,
                 description: 'staging 이 초록이면 같은 빌드가 prod 로 배포하고 production 을 이 커밋으로 앞당긴다')
    booleanParam(name: 'IMAGES_ONLY', defaultValue: false,
                 description: '이미지·부팅 가드까지만 — staging·production 은 건드리지 않는다(어느 브랜치든)')
  }

  options {
    timestamps()
    disableConcurrentBuilds()          // 같은 호스트의 같은 스택을 두 빌드가 밟지 않게
    buildDiscarder(logRotator(numToKeepStr: '50'))
  }

  stages {
    stage('대상 확인') {
      agent { label 'built-in' }
      steps {
        script {
          // 이 파일이 main 이 아닌 브랜치로 돌면(잡 브랜치 지정 실수) 시험을 거치지 않은 커밋을 staging 에
          // 올리고 끝에서 production 까지 앞당긴다. 멈춘다 — IMAGES_ONLY 는 이미지만 올리므로 예외다.
          def branch = env.GIT_BRANCH ?: ''
          if (!params.IMAGES_ONLY && !(branch == 'main' || branch.endsWith('/main'))) {
            error("main 브랜치만 staging 으로 배포한다 — 지금 브랜치: '${branch}'")
          }
          env.DEPLOY_SHA = sh(returnStdout: true, script: 'git -c safe.directory="$PWD" rev-parse HEAD').trim()
          currentBuild.description = env.DEPLOY_SHA.take(12) + (params.IMAGES_ONLY ? ' 이미지만' : '')
          // 문서(.md·docs/)만 바뀌었으면 이미지에 드는 것이 없다 — 굽지도 앞당기지도 않고 초록으로 끝난다.
          // 기준은 **마지막으로 staging 배포를 끝낸 커밋**(deploy.sh 의 배포 표식 — 이 노드의 이 워크스페이스에
          // 「배포 표식」 단계가 남긴다): 그 사이 커밋이 여럿이면 그 전부를 본다. `origin/staging` 으로 두지 않는
          // 이유: staging 앞당기기는 배포보다 먼저라, 커밋 X 의 배포가 실패한 뒤 문서만 바꾼 커밋이 오면 X 를
          // 다시 배포하지 않고 초록이 됐다(#709). 표식이 없으면(새 워크스페이스) 전부 돈다.
          def changed = sh(returnStdout: true, script: '''
            base=""
            if [ -f .jenkins-staging-deployed ]; then base=$(cat .jenkins-staging-deployed); fi
            if [ -n "$base" ] && git -c safe.directory="$PWD" cat-file -e "${base}^{commit}" 2>/dev/null; then
              bash scripts/ci/changed.sh "$base"
            else
              echo TESTS=1
            fi
          ''').trim()
          env.DOCS_ONLY = (changed == 'TESTS=0') ? 'true' : 'false'
          if (env.DOCS_ONLY == 'true') {
            echo '문서만 바뀌었다 — 이미지·가드·배포를 건너뛴다.'
            currentBuild.description += ' 문서만'
          } else {
            // 열차를 거쳐 온 커밋은 열차가 같은 트리로 굽고 병합 전에 ctx 를 붙였다(#712, #729) — 그러면 굽지
            // 않고 커밋 태그만 더하면 된다. 그 일(`images.sh` 의 retag — 빌더를 띄우지 않는다)을 이 노드에서 먼저
            // 해 보고, 한 아키텍처가 전부 「건너뛴다」면 그 「이미지」 가지는 노드를 잡지 않는다. 줄이 길 때
            // macos 실행기를 다음 열차와, sub 실행기를 열차의 sub 단계와 다투지 않으려는 것이다. 구울 것이
            // 하나라도 있거나 retag 가 붉으면 그 가지가 평소대로 돈다(이미 더한 커밋 태그는 같은 값으로 다시 더한다).
            withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
              for (arch in ['arm64', 'amd64']) {
                def ok = sh(returnStatus: true, script: "CODEMIT_IMAGES_MODE=retag bash scripts/ci/images.sh ${arch}") == 0
                if (ok && allSkipped(arch)) {
                  env."IMAGES_${arch.toUpperCase()}_RETAGGED" = 'true'
                  stash name: "ctx-${arch}", includes: ".images-${arch}.ctx", allowEmpty: true
                  if (arch == 'amd64') { readImageResult('amd64') }
                  echo "${arch}: 전부 건너뛴다 — 커밋 태그만 더했다, 「이미지」 가지를 돌지 않는다."
                }
              }
            }
          }
        }
        sh 'git -c safe.directory="$PWD" log -1 --oneline'
      }
    }

    stage('이미지') {
      when {
        beforeAgent true
        expression { env.DOCS_ONLY != 'true' }
      }
      // 하나가 실패해도 다른 아키텍처는 끝까지 굽는다 — 실패 원인을 한 번에 본다. 둘 다 초록이어야
      // 넘어간다: staging 이 초록이면 곧 production 을 앞당기므로 그때 prod(arm64) 이미지가 있어야 한다.
      failFast false
      parallel {
        stage('arm64 — prod (macos)') {
          when {
            beforeAgent true
            expression { env.IMAGES_ARM64_RETAGGED != 'true' }
          }
          agent { label 'macos' }
          options { timeout(time: 60, unit: 'MINUTES') }
          steps {
            pin()
            withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
              sh 'bash scripts/ci/images.sh arm64'
            }
            // 구운 것의 ctx 태그 목록 — 「문맥 태그」 단계가 sub 에서 붙인다.
            stash name: 'ctx-arm64', includes: '.images-arm64.ctx', allowEmpty: true
          }
        }
        stage('amd64 — staging (sub)') {
          when {
            beforeAgent true
            expression { env.IMAGES_AMD64_RETAGGED != 'true' }
          }
          // 배포 워크스페이스(`workspace/codemit-deploy-staging`, `docker/.env.staging` 이 있다)와 겹치지 않게 따로 둔다.
          agent { node { label 'laurio-staging'; customWorkspace 'codemit-deploy-staging-images' } }
          options { timeout(time: 60, unit: 'MINUTES') }
          steps {
            pin()
            withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
              sh 'bash scripts/ci/images.sh amd64'
            }
            script { readImageResult('amd64') }
            stash name: 'ctx-amd64', includes: '.images-amd64.ctx', allowEmpty: true
          }
        }
      }
    }

    // 방금 올린 staging 이미지를 ghcr 에서 받아, 설정 없이는 죽고 완전한 설정으로는 뜨는지 본다.
    // 이번에 굽지 않은(건너뛴) 앱은 보지 않는다 — ctx 태그는 가드까지 초록인 빌드만 붙이므로(「문맥 태그」)
    // 건너뛴 앱의 이미지는 이미 한 번 지났다.
    stage('부팅 가드') {
      when {
        beforeAgent true
        expression {
          env.DOCS_ONLY != 'true' && (env.IMAGE_AMD64_FRONTEND == 'built' ||
            env.IMAGE_AMD64_OPERATOR == 'built' || env.IMAGE_AMD64_CLASSROOM == 'built')
        }
      }
      agent { node { label 'laurio-staging'; customWorkspace 'codemit-deploy-staging-images' } }
      options { timeout(time: 20, unit: 'MINUTES') }
      stages {
        stage('가드 준비') {
          steps { pin() }
        }
        stage('frontend 가드') {
          when { expression { env.IMAGE_AMD64_FRONTEND == 'built' } }
          steps {
            withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
              sh 'bash scripts/ci/deploy-guard.sh frontend'
            }
          }
        }
        stage('operator 가드') {
          when { expression { env.IMAGE_AMD64_OPERATOR == 'built' } }
          steps {
            withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
              sh 'bash scripts/ci/deploy-guard.sh operator'
            }
          }
        }
        stage('classroom 가드') {
          when { expression { env.IMAGE_AMD64_CLASSROOM == 'built' } }
          steps {
            withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
              sh 'bash scripts/ci/deploy-guard.sh classroom'
            }
          }
        }
      }
    }

    // 이미지 두 가지와 부팅 가드가 초록이면 이번에 구운 이미지에 ctx 태그를 붙인다 — 다음 빌드가 그 문맥을
    // 「건너뛴다」로 두는 근거다. 앞 단계가 하나라도 빨가면 여기 닿지 않고, ctx 가 없는 그 이미지들은 다음
    // 빌드가 다시 굽고 가드도 다시 돈다(가드가 빨간 커밋을 그대로 다시 돌려도 같다). 가드가 없는 서비스
    // (backend·search·pgbouncer, 세 앱의 prod 이미지)도 여기서 함께 — 한 가지가 빨간 채 다른 가지가 ctx 를
    // 남기면 그 서비스를 다음에 건너뛰어 버린다. 배포 실패는 이미지 탓이 아니므로 앞당기기·배포보다 먼저 붙인다.
    stage('문맥 태그') {
      // 두 가지 모두 「대상 확인」의 retag 로 끝났으면 구운 것이 없어 붙일 ctx 도 없다 — 노드를 잡지 않는다.
      when {
        beforeAgent true
        expression {
          env.DOCS_ONLY != 'true' && !(env.IMAGES_ARM64_RETAGGED == 'true' && env.IMAGES_AMD64_RETAGGED == 'true')
        }
      }
      agent { node { label 'laurio-staging'; customWorkspace 'codemit-deploy-staging-images' } }
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        pin()
        unstash 'ctx-amd64'
        unstash 'ctx-arm64'
        withCredentials([string(credentialsId: 'ghcr-push-token', variable: 'GHCR_TOKEN')]) {
          sh 'bash scripts/ci/images-ctx.sh .images-amd64.ctx .images-arm64.ctx'
        }
      }
    }

    // `staging` 브랜치는 배포 기록이다 — 이미지와 가드가 초록인 main 의 커밋만 그리로 간다. 늦게 끝난
    // 옛 커밋이면 아무것도 하지 않고, 브랜치가 main 에서 갈라져 있으면 밀어붙이지 않고 빨갛게 멈춘다.
    // 토큰은 production 을 앞당기는 것과 같다(Contents 쓰기).
    stage('staging 앞당기기') {
      when {
        beforeAgent true
        expression { env.DOCS_ONLY != 'true' && !params.IMAGES_ONLY }
      }
      agent { label 'built-in' }
      steps {
        withCredentials([usernamePassword(credentialsId: 'github-sandcorporation-token', usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
          sh 'python3 scripts/ci/fast_forward.py staging "$DEPLOY_SHA"'
        }
      }
    }

    stage('staging 배포') {
      when {
        beforeAgent true
        expression { env.DOCS_ONLY != 'true' && !params.IMAGES_ONLY }
      }
      agent { label 'built-in' }
      stages {
        stage('Preflight') {
          steps {
            pin()
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

        stage('이미지 받기') {
          when { expression { env.DEPLOY_ANY == 'true' } }
          // 하나가 실패해도 나머지는 끝까지 받는다 — 한 번에 실패 원인을 전부 본다.
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
            script { env.STAGING_DEPLOYED = 'true' }   // 디스코드 알림이 staging 결과를 prod 와 따로 적는 근거
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
    }

    // staging 에서 초록이었던 **그 커밋**(DEPLOY_SHA)을 prod 로 보낸다 — 단계는 위 staging 배포와 같고 대상만
    // `prod`(docker/compose.prod.yaml, docker/.env.prod, 배포 표식 .jenkins-prod-deployed)다. 2026-10-23(#779)
    // 전에는 별도 잡 `codemit-deploy-prod` 가 `production` 브랜치의 웹훅으로 돌았다 — 같은 단계의 복제였고,
    // 「prod 는 staging 이 배포한 그 커밋을 따라가야 한다」는 조건을 브랜치 한 다리로 건넜다. 같은 빌드의
    // 단계면 같은 DEPLOY_SHA 라 저절로 만족한다.
    //
    // **어디서 도는가.** prod 스택이 떠 있는 Oracle A1 호스트다 — 이 컨트롤러에 붙은 인바운드 에이전트
    // `oracle` 이 거기서 돈다. 에이전트는 호스트의 `jenkins-desktop-agent` 컨테이너(root, 호스트 docker 소켓,
    // docker CLI·compose·buildx·git 포함 — 이미지 정의는 호스트의 `/server/jenkins`)이고, 호스트의
    // `/var/jenkins_home/workspace` 가 컨테이너의 `/home/jenkins/agent/workspace` 로 붙어 있다. 그래서 노드의
    // Remote root directory 는 **컨테이너 안 경로** `/home/jenkins/agent` 여야 하고, 워크스페이스는
    // `customWorkspace 'workspace/codemit-deploy-prod'`(옛 잡의 이름 — #708 전에는 `codemit`)여야 호스트의
    // `/var/jenkins_home/workspace/codemit-deploy-prod` 가 된다 — 거기에 사람이 둔 `docker/.env.prod`(chmod 600)와
    // 배포 표식이 있다(`deploy.sh` 의 `ENV_FILE="docker/.env.${TARGET}"`). 경로가 바뀌면 preflight 가 멈춘다.
    // **상대 경로는 노드의 Remote root 기준이지 그 아래 `workspace/` 가 아니다** — `'codemit-deploy-prod'` 로 뒀더니
    // `/home/jenkins/agent/codemit-deploy-prod` 에 새로 clone 해 「docker/.env.prod 이 없다」로 멈췄다(2026-10-23 #520).
    // 서버의 파일은 옮기지 않는다. 컨트롤러에서 돌면 prod 가 아니라 sub 호스트에 스택을 띄우므로 `built-in` 을
    // 쓰지 않는다.
    stage('prod 배포') {
      when {
        beforeAgent true
        expression { env.DOCS_ONLY != 'true' && !params.IMAGES_ONLY && params.PROMOTE_PRODUCTION }
      }
      agent { node { label 'oracle'; customWorkspace 'workspace/codemit-deploy-prod' } }
      stages {
        stage('prod Preflight') {
          steps {
            script { env.PROD_DEPLOY = 'running' }
            pin()
            sh "sh ./deploy.sh ${prodTarget} preflight"
          }
        }

        stage('prod 변경 계획') {
          steps {
            sh "sh ./deploy.sh ${prodTarget} plan"
            script {
              // staging 의 계획이 env 에 남아 있다 — prod 의 계획 파일이 같은 키 전부를 다시 적는다(deploy.sh plan).
              readFile(".jenkins-${prodTarget}-plan").split('\n').each { line ->
                def parts = line.split('=', 2)
                if (parts.length == 2) { env."${parts[0].trim()}" = parts[1].trim() }
              }
            }
          }
        }

        stage('prod 이미지 받기') {
          when { expression { env.DEPLOY_ANY == 'true' } }
          parallel {
            stage('prod backend') {
              when { expression { env.BUILD_BACKEND == 'true' } }
              steps { sh "sh ./deploy.sh ${prodTarget} image backend" }
            }
            stage('prod frontend') {
              when { expression { env.BUILD_FRONTEND == 'true' } }
              steps { sh "sh ./deploy.sh ${prodTarget} image frontend" }
            }
            stage('prod operator') {
              when { expression { env.BUILD_OPERATOR == 'true' } }
              steps { sh "sh ./deploy.sh ${prodTarget} image operator" }
            }
            stage('prod classroom') {
              when { expression { env.BUILD_CLASSROOM == 'true' } }
              steps { sh "sh ./deploy.sh ${prodTarget} image classroom" }
            }
            stage('prod search') {
              when { expression { env.BUILD_SEARCH == 'true' } }
              steps { sh "sh ./deploy.sh ${prodTarget} image search" }
            }
          }
        }

        stage('prod 교체') {
          when { expression { env.DEPLOY_ANY == 'true' } }
          steps {
            sh "sh ./deploy.sh ${prodTarget} up"
          }
        }

        stage('prod 확인') {
          when { expression { env.DEPLOY_ANY == 'true' } }
          stages {
            stage('prod 컨테이너') {
              steps { sh "sh ./deploy.sh ${prodTarget} verify" }
            }
            stage('prod backend 응답') {
              steps { sh "sh ./deploy.sh ${prodTarget} health backend" }
            }
            stage('prod events 응답') {
              steps { sh "sh ./deploy.sh ${prodTarget} health events" }
            }
            stage('prod search 응답') {
              steps { sh "sh ./deploy.sh ${prodTarget} health search" }
            }
            stage('prod 검색 재색인') {
              when { expression { env.BUILD_SEARCH == 'true' || env.BUILD_BACKEND == 'true' } }
              steps { sh "sh ./deploy.sh ${prodTarget} reindex" }
            }
            // 떠 있는 앱·backend 가 열차의 e2e 가 본 그 이미지인지(#729) — 관측만, 다르다고 붉히지 않는다.
            stage('prod e2e 대조') {
              steps {
                catchError(buildResult: null, stageResult: null, message: 'e2e 대조를 하지 못했다 — 배포와 무관하다') {
                  sh "sh ./deploy.sh ${prodTarget} e2e-digest"
                }
              }
            }
          }
        }

        stage('prod 배포 표식') {
          steps {
            sh "sh ./deploy.sh ${prodTarget} mark"
            script { env.PROD_DEPLOY = 'done' }
          }
        }

        // 위 staging 의 「정리」와 같다. **이 파일과 deploy.sh 가 다른 커밋에서 온다**(파이프라인은 main 의
        // 최신에서 읽고 deploy.sh 는 DEPLOY_SHA 를 체크아웃해 쓴다) — prune 이 생기기 전 커밋을 배포한 빌드가
        // 「알 수 없는 명령」으로 빨갛게 끝났다(2026-09-17, 교체·확인·표식은 다 끝난 뒤였다).
        stage('prod 정리') {
          steps {
            sh "sh ./deploy.sh ${prodTarget} prune || echo '정리를 건너뛴다 — 배포 결과와 무관하다'"
          }
        }
      }
    }

    // `production` 은 「prod 에 배포된 커밋」의 기록이다(`ghcr_prune.py` 가 그 이미지를 지키는 근거이기도 하다)
    // — 그래서 prod 배포가 초록으로 끝난 **뒤에** 앞당긴다(#779 전에는 배포 **전**에 앞당겨 웹훅으로 prod 잡을
    // 깨웠다). 이 push 는 이제 아무 잡도 깨우지 않는다. 토큰은 staging 앞당기기와 같다(Contents 쓰기).
    // 실패하면 빌드가 빨갛다 — prod 는 바뀌었는데 기록이 따라가지 않은 상태라 사람이 봐야 한다.
    stage('production 앞당기기') {
      when {
        beforeAgent true
        expression { env.DOCS_ONLY != 'true' && !params.IMAGES_ONLY && params.PROMOTE_PRODUCTION }
      }
      agent { label 'built-in' }
      steps {
        withCredentials([usernamePassword(credentialsId: 'github-sandcorporation-token', usernameVariable: 'GH_USER', passwordVariable: 'GH_TOKEN')]) {
          sh 'python3 scripts/ci/fast_forward.py production "$DEPLOY_SHA"'
        }
      }
    }
  }

  post {
    // **빌드가 끝나면 디스코드로 결과를 보낸다**(2026-09-18). 배포는 사람이 화면을
    // 보고 있지 않을 때 도는 일이라, 끝났다는 사실이 사람에게 닿는 자리가 없었다 —
    // 실패는 더더욱 그렇다(2026-09-17 staging 배포가 정리 단계에서 빨갛게 끝난 것을
    // 한참 뒤에 알았다). 문서만 바뀐 빌드는 보내지 않는다 — 한 일이 없다.
    //
    // **웹훅 주소는 저장소에 두지 않는다** — Jenkins 자격증명(Secret text)
    // `discord-deploy-webhook` 에 있고, 여기서는 이름으로만 부른다. 그 값을 아는
    // 사람은 그 채널에 아무 말이나 올릴 수 있으므로 커밋에 남기면 안 된다.
    //
    // **알림이 실패해도 빌드 결과를 뒤집지 않는다** — `|| true` 와
    // `catchError` 가 그 역할이다. 자격증명이 없는 Jenkins(새로 세운 것 등)에서도
    // 배포 자체는 그대로 돌아야 한다.
    always {
      script {
        if (env.DOCS_ONLY == 'true' && currentBuild.currentResult == 'SUCCESS') { return }
        node('built-in') {
          catchError(buildResult: null, stageResult: null, message: '디스코드 알림 실패 — 배포 결과와 무관하다') {
            withCredentials([string(credentialsId: 'discord-deploy-webhook', variable: 'DISCORD_WEBHOOK')]) {
              def result = currentBuild.currentResult
              def mark = result == 'SUCCESS' ? '✅' : (result == 'ABORTED' ? '⚪' : '❌')
              def sha = (env.DEPLOY_SHA ?: '').take(12)
              def took = currentBuild.durationString.replace(' and counting', '')
              def what = params.IMAGES_ONLY ? '이미지' : '배포'
              // staging 과 prod 를 한 줄에 — 예: `✅ staging 배포 SUCCESS · prod 배포 SUCCESS — #N (sha)`.
              // prod 를 돌리지 않은 빌드는 staging 만 적는다. staging 표식까지 간 뒤 prod 나 production
              // 앞당기기에서 붉어진 빌드는 어디서 붉어졌는지 그 자리에 적는다.
              def stagingResult = env.STAGING_DEPLOYED == 'true' ? 'SUCCESS' : result
              def prodPart = env.PROD_DEPLOY == 'done' ? ' · prod 배포 SUCCESS' :
                (env.PROD_DEPLOY == 'running' ? " · prod 배포 ${result}" : '')
              if (env.PROD_DEPLOY == 'done' && result != 'SUCCESS') { prodPart += " · production 앞당기기 ${result}" }
              def text = "${mark} staging ${what} ${stagingResult}${prodPart} — #${env.BUILD_NUMBER}" +
                (sha ? " (${sha})" : '') + " · ${took} · ${env.BUILD_URL}"
              // 본문은 JSON 이라 따옴표·역슬래시를 그대로 실으면 깨진다 — Groovy 가
              // 만들어 준 문자열을 셸이 다시 해석하지 않도록 파일로 넘긴다.
              writeFile file: 'discord-payload.json', text: groovy.json.JsonOutput.toJson([content: text])
              sh 'curl -sS -X POST -H "Content-Type: application/json" --data @discord-payload.json "$DISCORD_WEBHOOK" > /dev/null || true'
            }
          }
        }
      }
    }
    failure {
      echo '실패 — staging·production 은 이 커밋으로 옮기지 않았거나(앞 단계) 그 대상의 배포 표식을 옮기지 않았다(staging·prod 배포 단계). 다음 빌드가 같은 범위를 다시 시도한다.'
    }
  }
}
