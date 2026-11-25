// 강의실 `/login` — 화면 없이 공개 앱 로그인으로 307 한다(#1388).
//
// 강의실은 자기 로그인 폼이 없다(ADR-0038). 예전에는 「로그인이 필요합니다 + [로그인]」
// 화면을 그렸지만 그 화면이 하는 일은 공개 앱 로그인 주소를 짓는 것뿐이었다. 경로는
// 남긴다 — 미들웨어, 가입·초대 링크, BFF 401, 랜딩 CTA, 계정 메뉴와 바깥 북마크가 모두
// 여기를 가리키고, `next` 검증과 `next_origin` 싣기는 이 한 곳에 남는다
// (lib/auth/public-login-url.ts).
//
// 진입점 링크는 `<Link>` 가 아니라 `<a>` 다 — 클라이언트 라우터가 이 핸들러의 다른
// 오리진 리다이렉트를 RSC fetch 로 따라가지 않게 한다.
import * as Sentry from "@sentry/nextjs";

import { buildPublicLoginUrl } from "@/lib/auth/public-login-url";

// **빌드 때 굳으면 안 된다** (#297). `publicAppOrigin()` 이 빌드 머신의 환경(=비어
// 있음)을 읽으면 dev 폴백이 박제되어 배포된 강의실에서 로그인이 불가능해진다 — 실제로
// 그렇게 깨졌다. `lib/rendering/runtime-config.test.ts` 가 구조를, CI 의
// classroom-deploy-guard 가 결과(`Location`)를 잡는다.
export const dynamic = "force-dynamic";

export function GET(request: Request): Response {
  const location = buildPublicLoginUrl({
    requestUrl: request.url,
    host: request.headers.get("host"),
    proto: request.headers.get("x-forwarded-proto"),
    reportMissingOrigin: (message) => {
      console.error(message);
      Sentry.captureMessage(message, "error");
    },
  });
  return new Response(null, {
    status: 307,
    headers: { Location: location, "Cache-Control": "no-store" },
  });
}
