# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

WORKDIR /app

# 락파일만 먼저 복사해 의존성 레이어를 캐시한다. 소스가 바뀌어도 재설치하지 않는다.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ---- dev: 소스를 바인드 마운트하고 `next dev`로 돈다 (compose.dev.yaml이
# target: dev로 고른다). node_modules는 dev compose가 이름 있는 볼륨으로 가리므로
# 여기서 COPY하는 소스는 최초 기동 전까지의 스냅샷일 뿐이다. ----
FROM base AS dev
COPY frontend/ ./
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- builder: 프로덕션 산출물을 만든다. next.config.ts의 output: "standalone"이
# 서버 실행에 필요한 node_modules 서브셋까지 .next/standalone에 함께 추려준다 —
# runner 스테이지가 pnpm/전체 node_modules를 다시 설치하지 않는 이유다. ----
FROM base AS builder
COPY frontend/ ./
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
# /app/public ./public` 을 여기 추가한다 — 없는 디렉터리를 COPY하면 빌드 자체가
# 실패하므로 지금은 넣지 않는다).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# server.js는 standalone 산출물이 만든 자체 Node 서버다 — pnpm/next CLI를 거치지
# 않는다. instrumentation.ts의 register()가 이 프로세스 시작 시 호출되므로, 배포
# 설정 가드는 여기서도 그대로 작동한다(#38).
CMD ["node", "server.js"]
