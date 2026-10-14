// 브라우저에서 난 오류를 GlitchTip 으로 보낸다(2026-09-16). Next 가 이 파일을
// 클라이언트 번들 맨 앞에서 한 번 실행한다 — 화면 코드보다 먼저 돌아야 첫 렌더에서
// 난 오류도 잡힌다. 무엇을 보내고 무엇을 보내지 않는지는
// lib/observability/sentry-options.ts 가 정한다.
//
// DSN·환경·릴리스는 실행 env 에서 루트 레이아웃이 `<head>` 에 넘긴 공개 설정으로
// 온다(#711, lib/public-config.ts). 이 파일은 async 스크립트라 HTML 파싱이 그
// `<script>` 에 닿기 전에 돌 수도 있다 — 그때는 문서 파싱이 끝날 때(DOMContentLoaded)
// 초기화한다. 그 사이 난 오류는 놓치지만, 값 없이 빈 DSN 으로 꺼진 채 남는 것보다 낫다.
import * as Sentry from "@sentry/nextjs";

import { buildSentryOptions } from "@/lib/observability/sentry-options";
import { publicConfig } from "@/lib/public-config";

function startSentry(): void {
  const options = buildSentryOptions(publicConfig(), "browser");
  if (options) Sentry.init(options);
}

if (window.__CODEMIT_PUBLIC__ === undefined && document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startSentry, { once: true });
} else {
  startSentry();
}

// 화면 이동(앱 라우터 전환)을 오류의 앞 기록으로 남긴다.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
