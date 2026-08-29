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

COPY frontend/ ./

EXPOSE 3000

# dev 는 소스를 바인드 마운트하고 이 명령으로 돈다. staging/prod 용 빌드 스테이지는
# 티켓 FE-13(#38)이 붙인다 — next.config.ts 가 이미 output: "standalone" 이다.
CMD ["pnpm", "dev"]
