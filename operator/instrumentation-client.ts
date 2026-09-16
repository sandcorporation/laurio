// 브라우저에서 난 오류를 GlitchTip 으로 보낸다(2026-09-16). Next 가 이 파일을
// 클라이언트 번들 맨 앞에서 한 번 실행한다 — 화면 코드보다 먼저 돌아야 첫 렌더에서
// 난 오류도 잡힌다. 무엇을 보내고 무엇을 보내지 않는지는
// lib/observability/sentry-options.ts 가 정한다.
import * as Sentry from "@sentry/nextjs";

import { buildSentryOptions } from "@/lib/observability/sentry-options";

const options = buildSentryOptions({
  NEXT_PUBLIC_SENTRY_DSN: process.env.NEXT_PUBLIC_SENTRY_DSN,
  NEXT_PUBLIC_SENTRY_ENVIRONMENT: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT,
  NEXT_PUBLIC_SENTRY_RELEASE: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
});

if (options) Sentry.init(options);

// 화면 이동(앱 라우터 전환)을 오류의 앞 기록으로 남긴다.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
