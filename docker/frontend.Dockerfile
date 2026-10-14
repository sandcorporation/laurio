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
# 금칙어(사칭·욕설) 판정 순수 함수(spec #474, #478, #479, ADR-0051) — 개최자
# 공개용 이름·개발자 표시 이름, 공모전 제목·설명 폼이 제출 전에 이 패키지로
# 미리 검사한다. 원본은 backend/core/banned_words.py다. `app/console/profile/`이
# 이 타입을 쓰므로 빠지면 builder 의 타입 검사가 통째로 깨진다.
COPY packages/banned-words/package.json ./packages/banned-words/package.json
COPY packages/bff-shared/package.json ./packages/bff-shared/package.json
COPY packages/bff-client/package.json ./packages/bff-client/package.json
# 마크다운 렌더러(#313, 2026-09-16 에 강의실에서 패키지로 옮겼다) — 공개 앱의 공모전
# 설명과 강의실의 문제 설명이 같은 것을 쓴다. `app/globals.css` 가 이 패키지의
# `highlight.css` 를 `@import` 하므로 빠지면 스타일 빌드가 통째로 죽는다.
COPY packages/markdown/package.json ./packages/markdown/package.json
# route-audit 는 테스트 전용 정적 분석 도구지만(#166) 여기 빠지면 안 된다 —
# 각 앱의 `lib/routes/allowlist.ts` 가 그 타입을 쓰므로 builder 의 타입 검사가
# 통째로 깨진다. runner 스테이지는 `.next/standalone` 만 가져가므로 실행
# 이미지에는 들어가지 않는다.
COPY packages/route-audit/package.json ./packages/route-audit/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ---- dev: 소스를 바인드 마운트하고 `next dev`로 돈다 (compose.dev.yaml이
# target: dev로 고른다). node_modules는 dev compose가 이름 있는 볼륨으로 가리므로
# 여기서 COPY하는 소스는 최초 기동 전까지의 스냅샷일 뿐이다. ----
FROM base AS dev
COPY frontend/ ./frontend/
COPY packages/banned-words/ ./packages/banned-words/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
COPY packages/markdown/ ./packages/markdown/
COPY packages/route-audit/ ./packages/route-audit/
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
COPY packages/banned-words/ ./packages/banned-words/
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
COPY packages/markdown/ ./packages/markdown/
COPY packages/route-audit/ ./packages/route-audit/
WORKDIR /app/frontend
# 공개 값(Sentry·토스·포트원·문의 주소·공모전 스위치)은 여기서 받지 않는다 — 실행 때
# 컨테이너 env(`CODEMIT_PUBLIC_*`)에서 읽고 루트 레이아웃이 브라우저로 넘긴다(#711,
# ADR-0062, `frontend/lib/public-config.ts`). 그래서 이 이미지는 환경을 모른다 —
# 같은 이미지가 e2e·staging·prod 어디서든 뜬다.

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

# public/ 을 옮긴다(2026-09-16). standalone 산출물에는 public/ 이 **들어가지
# 않는다** — Next 가 그렇게 만든다. 그래서 이 줄이 없으면 `/kakao/...` 같은 정적
# 자산이 배포에서만 404 가 되고, 그 실패는 로컬·CI 어디에도 보이지 않는다
# (dev 는 소스를 그대로 서빙하고, deploy-guard 는 /login 의 HTML 만 본다).
# 실제로 카카오 로그인 버튼 이미지가 prod 에서 깨져 이 줄을 더했다.
COPY --from=builder --chown=nextjs:nodejs /app/frontend/public ./frontend/public
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
