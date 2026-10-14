# shellcheck shell=bash
# ghcr 로그인 — `images.sh`·`deploy-guard.sh` 가 source 한다(#705). bash 3.2(macos 노드)에서도 돈다.
#
#   GHCR_TOKEN=… [GHCR_USER=…] ; . scripts/ci/ghcr-login.sh ; ghcr_login ; … ; ghcr_logout
#
# **노드의 docker 설정을 건드리지 않는다.** 빌드마다 임시 DOCKER_CONFIG 를 만들어 거기에만 토큰을
# 적는다 — sub 의 컨테이너에는 deploy.sh 가 쓰는 읽기 전용 ghcr 로그인이 이미 있고, macos 는 Docker
# Desktop 의 키체인 자격증명을 쓴다. 원래 설정의 `cli-plugins`(buildx 가 여기 있는 노드가 있다)·
# `buildx`(빌더 정의)·`contexts`(Docker Desktop 의 desktop-linux) 는 심볼릭 링크로 이어 붙이고,
# config.json 은 자격증명 칸만 빼고 옮긴다.
#
# `docker login` 을 부르지 않고 auths 에 직접 적는 이유: auths 가 비어 있으면 docker CLI 가 기본
# 자격증명 저장소(macOS 키체인, 리눅스 pass/secretservice)를 찾아 그리로 쓰려 한다 — 에이전트 세션에서
# 키체인이 잠겨 있으면 로그인이 실패한다. 토큰이 없으면(로컬 실행) 아무것도 하지 않고 지금 설정을 쓴다.

ghcr_login() {
  if [ -z "${GHCR_TOKEN:-}" ]; then
    echo "GHCR_TOKEN 이 없다 — 이 노드의 docker 로그인을 그대로 쓴다"
    return 0
  fi
  local orig tmp d
  orig="${DOCKER_CONFIG:-$HOME/.docker}"
  mkdir -p "$orig/buildx"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/codemit-docker.XXXXXX")"
  for d in cli-plugins buildx contexts; do
    if [ -e "$orig/$d" ]; then ln -s "$orig/$d" "$tmp/$d"; fi
  done
  python3 - "$orig/config.json" "$tmp/config.json" "${GHCR_USER:-codemit-ci}" <<'PY'
import base64, json, os, sys
src, dst, user = sys.argv[1:4]
try:
    with open(src) as f:
        cfg = json.load(f)
except (OSError, ValueError):
    cfg = {}
for key in ("auths", "credsStore", "credHelpers"):
    cfg.pop(key, None)
token = os.environ["GHCR_TOKEN"].strip()
cfg["auths"] = {"ghcr.io": {"auth": base64.b64encode(f"{user}:{token}".encode()).decode()}}
fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(cfg, f)
PY
  export DOCKER_CONFIG="$tmp"
  CODEMIT_GHCR_TMP="$tmp"
}

ghcr_logout() {
  if [ -n "${CODEMIT_GHCR_TMP:-}" ]; then
    rm -rf "$CODEMIT_GHCR_TMP"
    CODEMIT_GHCR_TMP=""
  fi
}

# env 파일(`KEY=value` 줄)에서 값 하나. 없는 키면 1 로 끝난다(빈 값은 0).
env_value() {
  local file="$1" key="$2"
  grep -q "^${key}=" "$file" || return 1
  sed -n "s/^${key}=//p" "$file" | tail -n 1 | tr -d '\r'
}
