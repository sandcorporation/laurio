#!/bin/bash
# macos 노드의 호스트 상태를 1초마다 적는다(#716) — e2e.sh 가 스택을 띄우기 전에 뒤에서 띄우고 끝에 죽인다.
#
#   scripts/ci/host-sample.sh test-results/host &   # 죽일 때까지 돈다
#
# 왜: 열차 #1890 의 강의실 e2e 넷이 3초 한도에 걸린 4초 동안 backend 는 요청을 하나도 받지 않았고
# 서로 다른 두 Next 컨테이너도 응답하지 않았다 — Docker VM 전체가 멈췄다. 컨테이너 로그로는 더
# 가릴 수 없어, 그 몇 초에 호스트(mac)가 무엇을 했는지를 남긴다. 줄마다 UTC 초 시각을 붙여
# `test-results/stack/*.log` 의 Docker 타임스탬프·trace 의 wallTime 과 맞춰 본다.
#
#   memory.log        memory_pressure -Q(남은 메모리 %) · vm_stat 의 free/compressed/swapins/swapouts ·
#                     vm.swapusage · vm.loadavg
#   vm-top.log        Docker VM 프로세스(com.docker.virtualization·com.apple.Virtualization.VirtualMachine·
#                     com.docker.krun·qemu-system)의 pid·CPU·메모리. 첫 줄은 이름이 맞는 후보 전부(pid·RSS·
#                     실행 파일) — 열차 #1899 에서 `pgrep | head -1` 이 RSS 39M 짜리 보조 프로세스를 집어(#719)
#                     지금은 후보 중 RSS 가 가장 큰 것을 VM 본체로 본다. CPU 는 `top -l 2 -s 1` 의 둘째
#                     샘플(첫 샘플의 %CPU 는 무효라 #1899 는 내내 0.0 이었다) — 앞 1초의 값이고, top 을 띄우는
#                     몫까지 한 줄에 1.5초쯤 걸린다
#   docker-stats.log  docker stats --no-stream(컨테이너마다 CPU·메모리) — 한 번에 1~2초 걸리고, VM 이
#                     멈추면 그 자체가 멈추므로 다른 둘과 따로 돈다(줄 사이 틈이 곧 증거다)
#
# macOS 가 아니면 아무것도 하지 않고 끝난다. 명령이 없거나 권한이 없어도 그 줄을 비울 뿐 실패하지
# 않는다 — 증거를 남기려다 e2e 를 붉게 만들지 않는다. bash 3.2(macOS 기본)에서 돈다.
set -u
[ "$(uname -s 2>/dev/null)" = "Darwin" ] || exit 0
out=${1:-test-results/host}
mkdir -p "$out" 2>/dev/null || exit 0

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
has() { command -v "$1" >/dev/null 2>&1; }

memory_line() {
  local free="" vm="" swap="" load=""
  has memory_pressure && free=$(memory_pressure -Q 2>/dev/null | sed -n 's/.*percentage: *//p')
  has vm_stat && vm=$(vm_stat 2>/dev/null | awk -F: '
    /Pages free/ {f=$2} /occupied by compressor/ {c=$2} /^Swapins/ {i=$2} /^Swapouts/ {o=$2}
    END {gsub(/[ .]/,"",f); gsub(/[ .]/,"",c); gsub(/[ .]/,"",i); gsub(/[ .]/,"",o);
         printf "free=%s compressed=%s swapins=%s swapouts=%s", f, c, i, o}')
  swap=$(sysctl -n vm.swapusage 2>/dev/null)
  load=$(sysctl -n vm.loadavg 2>/dev/null)
  echo "$(now) mem_free=${free:-?} pages[$vm] swap[$swap] load=$load"
}

# 「pid RSS(KB) 실행 파일」 — 이름이 맞는 프로세스 전부. 실행 파일 경로(comm)에만 대므로 awk 자신은 안 걸린다.
vm_candidates() {
  ps -axo pid=,rss=,comm= 2>/dev/null | awk '
    /com\.docker\.virtualization|com\.apple\.Virtualization\.VirtualMachine|com\.docker\.krun|qemu-system/ {
      pid = $1; rss = $2; $1 = ""; $2 = ""; sub(/^ +/, ""); print pid, rss, $0 }'
}

# 같은 이름의 보조 프로세스가 있다 — RSS 가 가장 큰 것을 VM 본체로 본다.
vm_pid() { vm_candidates | sort -k2,2 -n -r | head -n 1 | awk '{print $1}'; }

candidates_line() {
  local list
  list=$(vm_candidates | awk '{pid = $1; rss = $2; $1 = ""; $2 = ""; sub(/^ +/, "");
                              printf "%s[pid=%s rss=%dM %s]", sep, pid, rss / 1024, $0; sep = " "}')
  echo "$(now) 후보 ${list:-없음}"
}

vm_line() {
  local pid sample
  pid=$(vm_pid)
  [ -n "$pid" ] || { echo "$(now) Docker VM 프로세스를 찾지 못했다"; sleep 1; return; }
  # 둘째 샘플의 줄 — top 이 1초를 기다린 뒤에 끝나므로 시각은 그 뒤에 찍는다.
  sample=$(top -l 2 -s 1 -stats pid,cpu,mem,command -pid "$pid" 2>/dev/null | tail -n 1)
  echo "$(now) ${sample:-top 이 줄을 주지 않았다}"
  [ -n "$sample" ] || sleep 1   # top 이 없거나 곧바로 실패하면 헛돌지 않게
}

loop_memory() { while :; do memory_line >>"$out/memory.log" 2>/dev/null; sleep 1; done; }
loop_vm() {
  candidates_line >>"$out/vm-top.log" 2>/dev/null
  while :; do vm_line >>"$out/vm-top.log" 2>/dev/null; done
}
loop_docker() {
  has docker || return 0
  while :; do
    { echo "$(now)"; docker stats --no-stream --format '  {{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' 2>&1; } \
      >>"$out/docker-stats.log" 2>/dev/null
    sleep 1
  done
}

children=""
stop() {
  # 자식 루프와 그 안의 sleep·docker, 명령 치환 속의 top 까지 — 남으면 다음 빌드까지 노드에서 돈다.
  # 루프를 먼저 죽인다 — 손주(top)를 먼저 죽이면 루프가 빈 줄 하나를 더 적는다.
  local pid kids kid
  for pid in $children; do
    kids=$(pgrep -P "$pid" 2>/dev/null)
    kill "$pid" 2>/dev/null
    for kid in $kids; do
      pkill -P "$kid" 2>/dev/null
      kill "$kid" 2>/dev/null
    done
  done
  exit 0
}
trap stop TERM INT HUP EXIT

loop_memory & children="$children $!"
loop_vm & children="$children $!"
loop_docker & children="$children $!"
wait
