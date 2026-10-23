#!/bin/bash
# macos 노드의 열차 단계 첫머리 — 앞 빌드가 남긴 스택과 디스크를 걷는다(2026-10-03).
#
# e2e.sh·celery-broker.sh 는 끝날 때 trap 으로 스택을 지우지만, Jenkins 가 빌드를 중단하면
# 프로세스 나무를 곧장 죽여 trap 이 돌지 못한다. 그렇게 남은 스택 둘(볼륨 400여 개·30GB)이
# Docker VM 디스크를 채워 MinIO 가 XMinioStorageFull 로 업로드를 거절했고, 열린 PR 넷이
# 코드와 무관하게 e2e 에서 붉어졌다. 이 노드는 실행기가 하나라 지금 도는 PR 빌드는 이 빌드
# 하나뿐이므로, 이름이 jenkins-codemit-ci-pr-·jenkins-codemit-ci-train- 으로 시작하는 compose 프로젝트는 전부 남은 것이다.
# 다른 프로젝트(web-rpg·러너 컨테이너)는 건드리지 않는다(이미지도 이름이 jenkins-codemit- 인 것만). 무엇이 실패해도 0 으로 끝난다.
#
# 이름은 Jenkins 의 BUILD_TAG(`jenkins-<잡 이름>-<번호>`)에서 온다(CODEMIT_CI_RUN_ID, e2e.sh·celery-broker.sh).
# #708(2026-10-15)이 잡 이름을 codemit-pr → codemit-ci-pr, codemit-train → codemit-ci-train 으로 바꿨다.
# #780(2026-10-23)이 잡을 폴더 codemit/ 로 옮겨 ci-pr·ci-train 이 됐지만 BUILD_TAG 는 전체 이름의 / 를 - 로 바꾼
# jenkins-codemit-ci-pr-N·jenkins-codemit-ci-train-N 그대로라 아래 패턴은 바뀌지 않았다.
# **옛 이름 jenkins-codemit-(pr|train)- 도 같이 걷는다** — rename 직전에 중단된 빌드가 남긴 것이다.
# 지울 때: rename 뒤 macos 에서 `docker ps -a`·`docker volume ls`·`docker image ls` 에 옛 이름이 하나도
# 없음을 본 뒤 아래 PAT 에서 `|pr|train` 을 빼고 `ci-(pr|train)` 만 남긴다 — 2026-11-15 이후 #735 로 지운다.
set -u
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin"
PAT='^jenkins-codemit-(ci-pr|ci-train|pr|train)-'

for p in $(docker ps -a --format '{{.Label "com.docker.compose.project"}}' | grep -E "$PAT" | sort -u); do
  echo "남은 스택을 걷는다: $p"
  docker ps -aq --filter "label=com.docker.compose.project=$p" | xargs -r docker rm -f -v >/dev/null 2>&1
  docker volume ls -q --filter "label=com.docker.compose.project=$p" | xargs -r docker volume rm >/dev/null 2>&1
  docker network ls -q --filter "label=com.docker.compose.project=$p" | xargs -r docker network rm >/dev/null 2>&1
done
# 컨테이너 없이 남은 이 저장소의 볼륨(스택은 지워졌는데 볼륨만 남은 경우)
docker volume ls -q --filter label=com.docker.compose.project | while read -r v; do
  proj=$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$v" 2>/dev/null)
  printf '%s\n' "$proj" | grep -qE "$PAT" && docker volume rm "$v" >/dev/null 2>&1
done
# 중단된 빌드가 남긴 이미지(2026-10-14) — e2e.sh·celery-broker.sh 는 내릴 때 구운 이미지를 지우지만
# (`--rmi local`) trap 이 못 돌면 jenkins-codemit-ci-(pr|train)-<번호>-<밀리초>-e2e-<서비스> 가 남는다.
# 태그가 있어 `image prune` 에 걸리지 않는다. 어떤 컨테이너도 쓰지 않는 것만 지운다.
in_use=$(docker ps -a --format '{{.Image}}' | sort -u)
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E "$PAT" | while read -r img; do
  grep -qxF "$img" <<<"$in_use" && continue
  grep -qxF "${img%:latest}" <<<"$in_use" && continue
  docker image rm "$img" >/dev/null 2>&1
done
# 열차가 받아 띄운 배포 이미지(#712, `compose.ci-images.yaml`) — `ghcr.io/sandcorporation/codemit-<서비스>:<sha>-<arch>`.
# 커밋마다 태그가 새로 생기므로 저장소마다 **가장 새것 하나**만 남긴다 — 다음 실행이 받을 때 바뀌지 않은
# 층(의존성·기반 이미지)을 다시 받지 않게 하는 층 캐시다. 컨테이너가 쓰는 것은 건드리지 않는다.
# `docker image ls` 는 새것부터 나온다.
seen=""
docker image ls --format '{{.Repository}} {{.Tag}} {{.ID}}' | grep -E '^ghcr\.io/sandcorporation/codemit-[a-z]+ ' | while read -r repo tag id; do
  case " $seen " in
    *" $repo "*) ;;
    *) seen="$seen $repo"; continue ;;
  esac
  grep -qxF "$repo:$tag" <<<"$in_use" && continue
  docker image rm "$repo:$tag" >/dev/null 2>&1
done
docker image prune -f >/dev/null 2>&1
# 기본 빌더의 캐시는 이제 로컬에서 스택을 굽는 길(CODEMIT_IMAGE_TAG 없이 e2e.sh·celery-broker.sh)만
# 쓴다 — 열차의 이미지는 `images.sh` 의 빌더 `codemit-images` 가 굽고 레지스트리 캐시를 쓰며 그 빌더의
# 캐시는 images.sh 가 스스로 자른다(`CODEMIT_IMAGES_KEEP_STORAGE`). 그래서 30GB 였던 상한을 10GB 로
# 줄인다 — 크기로 자르는 이유는 그대로다(오래 안 바뀐 의존성 층이 나이로 지워지면 처음부터 굽는다).
docker builder prune -f --keep-storage 10GB >/dev/null 2>&1
docker system df 2>/dev/null || true
exit 0
