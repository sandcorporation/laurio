#!/bin/bash
# macos 노드의 PR CI 단계 첫머리 — 앞 빌드가 남긴 스택과 디스크를 걷는다(2026-10-03).
#
# e2e.sh·celery-broker.sh 는 끝날 때 trap 으로 스택을 지우지만, Jenkins 가 빌드를 중단하면
# 프로세스 나무를 곧장 죽여 trap 이 돌지 못한다. 그렇게 남은 스택 둘(볼륨 400여 개·30GB)이
# Docker VM 디스크를 채워 MinIO 가 XMinioStorageFull 로 업로드를 거절했고, 열린 PR 넷이
# 코드와 무관하게 e2e 에서 붉어졌다. 이 노드는 실행기가 하나라 지금 도는 PR 빌드는 이 빌드
# 하나뿐이므로, 이름이 jenkins-codemit-pr-·jenkins-codemit-train- 으로 시작하는 compose 프로젝트는 전부 남은 것이다.
# 다른 프로젝트(web-rpg·러너 컨테이너)는 건드리지 않는다(이미지도 이름이 jenkins-codemit- 인 것만). 무엇이 실패해도 0 으로 끝난다.
set -u
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin"

for p in $(docker ps -a --format '{{.Label "com.docker.compose.project"}}' | grep -E '^jenkins-codemit-(pr|train)-' | sort -u); do
  echo "남은 스택을 걷는다: $p"
  docker ps -aq --filter "label=com.docker.compose.project=$p" | xargs -r docker rm -f -v >/dev/null 2>&1
  docker volume ls -q --filter "label=com.docker.compose.project=$p" | xargs -r docker volume rm >/dev/null 2>&1
  docker network ls -q --filter "label=com.docker.compose.project=$p" | xargs -r docker network rm >/dev/null 2>&1
done
# 컨테이너 없이 남은 이 저장소의 볼륨(스택은 지워졌는데 볼륨만 남은 경우)
docker volume ls -q --filter label=com.docker.compose.project | while read -r v; do
  proj=$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$v" 2>/dev/null)
  case "$proj" in jenkins-codemit-pr-*|jenkins-codemit-train-*) docker volume rm "$v" >/dev/null 2>&1 ;; esac
done
# 중단된 빌드가 남긴 이미지(2026-10-14) — e2e.sh·celery-broker.sh 는 내릴 때 구운 이미지를 지우지만
# (`--rmi local`) trap 이 못 돌면 jenkins-codemit-(pr|train)-<번호>-<밀리초>-e2e-<서비스> 가 남는다.
# 태그가 있어 `image prune` 에 걸리지 않는다. 어떤 컨테이너도 쓰지 않는 것만 지운다.
in_use=$(docker ps -a --format '{{.Image}}' | sort -u)
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E '^jenkins-codemit-(pr|train)-' | while read -r img; do
  grep -qxF "$img" <<<"$in_use" && continue
  grep -qxF "${img%:latest}" <<<"$in_use" && continue
  docker image rm "$img" >/dev/null 2>&1
done
docker image prune -f >/dev/null 2>&1
# 빌드 캐시는 나이가 아니라 크기로 자른다 — 오래 안 바뀐 의존성 층이 72시간을 넘겼다고 지워지면
# 다음 굽기가 처음부터다. 묶음이 캐시 히트로 도는 지금 캐시가 21.6GB 라 30GB 를 상한으로 두고,
# 넘치면 오래 안 쓴 것부터 버린다. VM 디스크 96GiB 가운데 이미지(정리 뒤 ~10GB)·스택 볼륨과 함께
# 쓰고도 절반 넘게 남는다.
docker builder prune -f --keep-storage 30GB >/dev/null 2>&1
docker system df 2>/dev/null || true
exit 0
