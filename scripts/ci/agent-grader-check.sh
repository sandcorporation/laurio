#!/usr/bin/env bash
# agent-grader 이미지·서비스 검사(#999) — PR 검사의 `agent-grader` 잡(arm64 실행기)이 부른다. 로컬 mac(arm64)에서도 돈다.
#
#   1. 이미지를 굽는다(이 실행기의 아키텍처 — 잡은 ubuntu-24.04-arm 이라 운영과 같은 arm64).
#   2. 컨테이너 안에서 두 CLI 의 `--version` 과 `selfcheck`(키 env·자격증명 파일 없음, 고정 버전), 그리고 운영 확인 한 줄
#      (Codex 샌드박스만, docs/ops/deploy.md).
#   3. 운영과 같은 격리 설정으로 실행기를 `agent` 내부 네트워크에 세우고, 밖으로 직접 나가지 못하는지 본다.
#   4. `llm-proxy` 자리의 가짜 벤더로 Claude Code·Codex 를 한 번씩 돌린다(`agent_grader_check.py`).
#
# 환경변수: AGENT_GRADER_IMAGE(기본 codemit-agent-grader:check), AGENT_GRADER_SKIP_BUILD=1 이면 굽지 않는다.
set -euo pipefail
echo "#1139 시험: 일부러 실패"; exit 1
cd "$(dirname "$0")/../.."

export AGENT_GRADER_IMAGE="${AGENT_GRADER_IMAGE:-codemit-agent-grader:check}"
compose=(docker compose -f docker/compose.agent-grader-check.yaml)

cleanup() {
  "${compose[@]}" --profile driver logs --no-color agent-grader llm-proxy 2>/dev/null | tail -n 60 || true
  "${compose[@]}" --profile driver down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [ "${AGENT_GRADER_SKIP_BUILD:-0}" != 1 ]; then
  echo "== 이미지 굽기 ($(uname -m))"
  docker build -q -f docker/agent-grader.Dockerfile -t "$AGENT_GRADER_IMAGE" .
fi
docker image inspect -f 'arch={{.Architecture}} size={{.Size}}' "$AGENT_GRADER_IMAGE"

echo "== CLI 버전·selfcheck(운영과 같은 읽기 전용 루트)"
"${compose[@]}" run --rm --no-deps -T agent-grader sh -c 'claude --version && codex --version'
"${compose[@]}" run --rm --no-deps -T agent-grader python3 /app/agent_runner.py selfcheck

echo "== Codex 샌드박스(bwrap)만 — 운영 확인 한 줄과 같은 꼴(docs/ops/deploy.md 「agent-grader 샌드박스 확인」, 이미지 자리만 다르다)"
# 운영과 같은 제한(비루트·read_only·tmpfs·mem 1536m·cap_drop ALL·no-new-privileges·seccomp 프로필), 벤더·키·네트워크 없이
# 빈 폴더를 읽고 끝난다. 실패하면 bwrap 이 막힌 단계를 한 줄로 찍는다. 운영 줄과 다른 것은 AppArmor 하나 — 이
# 실행기(Ubuntu)의 docker 기본 AppArmor 프로필이 mount 를 막는다(「Failed to make / slave: Permission denied」, 검사
# compose 의 apparmor:unconfined 와 같은 까닭). AppArmor 가 없는 호스트(운영·mac)에서는 붙이지 않는다.
apparmor=()
if [ -e /sys/kernel/security/apparmor ]; then apparmor=(--security-opt apparmor=unconfined); fi
probe=$(docker run ${apparmor[@]+"${apparmor[@]}"} --rm --read-only --tmpfs /work:size=768m,mode=0700,uid=10001,gid=10001 --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges:true --security-opt seccomp=docker/agent-grader-seccomp.json --memory 1536m --pids-limit 512 --network none --entrypoint sh "$AGENT_GRADER_IMAGE" -c 'mkdir -p /work/probe/home /work/probe/empty && cd /work/probe/empty && HOME=/work/probe/home codex sandbox -- ls -A /work/probe/empty && echo agent-grader-sandbox-ok' 2>&1) || true
echo "$probe"
if [ "$probe" != agent-grader-sandbox-ok ]; then
  echo "FAIL: Codex 샌드박스가 운영과 같은 제한에서 뜨지 않았다"
  exit 1
fi
echo "  ok   빈 폴더를 읽고 끝났다"

echo "== 밖으로 직접 나가지 못한다(agent 는 internal 네트워크)"
if "${compose[@]}" run --rm --no-deps -T agent-grader python3 -c \
  "import socket; socket.create_connection(('1.1.1.1', 443), 5)" >/dev/null 2>&1; then
  echo "FAIL: agent-grader 에서 1.1.1.1:443 에 닿았다"
  exit 1
fi
echo "  ok   1.1.1.1:443 에 닿지 못한다"

echo "== 가짜 벤더로 두 CLI"
"${compose[@]}" --profile driver up -d agent-grader llm-proxy
"${compose[@]}" --profile driver run --rm -T driver
