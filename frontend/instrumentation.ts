// 부팅 시점 설정 가드 (ADR-0016 — 코드리뷰 지적 수정).
//
// backend/config/settings.py의 IS_DEPLOYED_ENVIRONMENT 가드와 같은 원칙을
// 프론트엔드에도 세운다: 배포 환경(production)에서 필수 설정이
// 비어 있으면 첫 요청을 받기 전에 부팅 자체를 거부한다 — "설정이 비어 있는
// 채로 조용히 뜬다"는 실패 모드를 애초에 없앤다.
//
// CODEMIT_WEB_ORIGIN이 그 대상이다. lib/auth/origin.ts의 assertSameOrigin은
// 이 값이 없으면 요청의 Host 헤더로 오리진을 유도하는 폴백을 쓰는데, 그
// 폴백은 dev(리버스 프록시 없이 컨테이너 포트를 직접 노출)에는 맞지만
// 배포 환경에서 TLS 종단 리버스 프록시가 X-Forwarded-Proto를 빠뜨리면
// (또는 Host 헤더가 프록시 뒤에서 내부 주소로 바뀌면) 유도된 오리진이
// 브라우저가 보낸 Origin과 어긋난다 — CSRF 방어가 fail-closed라 보안
// 구멍은 아니지만, 그 순간부터 모든 POST/PUT/PATCH/DELETE가 403이 되어
// 로그인부터 아무것도 안 된다. 폴백에 기대지 말고, 배포 환경에서는 이
// 값을 명시적으로 요구한다.
//
// Next.js가 이 파일의 register()를 서버 프로세스 시작 시 정확히 한 번
// 호출한다(Node.js 런타임 인스턴스마다). 여기서 에러를 던지면 프로세스가
// 그대로 죽는다 — backend의 `${VAR:?...}` compose 가드, JWT_SIGNING_KEY
// 부팅 가드와 같은 "설정이 없으면 뜨지 않는다" 규율을 그대로 반복한다.
//
// docker/prod.env.example에 CODEMIT_WEB_ORIGIN 항목이 있다 — compose.prod.yaml이
// frontend 서비스에 CODEMIT_DEPLOYMENT_TARGET=production을 주입하므로 이 가드가
// 배포마다 작동한다.
//
// FE-13(#38) 추가 — CODEMIT_API_BASE_URL도 같은 이유로 여기 합류한다.
// lib/api/client.ts·lib/auth/backend.ts·app/healthz/route.ts 셋 다
// `process.env.CODEMIT_API_BASE_URL ?? "http://127.0.0.1:58000"` 폴백을 쓴다.
// dev(compose 네트워크 안에서 backend 호스트명이 항상 해석된다)에는 그 폴백이
// 무해하지만, 배포 환경에서 이 값이 빠지면 프론트가 자기 자신의 루프백으로
// 로그인·조회·제출 요청을 쏘려 하며 전부 연결 거부로 조용히 죽는다 — 502가
// 아니라 "이유를 알 수 없는 500/타임아웃"으로 보인다. CODEMIT_WEB_ORIGIN과 같은
// 자리에서 같은 원칙으로 막는다: 값이 비어 있으면 첫 요청 전에 부팅을 거부한다.
//
// 두 검사를 한 번에 모아 던진다 — 이 파일이 "배포 환경 필수 설정"의 유일한
// 집합소여야 한다는 지침(#38) 그대로다. 앞으로 배포 전용 필수값이 늘어나면
// 여기 배열에 추가한다.
import * as Sentry from "@sentry/nextjs";

import { invalidDeploymentTarget, isDeployedEnvironment } from "@/lib/auth/cookies";
import { buildSentryOptions } from "@/lib/observability/sentry-options";

const REQUIRED_IN_DEPLOYED_ENVIRONMENTS: Array<{ name: string; reason: string }> = [
  {
    name: "CODEMIT_WEB_ORIGIN",
    reason:
      "배포 환경에서는 Origin 검증(lib/auth/origin.ts)이 Host 헤더 유도가 아니라 " +
      "이 값에 의존해야 한다 — 리버스 프록시가 X-Forwarded-Proto를 빠뜨리면 모든 " +
      "변경 요청이 403이 되는 사고를 부팅 시점에 막는다.",
  },
  {
    name: "CODEMIT_API_BASE_URL",
    reason:
      "이 값이 비어 있으면 lib/api/client.ts·lib/auth/backend.ts·app/healthz/route.ts가 " +
      "모두 127.0.0.1:58000(자기 자신)으로 조용히 폴백해 로그인·조회·제출이 전부 " +
      "연결 거부로 실패한다 — 배포 환경에서는 실제 backend 주소를 명시적으로 요구한다.",
  },
  // 카카오 OAuth 앱 자격증명(#95/#96, spec #92) — authorize 리다이렉트・code→token
  // 교환을 이 BFF가 직접 하므로(lib/auth/kakao.ts) 이 세 값을 실제로 읽는
  // 프로세스는 backend가 아니라 여기다. backend/config/settings.py가 같은
  // 이름의 값을 배포 환경에서 한 번 더 요구하는 것도 같은 이유다
  // (CODEMIT_OPERATOR_ORIGIN을 backend·operator 양쪽이 각자 요구하는 것과 같은
  // 원칙) — 두 쪽 다 잊혀야만 "로그인 버튼이 컨테이너가 뜬 채로 항상 실패한다"는
  // 사고가 난다.
  {
    name: "KAKAO_REST_API_KEY",
    reason:
      "카카오 OAuth의 client_id다. 비어 있으면 lib/auth/kakao.ts의 " +
      "readKakaoOAuthConfig가 null을 돌려줘, authorize 라우트가 카카오로 " +
      "보내는 대신 '이 환경에는 카카오 앱이 설정되지 않았다'는 우리 문구로 " +
      "돌아간다 — dev에서는 정상 동작이지만 배포 환경에서 이 상태가 되는 것은 " +
      "설정 누락이다.",
  },
  {
    name: "KAKAO_SECRET_KEY",
    reason:
      "카카오 OAuth의 client_secret이다. code→token 교환(lib/auth/kakao.ts의 " +
      "exchangeKakaoCodeForToken)에만 쓰이고 브라우저로 나가는 응답에는 " +
      "절대 실리지 않는다 — 비어 있으면 authorize 자체가 카카오로 가지 않는다.",
  },
  {
    name: "KAKAO_REDIRECT_URI",
    reason:
      "카카오 콘솔에 등록한 값과 한 글자라도 다르면 카카오가 code→token 교환을 " +
      "거절한다(docker/prod.env.example 참고) — 비어 있으면 그 사고를 배포 " +
      "시점에 막는다.",
  },
  // 토스 결제창 브라우저 SDK의 클라이언트 키(#112 lib/payments/toss.ts, #115).
  // 배포 환경에서 PAYMENT_ADAPTER_MODE는 언제나 실물 어댑터를 가리키므로(#83이
  // fake를 거부한다) 위젯을 반드시 쓴다 — 이 값이 비어 있으면 사용자가 결제하기를
  // 누르는 순간에야 getTossClientKey()가 null을 돌려줘 실패한다. 그 첫 발견자가
  // 사용자였던 사고(spec #110)를 부팅 시점으로 당긴다.
  //
  // 이 값은 실행 env 이고, 브라우저는 루트 레이아웃이 **같은 env** 에서 넘긴 값을
  // 쓴다(#711, lib/public-config.ts) — 그래서 여기서 본 값이 곧 결제창이 쓸 값이다.
  // (빌드 인자로 굽던 시절에는 env 와 번들이 갈릴 수 있어 compose `environment:` 에
  // 이 이름을 넣지 말라는 경고가 있었다 — 이제는 거기가 유일한 자리다.)
  {
    name: "CODEMIT_PUBLIC_TOSS_CLIENT_KEY",
    reason:
      "토스 결제창 브라우저 SDK가 결제창을 열 때 쓰는 공개 키다 " +
      "(lib/payments/toss.ts의 getTossClientKey) — 배포 환경은 PG 어댑터가 " +
      "언제나 실물(TossPGAdapter)이라 위젯을 반드시 거치는데, 이 값이 " +
      "비어 있으면 사용자가 결제하기를 누른 순간에야 실패가 드러난다. " +
      "서버의 docker/.env.prod 에 TOSS_LIVE_CLIENT_KEY 를 채우고 컨테이너를 다시 " +
      "띄운다(docker/prod.env.example 참고).",
  },
  // 세션 쿠키의 domain 속성(ADR-0038, #273) — lib/auth/cookies.ts가 이 값이
  // 비어 있으면 domain을 아예 주지 않아 dev와 똑같이 호스트 전용 쿠키로
  // 조용히 되돌아간다. 배포 환경에서 그 상태가 되면 강의실 등 형제
  // 서브도메인이 로그인을 공유하지 못하는 채로 조용히 뜬다 — 기능 결함이지
  // 500은 아니라서 다른 가드보다 늦게 발견될 위험이 크다.
  {
    name: "CODEMIT_SESSION_COOKIE_DOMAIN",
    reason:
      "부모 도메인(예: .laurio.honeycombpizza.link)을 주지 않으면 " +
      "lib/auth/cookies.ts의 setSessionCookies가 dev와 동일하게 domain을 " +
      "생략한다 — laurio.honeycombpizza.link에서 로그인한 세션 쿠키가 " +
      "classroom.laurio.honeycombpizza.link 등 형제 서브도메인으로 가지 " +
      "않아, 회원 공유라는 이 결정의 목적이 조용히 깨진다(ADR-0038).",
  },
];

// 서버(Node 런타임)에서 난 오류도 같은 프로젝트로 보낸다(2026-09-16) — 아래 부팅
// 가드와 한 파일에 있는 이유는 Next 가 register() 를 서버 시작에 한 번 부르는 자리가
// 여기뿐이기 때문이다. `onRequestError` 는 서버 컴포넌트·라우트 핸들러에서 난
// 오류를 Next 가 직접 넘겨주는 훅이다.
function startSentry(): void {
  const options = buildSentryOptions(process.env, "server");
  if (options) Sentry.init(options);
}

export const onRequestError = Sentry.captureRequestError;

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  startSentry();

  const target = process.env.CODEMIT_DEPLOYMENT_TARGET;
  // 알 수 없는 배포 대상(없앤 staging 포함)은 아래 필수 설정 가드보다 먼저 거부한다 —
  // 그대로 두면 development 로 흘러 이 가드 전체가 꺼진 채 뜬다.
  const invalid = invalidDeploymentTarget(target);
  if (invalid) {
    console.error(invalid);
    process.exit(1);
  }
  if (!isDeployedEnvironment()) return;

  const missing = REQUIRED_IN_DEPLOYED_ENVIRONMENTS.filter(({ name }) => !process.env[name]);
  if (missing.length === 0) return;

  const detail = missing.map(({ name, reason }) => `- ${name}: ${reason}`).join("\n");
  const message = `CODEMIT_DEPLOYMENT_TARGET=${target} 인데 다음 필수 설정이 비어 있다:\n${detail}`;

  // FE-13(#38) 발견: `throw` 만으로는 부팅이 실패하지 않는다 — standalone
  // 산출물의 `node server.js`(compose.prod.yaml이 실제로 도는 그 실행
  // 파일)로 직접 재현해 확인했다. register()의 에러는 Next가 "unhandledRejection"
  // 으로 로그만 찍고 삼켜, HTTP 서버는 계속 듣고 있다가 모든 요청에 이유 없는
  // 500을 낸다 — 컨테이너는 Up 상태로 남고 `restart: unless-stopped`도 재시작할
  // 계기를 못 잡는다. 이건 이 티켓의 핵심 인수조건("부팅 시점에 시끄럽게
  // 실패한다")을 문자 그대로 어긴다 — 시끄럽긴 하지만 실패하지 않는다. 그래서
  // 로그를 남긴 뒤 `process.exit(1)`로 직접 프로세스를 끊는다 — backend가
  // `manage.py check`의 비정상 종료 코드로 부팅을 막는 것과 같은 결과를
  // Next.js의 삼킴을 우회해서 만든다.
  console.error(message);
  process.exit(1);
}
