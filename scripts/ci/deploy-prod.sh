#!/usr/bin/env bash
# 배포 잡(`codemit/deploy`)의 oracle 쪽 — jenkins-shared `sandcorpDeploy` 의 `deployScript`(#873, ADR-0071).
# 라이브러리가 oracle 노드의 `workspace/codemit-deploy-prod`(사람이 둔 `docker/.env.prod`·배포 표식이 있는 자리)에서
# 배포할 커밋을 체크아웃하고 이것을 부른다. 논리는 여전히 `deploy.sh` 에 있다 — 여기는 그 명령을 예전 Jenkinsfile 의
# 단계 순서대로 부를 뿐이다:
#
#   preflight → plan → (바뀐 것이 있으면) image <서비스>… → up → verify → health backend·events·search →
#   (search·backend 를 바꿨으면) reindex → e2e-digest(관측만) → mark → prune(실패해도 넘어간다)
#
# 「문서만」 병합은 `plan` 이 배포 표식(`.jenkins-prod-deployed`, = 직전 성공 배포) 기준으로 바뀐 서비스가 없다고
# 내고(DEPLOY_ANY=false), 교체 없이 표식만 옮긴다 — 컨테이너는 그대로다.
#
# 종료 코드는 라이브러리 약속(README 「자동 롤백」)을 따른다: 0 성공 · 1 교체 전 실패(옛 서비스 그대로) ·
# 2 교체 뒤 실패(되돌리지 않는다 — Jenkinsfile 의 `autoRollback: false`). `SANDCORP_ROLLBACK=1` 로 불리면 거절한다.
#
# 라이브러리가 넘기는 `COMPOSE_PROJECT_NAME`·`COMPOSE_FILE` 은 지운다 — deploy.sh 는 `-f docker/compose.prod.yaml` 과
# 그 파일의 `name: codemit-prod` 를 쓴다. 문맥 해시(`CODEMIT_CTX_*`)는 빌드 노드의 `build-images.sh` 가 넘긴다.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
unset COMPOSE_PROJECT_NAME COMPOSE_FILE

if [ "${SANDCORP_ROLLBACK:-0}" = 1 ]; then
  echo "자동 롤백은 끈 저장소다(autoRollback: false) — 부르지 않아야 한다"
  exit 1
fi

GIT=(git -c safe.directory="$PWD")
sha="${SANDCORP_IMAGE_SHA:?SANDCORP_IMAGE_SHA 가 없다 — 라이브러리 deployScript 로만 부른다}"
# 되돌리기(`ROLLBACK_SHA`)는 라이브러리가 지금 main 을 체크아웃해 두고 옛 sha 를 넘긴다. deploy.sh 는 체크아웃한
# 커밋의 이미지(`<sha>-arm64`)와 compose 를 쓰므로 그 커밋으로 옮긴다.
if [ "$("${GIT[@]}" rev-parse HEAD)" != "$sha" ]; then
  "${GIT[@]}" cat-file -e "${sha}^{commit}" 2>/dev/null || { echo "체크아웃에 $sha 가 없다"; exit 1; }
  "${GIT[@]}" checkout -q --detach "$sha" || exit 1
fi
"${GIT[@]}" log -1 --oneline

run() {
  echo "== deploy.sh prod $*"
  sh ./deploy.sh prod "$@"
}

run preflight || exit 1
run plan || exit 1

# plan 이 남긴 `KEY=value` 줄(.jenkins-prod-plan) — 이 스크립트는 교체 여부와 서비스별 받기만 읽는다.
declare -A plan=()
while IFS='=' read -r key value; do
  case "$key" in DEPLOY_ANY|BUILD_[A-Z]*) plan[$key]=$value ;; esac
done < .jenkins-prod-plan

replaced=1
if [ "${plan[DEPLOY_ANY]:-false}" = true ]; then
  # 받기는 서비스마다 나란히 — 하나가 실패해도 나머지를 끝까지 받아 실패 원인을 한 번에 본다.
  pids=()
  names=()
  for svc in backend frontend operator classroom search; do
    flag="BUILD_$(printf '%s' "$svc" | tr '[:lower:]' '[:upper:]')"
    if [ "${plan[$flag]:-false}" = true ]; then
      run image "$svc" &
      pids+=("$!")
      names+=("$svc")
    fi
  done
  failed=""
  for i in "${!pids[@]}"; do
    wait "${pids[$i]}" || failed="$failed ${names[$i]}"
  done
  if [ -n "$failed" ]; then
    echo "이미지를 받지 못했다:$failed — 교체하지 않는다"
    exit 1
  fi

  # 여기부터는 살아 있는 서비스를 바꾼다 — 실패하면 2(교체 뒤 실패).
  replaced=2
  run up || exit 2
  run verify || exit 2
  run health backend || exit 2
  run health events || exit 2
  run health search || exit 2
  if [ "${plan[BUILD_SEARCH]:-false}" = true ] || [ "${plan[BUILD_BACKEND]:-false}" = true ]; then
    run reindex || exit 2
  fi
  run e2e-digest || echo "e2e 대조를 하지 못했다 — 배포와 무관하다"
else
  echo "바뀐 서비스가 없다(문서만 등) — 교체하지 않고 배포 표식만 옮긴다"
fi

run mark || exit "$replaced"
run prune || echo "정리를 건너뛴다 — 배포 결과와 무관하다"
exit 0
