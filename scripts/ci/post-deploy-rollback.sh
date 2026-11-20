#!/usr/bin/env bash
# 자동 되돌리기(#1092) — 교체 뒤 실패한 배포를 직전 배포 표식의 이미지로 되돌린다. `deploy-prod.sh` 만 부른다
# (스위치 `CODEMIT_POSTDEPLOY=rollback`, scripts/ci/post-deploy-check.sh).
#
#   bash <사본>/post-deploy-rollback.sh <되돌릴 sha> <실패한 sha> <확인 스크립트 사본>
#
# 부르기 전에 `deploy.sh prod rollback-plan` 이 계획 파일을 <되돌릴 sha> 의 것으로 고쳐 둔다(바꿔 끼운 서비스 그대로,
# 겹쳐 바꾸기). 여기서는 그 커밋을 체크아웃하고 deploy.sh 의 `image`·`up`·`verify`·`health` 를 그 커밋의 것으로 부른다 —
# 이미지 태그·compose 가 체크아웃한 커밋을 따른다. 스키마는 되돌리지 않는다(docs/ops/migrations.md).
#
# **이 파일은 임시 사본으로 돈다.** 체크아웃이 저장소의 스크립트를 옛 판으로 바꾸므로, 부르는 쪽이 사본을 `exec`
# 하고 확인 스크립트도 사본을 넘긴다(bash 는 실행 중인 파일을 조금씩 읽는다).
#
# 배포 표식은 옮기지 않는다 — 직전 배포 그대로다. 언제나 2(교체 뒤 실패)로 끝난다: 되돌렸어도 이 배포는
# 실패이고, 잡이 빨갛게 끝나는 것이 알림이다. 되돌리기마저 실패하면 그 단계를 적고 2 로 끝난다.
set -uo pipefail

target="${1:?되돌릴 sha}"
failed_sha="${2:?실패한 sha}"
check="${3:?확인 스크립트 사본}"
GIT=(git -c safe.directory="$PWD")

give_up() {
  echo "!! 자동 되돌리기 실패($1) — ${failed_sha:0:12} → ${target:0:12}. 사람이 본다: docs/ops/deploy.md 「되돌리기」"
  exit 2
}

echo "== 자동 되돌리기: ${failed_sha:0:12} → ${target:0:12}(배포 표식)"
"${GIT[@]}" checkout -q --detach "$target" || give_up "체크아웃"
"${GIT[@]}" log -1 --oneline

run() {
  echo "== deploy.sh prod $* (되돌리기)"
  sh ./deploy.sh prod "$@"
}

declare -A plan=()
while IFS='=' read -r key value; do
  case "$key" in BUILD_[A-Z]*) plan[$key]=$value ;; esac
done < .jenkins-prod-plan

for svc in backend frontend operator classroom search agent-grader; do
  flag="BUILD_$(printf '%s' "$svc" | tr '[:lower:]-' '[:upper:]_')"
  if [ "${plan[$flag]:-false}" = true ]; then
    run image "$svc" || give_up "image $svc"
  fi
done
run up || give_up up
run verify || give_up verify
run health backend || give_up "health backend"
run health events || give_up "health events"
run health search || give_up "health search"
if [ "${plan[BUILD_SEARCH]:-false}" = true ] || [ "${plan[BUILD_BACKEND]:-false}" = true ]; then
  run reindex || give_up reindex
fi
rm -f .jenkins-prod-plan
if bash "$check"; then
  echo "!! 자동 되돌리기 끝 — ${target:0:12} 로 돌아갔다. ${failed_sha:0:12} 배포는 실패다"
else
  echo "!! 자동 되돌리기 뒤에도 확인이 실패한다 — ${target:0:12}. 사람이 본다"
fi
exit 2
