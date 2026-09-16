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
COPY packages/bff-client/package.json ./packages/bff-client/package.json
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
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
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
COPY packages/bff-shared/ ./packages/bff-shared/
COPY packages/bff-client/ ./packages/bff-client/
COPY packages/route-audit/ ./packages/route-audit/
WORKDIR /app/frontend
# NEXT_PUBLIC_*는 브라우저에서 도는 코드에 빌드타임에 인라인된다 — 런타임
# environment로 넘겨도 이미 굳어진 번들에는 반영되지 않는다(#85 코드리뷰 지적
# 2). 포트원 브라우저 SDK가 인증창을 열 때 쓰는 두 값을 여기서 ARG로 받아
# ENV로 노출해야 `pnpm build`가 실제 값을 인라인한다 — 비워 두면
# `lib/verification/portone.ts`의 getPortOneBrowserConfig()가 null을 돌려줘
# "실제 본인확인하기" 버튼 자체가 렌더링되지 않는다(기능이 죽은 채가 아니라
# 조용히 숨는다 — 자격증명이 없는 dev/CI 이미지가 이 버튼으로 죽지 않는 이유).
ARG NEXT_PUBLIC_PORTONE_STORE_ID=""
ARG NEXT_PUBLIC_PORTONE_CHANNEL_KEY=""
ENV NEXT_PUBLIC_PORTONE_STORE_ID=${NEXT_PUBLIC_PORTONE_STORE_ID}
ENV NEXT_PUBLIC_PORTONE_CHANNEL_KEY=${NEXT_PUBLIC_PORTONE_CHANNEL_KEY}
# 토스 결제창 브라우저 SDK가 결제창을 열 때 쓰는 값(#112) — 같은 이유로 여기서
# ARG로 받아 ENV로 노출해야 `pnpm build`가 실제 값을 인라인한다. 비어 있어도
# 빌드는 죽지 않는다 — 위젯을 쓸지는 이 값이 아니라 백엔드의
# PAYMENT_ADAPTER_MODE가 가른다(payments.api의 checkout_flow, ADR-0007). 값이
# 비었는데 서버가 "widget"을 요구하면 lib/payments/toss.ts가 결제창을 열지
# 못했다는 것을 화면에 곧바로 보여준다 — 부팅 시점에 이 값 자체를 요구하는
# 것은 #115의 범위다.
ARG NEXT_PUBLIC_TOSS_CLIENT_KEY=""
ENV NEXT_PUBLIC_TOSS_CLIENT_KEY=${NEXT_PUBLIC_TOSS_CLIENT_KEY}
# 공모전 제품 스위치(#271, `frontend/lib/contest-switch.ts`) — 기본값 "true"라
# ARG를 안 주는 dev/CI 빌드는 지금과 똑같이 공모전이 보인다. staging·prod는
# compose 파일이 이 build.args를 겹쳐 준다.
ARG NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED="true"
ENV NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED=${NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED}
# 유료 공모전 스위치(#413) — 위와 같은 이유로 기본값 "true", staging·prod만
# compose 파일이 "false"로 겹쳐 쓴다(ADR-0048: 공모전 켜짐·유료 꺼짐).
ARG NEXT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED="true"
ENV NEXT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED=${NEXT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED}
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

# ---- runner: staging/prod가 실제로 쓰는 얇은 이미지 (compose.staging.yaml/
# compose.prod.yaml이 target: runner로 고른다). builder의 산출물만 옮겨 담고
# base 이미지로 되돌아간다 — pnpm store·devDependencies·소스 트리 전체가 이
# 레이어에 없다. 루트가 아닌 사용자로 돈다(컨테이너 탈출 시 피해 범위를 줄인다). ----
FROM node:22-bookworm-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# builder 가 브라우저 번들에 인라인한 값을, 이 스테이지의 **컨테이너 런타임
# env** 로도 다시 노출한다. `docker build --build-arg` 는 그 이름을 선언한 모든
# 스테이지에 전역으로 적용되므로, compose 의 build.args 가 주는 한 값이
# builder(번들 인라인용)와 runner(여기) 양쪽에 똑같이 들어간다 — 갈릴 여지가
# 없다. NEXT_PUBLIC_* 는 build.args 로만 오고 frontend 서비스의 `environment:`
# 블록에는 **없다**. 그 사실이 이 등식을 떠받치므로 깨뜨리지 마라.
#
# 소비자가 둘이다.
#
# 1. **부팅 가드**(#115). `instrumentation.ts` 는 Next 의 컴파일 그래프 밖에서
#    도는 별도 Node 진입점이라 인라인의 혜택을 받지 못한다 — 직접 확인했다:
#    builder 만 --build-arg 로 채워 빌드해도 그 파일이 읽는
#    `process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY` 는 여전히 빈 문자열이었다.
#    이 ENV 가 있어야 가드가 실제로 구워진 값을 읽는다.
#
# 2. **deploy.sh 의 변경 감지**(#112 코드리뷰 지적 3). 이 값이 남아 있으면
#    「이 컨테이너가 지금 서빙 중인 값」을 컨테이너에게 물어볼 수 있다.
#    재배포 때 `.env.<target>` 의 현재 값과 비교해, 키가 회전(rotate)됐는데
#    frontend 를 다시 굽지 않아 옛 키를 문 채로 뜨는 것을 잡는다 —
#    `.env.<target>` 은 gitignore 라 git diff 기반 감지로는 절대 보이지 않는다.
ARG NEXT_PUBLIC_TOSS_CLIENT_KEY=""
ENV NEXT_PUBLIC_TOSS_CLIENT_KEY=${NEXT_PUBLIC_TOSS_CLIENT_KEY}

# 공모전 제품 스위치(#271) — builder 와 같은 기본값("true")을 다시 노출한다.
# 이 값을 읽는 부팅 가드는 없지만(`frontend/lib/contest-switch.ts`는 요청
# 처리 코드 안에서만 읽히고 이미 번들에 굳어 있다), deploy.sh 의 변경 감지가
# "이 컨테이너가 지금 서빙 중인 값"을 컨테이너에게 그대로 물어볼 수 있게
# NEXT_PUBLIC_TOSS_CLIENT_KEY 와 같은 자리를 지킨다.
ARG NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED="true"
ENV NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED=${NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED}

# 유료 공모전 스위치(#413) — 위와 같은 이유로 같은 자리를 지킨다.
ARG NEXT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED="true"
ENV NEXT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED=${NEXT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED}

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

COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/static ./frontend/.next/static

USER nextjs
EXPOSE 3000

# server.js는 standalone 산출물이 만든 자체 Node 서버다 — pnpm/next CLI를 거치지
# 않는다. instrumentation.ts의 register()가 이 프로세스 시작 시 호출되므로, 배포
# 설정 가드는 여기서도 그대로 작동한다(#38).
CMD ["node", "frontend/server.js"]
