#!/usr/bin/env bash
# 배포 잡(`codemit/deploy`)의 oracle 쪽 — jenkins-shared `sandcorpDeploy` 의 `deployScript`(#873, ADR-0071).
# 라이브러리가 oracle 노드의 `workspace/codemit-deploy-prod`(사람이 둔 `docker/.env.prod`·배포 표식이 있는 자리)에서
# 배포할 커밋을 체크아웃하고 이것을 부른다. 논리는 여전히 `deploy.sh` 에 있다 — 여기는 그 명령을 예전 Jenkinsfile 의
# 단계 순서대로 부를 뿐이다:
#
#   preflight → plan → (바뀐 것이 있으면) image <서비스>… → up → verify → health backend·events·search →
#   (search·backend 를 바꿨으면) reindex → mark → GlitchTip 해결 표시 → prune(이 둘은 실패해도 넘어간다)
#
# 평소에는 라이브러리가 production 머리를 이미지 빌드 없이 넘긴다(`deployFrom`, #938 — 이미지는 Actions 의 image.yml 이 굽는다).
# 그때는 빌드 노드 단계가 없어 문맥 해시(`CODEMIT_CTX_*`)가 오지 않고, `deploy.sh plan` 은 경로 비교로 간다.
# GlitchTip 해결 표시(`glitchtip-resolve.sh`)는 직전 배포 표식 → 이 커밋 범위다 — 쓰기 토큰은 `docker/.env.prod` 의
# `GLITCHTIP_TOKEN_FOR_AUTOMATION`(없으면 표시만 건너뛴다).
#
# 「문서만」 병합은 `plan` 이 배포 표식(`.jenkins-prod-deployed`, = 직전 성공 배포) 기준으로 바뀐 서비스가 없다고
# 내고(DEPLOY_ANY=false), 교체 없이 표식만 옮긴다 — 컨테이너는 그대로다.
#
# 종료 코드는 라이브러리 약속(README 「자동 롤백」)을 따른다: 0 성공 · 1 교체 전 실패(옛 서비스 그대로) ·
# 2 교체 뒤 실패(되돌리지 않는다 — Jenkinsfile 의 `autoRollback: false`). `SANDCORP_ROLLBACK=1` 로 불리면 거절한다.
#
# **배포 뒤 확인·자동 되돌리기(#1092)는 스위치 `CODEMIT_POSTDEPLOY` 뒤에 있다 — 기본 off 는 위 순서 그대로다.**
# check 면 reindex 뒤 `post-deploy-check.sh`(1분 한도)를 돌려 실패를 2 로 끝내고, rollback 이면 교체 뒤 실패(up 부터
# 확인까지 어디서든)를 직전 배포 표식의 이미지로 되돌린 뒤 2 로 끝낸다(`deploy.sh rollback-plan` →
# `post-deploy-rollback.sh`). 라이브러리의 되돌리기(`autoRollback`)는 그대로 끈다 — 되돌리기는 이 스크립트 안에서 한다.
#
# 라이브러리가 넘기는 `COMPOSE_PROJECT_NAME`·`COMPOSE_FILE` 은 지운다 — deploy.sh 는 `-f docker/compose.prod.yaml` 과
# 그 파일의 `name: codemit-prod` 를 쓴다. 문맥 해시(`CODEMIT_CTX_*`)는 더 이상 Jenkins 배포 단계에서 만들거나 전달하지 않는다.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
unset COMPOSE_PROJECT_NAME COMPOSE_FILE
# Jenkins is deployment-only: ignore any local-build override and pull the
# Actions-published GHCR artifacts checked by sandcorpDeploy's image wait.
unset DEPLOY_IMAGE_SOURCE

if [ "${SANDCORP_ROLLBACK:-0}" = 1 ]; then
  echo "자동 롤백은 끈 저장소다(autoRollback: false) — 부르지 않아야 한다"
  exit 1
fi

GIT=(git -c safe.directory="$PWD")
# 직전 성공 배포(배포 표식) — mark 가 옮기기 전에 읽어 둔다. GlitchTip 해결 표시의 범위 시작이다.
previous_deployed=$(cat .jenkins-prod-deployed 2>/dev/null || true)
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

# 스위치(off|check|rollback, 기본 off) — 확인 스크립트가 없는 옛 커밋(ROLLBACK_SHA)은 off 다.
postdeploy=off
if [ -f scripts/ci/post-deploy-check.sh ]; then
  postdeploy=$(bash scripts/ci/post-deploy-check.sh --mode) || exit 1
fi

# 교체 뒤 실패 — off·check 는 지금처럼 2 로 끝내고, rollback 이면 직전 배포 표식으로 되돌린다. 뒤로 가는 배포
# (ROLLBACK_SHA — 표식이 이 커밋보다 새것)는 되돌리지 않는다: 표식이 바로 피하려던 커밋이다.
after_replace_failed() {
  [ "$postdeploy" = rollback ] || exit 2
  echo "교체 뒤 실패($1) — 직전 배포 표식으로 되돌린다"
  if [ -z "$previous_deployed" ] || "${GIT[@]}" merge-base --is-ancestor "$sha" "$previous_deployed" 2>/dev/null; then
    echo "되돌릴 곳이 없다(배포 표식 ${previous_deployed:-없음}) — 되돌리지 않는다"
    exit 2
  fi
  run rollback-plan || exit 2
  local tmp
  tmp=$(mktemp -d) || exit 2
  cp scripts/ci/post-deploy-rollback.sh scripts/ci/post-deploy-check.sh "$tmp/" || exit 2
  exec bash "$tmp/post-deploy-rollback.sh" "$previous_deployed" "$sha" "$tmp/post-deploy-check.sh"
}

run preflight || exit 1
run plan || exit 1

# plan 이 남긴 `KEY=value` 줄(.jenkins-prod-plan) — 이 스크립트는 교체 여부와 서비스별 받기만 읽는다.
declare -A plan=()
while IFS='=' read -r key value; do
  case "$key" in DEPLOY_ANY|BUILD_[A-Z]*) plan[$key]=$value ;; esac
done < .jenkins-prod-plan
pulls=""
for svc in backend frontend operator classroom search agent-grader; do
  flag="BUILD_$(printf '%s' "$svc" | tr '[:lower:]-' '[:upper:]_')"
  [ "${plan[$flag]:-false}" = true ] && pulls="$pulls $svc"
done
echo "계획: 교체 ${plan[DEPLOY_ANY]:-false} · 받을 이미지:${pulls:- 없음}"

replaced=1
if [ "${plan[DEPLOY_ANY]:-false}" = true ]; then
  # 받기는 서비스마다 나란히 — 하나가 실패해도 나머지를 끝까지 받아 실패 원인을 한 번에 본다.
  pids=()
  names=()
  for svc in backend frontend operator classroom search agent-grader; do
    flag="BUILD_$(printf '%s' "$svc" | tr '[:lower:]-' '[:upper:]_')"
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
  run up || after_replace_failed up
  run verify || after_replace_failed verify
  run health backend || after_replace_failed "health backend"
  run health events || after_replace_failed "health events"
  run health search || after_replace_failed "health search"
  if [ "${plan[BUILD_SEARCH]:-false}" = true ] || [ "${plan[BUILD_BACKEND]:-false}" = true ]; then
    run reindex || after_replace_failed reindex
  fi
  if [ "$postdeploy" != off ]; then
    echo "== 배포 뒤 확인 ($postdeploy)"
    bash scripts/ci/post-deploy-check.sh || after_replace_failed "배포 뒤 확인"
  fi
else
  echo "바뀐 서비스가 없다(문서만 등) — 교체하지 않고 배포 표식만 옮긴다"
fi

run mark || exit "$replaced"
bash scripts/ci/glitchtip-resolve.sh "$previous_deployed" "$sha" docker/.env.prod || echo "GlitchTip 표시 실패 — 배포와 무관하다"
run prune || echo "정리를 건너뛴다 — 배포 결과와 무관하다"
exit 0
