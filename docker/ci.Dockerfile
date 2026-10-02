# PR CI 가 sub(Jenkins 내장 노드)에서 백엔드·단위 시험·생성물·문서 검사를 돌리는 이미지
# (2026-10-02, `Jenkinsfile.pr`·`scripts/ci/sub-checks.sh`).
#
# Jenkins 는 컨테이너 안에서 돌고 호스트 docker 를 쓴다 — 워크스페이스 경로가 호스트와
# 달라 bind mount 가 엉뚱한 곳을 본다(CLAUDE.md 「Jenkins 는 staging 배포 호스트에 있다」).
# 그래서 저장소를 이미지에 담아 그 안에서 돌린다. 그 컨테이너에는 node·pnpm·uv 도 없다.
#
# 바탕은 backend 이미지와 같은 uv 이미지이고(파이썬·uv 판이 같다), Node 는 앱 이미지와
# 같은 node:22 에서 가져온다.
FROM node:22-bookworm-slim AS node

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    XDG_CACHE_HOME=/opt/codemit-cache

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && corepack enable \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

# 의존이 같으면 이 두 층은 캐시에서 온다.
COPY backend/pyproject.toml backend/uv.lock backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --locked

COPY . .
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile
