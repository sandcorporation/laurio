# syntax=docker/dockerfile:1

# 강의실(#276, ADR-0037) 이미지. docker/frontend.Dockerfile·docker/operator.Dockerfile과
# 같은 세 스테이지 구조를 그대로 따른다 — 세 앱이 같은 워크스페이스 멤버라서 install
# 레이어까지 동일하다. 차이는 어느 앱 디렉터리에서 build/dev를 도는지, 그리고 이
# 앱은 @laurio/bff-client를 아직 쓰지 않는다는 것뿐이다(지금은 이 앱의 어떤 화면도
# 백엔드 프록시를 실제로 타지 않는다 — lib/proxy/allowlist.ts가 비어 있다).

FROM node:22-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY classroom/package.json ./classroom/package.json
COPY packages/bff-shared/package.json ./packages/bff-shared/package.json
# route-audit는 테스트 전용 정적 분석 도구지만(#166) 여기 빠지면 안 된다 —
# lib/routes/allowlist.ts가 그 타입을 쓰므로 builder의 타입 검사가 통째로 깨진다.
# runner 스테이지는 `.next/standalone`만 가져가므로 실행 이미지에는 들어가지 않는다.
COPY packages/route-audit/package.json ./packages/route-audit/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ---- dev: 소스를 바인드 마운트하고 `next dev`로 돈다 (compose.dev.yaml이
# target: dev로 고른다). ----
FROM base AS dev
COPY classroom/ ./classroom/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/route-audit/ ./packages/route-audit/
WORKDIR /app/classroom
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- builder: 프로덕션 산출물을 만든다. ----
FROM base AS builder
COPY classroom/ ./classroom/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/route-audit/ ./packages/route-audit/
WORKDIR /app/classroom
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

COPY --from=builder --chown=nextjs:nodejs /app/classroom/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/classroom/.next/static ./classroom/.next/static

USER nextjs
EXPOSE 3000

# instrumentation.ts의 register()가 이 프로세스 시작 시 호출되므로, 배포
# 설정 가드는 여기서도 그대로 작동한다.
CMD ["node", "classroom/server.js"]
