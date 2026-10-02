#!/bin/bash
# macos 노드의 PR CI 단계 첫머리 — 앞 빌드가 남긴 스택과 디스크를 걷는다(2026-10-03).
#
# e2e.sh·celery-broker.sh 는 끝날 때 trap 으로 스택을 지우지만, Jenkins 가 빌드를 중단하면
# 프로세스 나무를 곧장 죽여 trap 이 돌지 못한다. 그렇게 남은 스택 둘(볼륨 400여 개·30GB)이
# Docker VM 디스크를 채워 MinIO 가 XMinioStorageFull 로 업로드를 거절했고, 열린 PR 넷이
# 코드와 무관하게 e2e 에서 붉어졌다. 이 노드는 실행기가 하나라 지금 도는 PR 빌드는 이 빌드
# 하나뿐이므로, 이름이 jenkins-codemit-pr- 로 시작하는 compose 프로젝트는 전부 남은 것이다.
# 다른 프로젝트(web-rpg·러너 컨테이너)는 건드리지 않는다. 무엇이 실패해도 0 으로 끝난다.
set -u
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin"

for p in $(docker ps -a --format '{{.Label "com.docker.compose.project"}}' | grep '^jenkins-codemit-pr-' | sort -u); do
  echo "남은 스택을 걷는다: $p"
  docker ps -aq --filter "label=com.docker.compose.project=$p" | xargs -r docker rm -f -v >/dev/null 2>&1
  docker volume ls -q --filter "label=com.docker.compose.project=$p" | xargs -r docker volume rm >/dev/null 2>&1
  docker network ls -q --filter "label=com.docker.compose.project=$p" | xargs -r docker network rm >/dev/null 2>&1
done
# 컨테이너 없이 남은 이 저장소의 볼륨(스택은 지워졌는데 볼륨만 남은 경우)
docker volume ls -q --filter label=com.docker.compose.project | while read -r v; do
  proj=$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$v" 2>/dev/null)
  case "$proj" in jenkins-codemit-pr-*) docker volume rm "$v" >/dev/null 2>&1 ;; esac
done
docker image prune -f >/dev/null 2>&1
docker builder prune -f --filter until=72h >/dev/null 2>&1
docker system df 2>/dev/null || true
exit 0
