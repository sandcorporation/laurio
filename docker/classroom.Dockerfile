# syntax=docker/dockerfile:1

# 강의실(#276, ADR-0037) 이미지. docker/frontend.Dockerfile·docker/operator.Dockerfile과
# 같은 세 스테이지 구조를 그대로 따른다 — 세 앱이 같은 워크스페이스 멤버라서 install
# 레이어까지 동일하다. 차이는 어느 앱 디렉터리에서 build/dev를 도는지뿐이다. 이
# 앱도 공개 앱·운영자 앱과 같은 @codemit/bff-client를 쓴다(#462) — 손으로 쓴
# 클라이언트(lib/backend/client.ts)는 걷어냈다.

FROM node:22-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY classroom/package.json ./classroom/package.json
COPY packages/bff-shared/package.json ./packages/bff-shared/package.json
COPY packages/bff-client/package.json ./packages/bff-client/package.json
# 마크다운 렌더러(#313, 2026-09-16 에 강의실에서 패키지로 옮겼다) — 공개 앱의 공모전
# 설명과 강의실의 문제 설명이 같은 것을 쓴다. `app/globals.css` 가 이 패키지의
# `highlight.css` 를 `@import` 하므로 빠지면 스타일 빌드가 통째로 죽는다.
COPY packages/markdown/package.json ./packages/markdown/package.json
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
COPY packages/bff-client/ ./packages/bff-client/
COPY packages/markdown/ ./packages/markdown/
COPY packages/route-audit/ ./packages/route-audit/
WORKDIR /app/classroom
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- builder: 프로덕션 산출물을 만든다. ----
FROM base AS builder
COPY classroom/ ./classroom/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
COPY packages/markdown/ ./packages/markdown/
COPY packages/route-audit/ ./packages/route-audit/
WORKDIR /app/classroom
# 오류 수집(GlitchTip, 2026-09-16) — `NEXT_PUBLIC_*` 이라 브라우저 번들에
# 빌드타임에 굳는다. 값이 비면 SDK 가 꺼진 채로 돌므로 dev/CI 빌드는 지금과 같다.
# runner 에도 같은 인자를 다시 두는 이유: 서버(Node)에서 난 오류를 보내는
# 초기화(instrumentation.ts)는 런타임 env 를 읽는다 — 빌드 값과 같아야 한다.
ARG NEXT_PUBLIC_SENTRY_DSN=""
ARG NEXT_PUBLIC_SENTRY_ENVIRONMENT=""
ARG NEXT_PUBLIC_SENTRY_RELEASE=""
ENV NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN} \
    NEXT_PUBLIC_SENTRY_ENVIRONMENT=${NEXT_PUBLIC_SENTRY_ENVIRONMENT} \
    NEXT_PUBLIC_SENTRY_RELEASE=${NEXT_PUBLIC_SENTRY_RELEASE}

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

# 오류 수집(GlitchTip, 2026-09-16) — `NEXT_PUBLIC_*` 이라 브라우저 번들에
# 빌드타임에 굳는다. 값이 비면 SDK 가 꺼진 채로 돌므로 dev/CI 빌드는 지금과 같다.
# runner 에도 같은 인자를 다시 두는 이유: 서버(Node)에서 난 오류를 보내는
# 초기화(instrumentation.ts)는 런타임 env 를 읽는다 — 빌드 값과 같아야 한다.
ARG NEXT_PUBLIC_SENTRY_DSN=""
ARG NEXT_PUBLIC_SENTRY_ENVIRONMENT=""
ARG NEXT_PUBLIC_SENTRY_RELEASE=""
ENV NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN} \
    NEXT_PUBLIC_SENTRY_ENVIRONMENT=${NEXT_PUBLIC_SENTRY_ENVIRONMENT} \
    NEXT_PUBLIC_SENTRY_RELEASE=${NEXT_PUBLIC_SENTRY_RELEASE}

COPY --from=builder --chown=nextjs:nodejs /app/classroom/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/classroom/.next/static ./classroom/.next/static

USER nextjs
EXPOSE 3000

# instrumentation.ts의 register()가 이 프로세스 시작 시 호출되므로, 배포
# 설정 가드는 여기서도 그대로 작동한다.
CMD ["node", "classroom/server.js"]
