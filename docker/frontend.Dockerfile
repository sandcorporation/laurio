# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

# WORKDIR이 저장소 루트다 — pnpm 워크스페이스가 됐다(운영자 앱 04 #62). 락파일이
# 루트에 하나뿐이고, frontend/가 그 워크스페이스 멤버 중 하나로 설치된다.
WORKDIR /app

# 워크스페이스 정의·루트 락파일·각 멤버의 package.json만 먼저 복사해 의존성
# 레이어를 캐시한다. 소스가 바뀌어도 재설치하지 않는다. operator/의
# package.json은 운영자 앱 05(#63)가 그 디렉터리를 만들 때 여기 추가한다.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json
COPY packages/bff-shared/package.json ./packages/bff-shared/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ---- dev: 소스를 바인드 마운트하고 `next dev`로 돈다 (compose.dev.yaml이
# target: dev로 고른다). node_modules는 dev compose가 이름 있는 볼륨으로 가리므로
# 여기서 COPY하는 소스는 최초 기동 전까지의 스냅샷일 뿐이다. ----
FROM base AS dev
COPY frontend/ ./frontend/
COPY packages/bff-shared/ ./packages/bff-shared/
WORKDIR /app/frontend
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- builder: 프로덕션 산출물을 만든다. next.config.ts의 output: "standalone"이
# 서버 실행에 필요한 node_modules 서브셋까지 .next/standalone에 함께 추려준다 —
# runner 스테이지가 pnpm/전체 node_modules를 다시 설치하지 않는 이유다.
# outputFileTracingRoot이 워크스페이스 루트를 가리키므로(next.config.ts),
# standalone 산출물은 "frontend/server.js"처럼 워크스페이스 상대 경로를
# 그대로 보존한다 — 아래 runner 스테이지가 그 구조를 그대로 옮겨 담는 이유다. ----
FROM base AS builder
COPY frontend/ ./frontend/
COPY packages/bff-shared/ ./packages/bff-shared/
WORKDIR /app/frontend
RUN pnpm build

# ---- runner: staging/prod가 실제로 쓰는 얇은 이미지 (compose.staging.yaml/
# compose.prod.yaml이 target: runner로 고른다). builder의 산출물만 옮겨 담고
# base 이미지로 되돌아간다 — pnpm store·devDependencies·소스 트리 전체가 이
# 레이어에 없다. 루트가 아닌 사용자로 돈다(컨테이너 탈출 시 피해 범위를 줄인다). ----
FROM node:22-bookworm-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

# public/ 은 아직 이 저장소에 없다(정적 자산이 생기면 `COPY --from=builder
# /app/frontend/public ./frontend/public` 을 여기 추가한다 — 없는 디렉터리를
# COPY하면 빌드 자체가 실패하므로 지금은 넣지 않는다).
#
# standalone 산출물이 워크스페이스 구조를 그대로 담고 있으므로(위 builder
# 스테이지 주석), 통째로 옮기면 "frontend/server.js"·루트 node_modules가 함께
# 옮겨진다 — 실행에 필요한 워크스페이스 형태가 그대로 보존된다.
COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/static ./frontend/.next/static

USER nextjs
EXPOSE 3000

# server.js는 standalone 산출물이 만든 자체 Node 서버다 — pnpm/next CLI를 거치지
# 않는다. instrumentation.ts의 register()가 이 프로세스 시작 시 호출되므로, 배포
# 설정 가드는 여기서도 그대로 작동한다(#38).
CMD ["node", "frontend/server.js"]
