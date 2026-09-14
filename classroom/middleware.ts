// 인증 경로 가드 (ADR-0016/0038, #276/#280). 공개 앱(frontend/middleware.ts)·운영자
// 앱(operator/middleware.ts)과 같은 모양이다 — 세션 쿠키가 아예 없으면 렌더링
// 전에 이 미들웨어가 /login으로 돌려보낸다.
//
// 강의실은 "/login"과 "/join/{code}"를 뺀 전부가 인증 구역이다(운영자 앱과 같은
// 이유 — 색인될 공개 표면이 없다, ADR-0021/0037). "/join/{code}"만 예외인 이유는
// #280 AC 그대로다 — 계정이 없는 사람도 그 링크를 열어 클래스 미리보기(이름·
// 강사·문제 수·참여자 수)를 보고 가입할지 판단할 수 있어야 한다. matcher는
// 화이트리스트가 아니라 예외 목록이다 — 운영자 앱이 이미 겪은 "가드 없이 태어나는
// 페이지" 사고를 되풀이하지 않는다.
//
// **아이콘 경로도 뺀다**(#392). `app/icon.tsx`·`app/apple-icon.tsx`(Next 아이콘
// 파일 컨벤션)가 `/icon`·`/apple-icon`으로 나가는데, 예전에는 `favicon.ico`만
// 빠져 있어 비로그인 탭이 그 둘을 요청하면 `/login`으로 튕겼다 — 탭에 아이콘이
// 뜨지 않는 것으로 보이는 사고였다.
//
// 쿠키의 "존재"만 본다 — 유효성 판단은 언제나 백엔드 몫이다. 강의실은 자기
// 로그인을 갖지 않으므로(ADR-0038 — 공개 앱에서 발급된 쿠키가 부모 도메인을 타고
// 온다) 이 쿠키가 없는 사람에게 보여줄 자기 로그인 폼이 없다 — /login 화면은
// 공개 앱으로 가는 안내만 한다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "./lib/auth/cookies";

export function middleware(request: NextRequest) {
  const hasAccess = request.cookies.has(ACCESS_COOKIE);
  const hasRefresh = request.cookies.has(REFRESH_COOKIE);

  if (!hasAccess && !hasRefresh) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!login|join|api|healthz|_next/static|_next/image|favicon.ico|icon|apple-icon).*)",
  ],
};
