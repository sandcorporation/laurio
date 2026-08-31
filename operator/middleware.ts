// 인증 경로 가드 (#63, ADR-0016/0019). 공개 앱의 `frontend/middleware.ts`와 같은
// 모양이다 — 세션 쿠키가 아예 없으면 렌더링 전에 이 미들웨어가 /login으로
// 돌려보낸다. Next 미들웨어는 라우트 렌더링보다 먼저 실행되므로, 페이지
// 컴포넌트가 실행되는 일 자체가 없다(HTML 본문에 보호된 콘텐츠가 한 조각도
// 안 들어간다).
//
// 이 앱은 "/login"을 뺀 전부가 인증 구역이다(공개 앱처럼 "/console"로 갈라 둘
// 이유가 없다 — 색인될 표면이 없으므로 ADR-0015의 렌더링 경계가 애초에 적용되지
// 않는다, ADR-0021). matcher는 지금 이 티켓이 만드는 페이지("/")만 담는다 —
// 이후 티켓이 "/appeals"·"/payouts"·"/operators"를 추가하면 여기도 함께 늘린다.
//
// 쿠키의 "존재"만 본다 — 유효성 판단은 항상 백엔드 몫이다(lib/auth/use-session.ts
// 가 런타임에 401을 만나면 로그인으로 보낸다).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME } from "./lib/auth/cookies";

export function middleware(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_COOKIE_NAME);

  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/"],
};
