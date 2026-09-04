# syntax=docker/dockerfile:1

# 운영자 앱(#63, ADR-0019/0021) 이미지. docker/frontend.Dockerfile과 같은
# 세 스테이지 구조를 그대로 따른다 — 두 앱이 같은 워크스페이스 멤버라서 install
# 레이어까지 동일하다. 차이는 어느 앱 디렉터리에서 build/dev를 도는지뿐이다.

FROM node:22-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY operator/package.json ./operator/package.json
COPY packages/bff-shared/package.json ./packages/bff-shared/package.json
COPY packages/bff-client/package.json ./packages/bff-client/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ---- dev: 소스를 바인드 마운트하고 `next dev`로 돈다 (compose.dev.yaml이
# target: dev로 고른다). ----
FROM base AS dev
COPY operator/ ./operator/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
WORKDIR /app/operator
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- builder: 프로덕션 산출물을 만든다. ----
FROM base AS builder
COPY operator/ ./operator/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
WORKDIR /app/operator
RUN pnpm build

# ---- runner: staging/prod가 실제로 쓰는 얇은 이미지. ----
FROM node:22-bookworm-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/operator/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/operator/.next/static ./operator/.next/static

USER nextjs
EXPOSE 3000

# instrumentation.ts의 register()가 이 프로세스 시작 시 호출되므로, 배포
# 설정 가드는 여기서도 그대로 작동한다.
CMD ["node", "operator/server.js"]
