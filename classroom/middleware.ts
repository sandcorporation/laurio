// 인증 경로 가드 (ADR-0016/0038, #276/#280). 공개 앱(frontend/middleware.ts)·운영자
// 앱(operator/middleware.ts)과 같은 모양이다 — 세션 쿠키가 아예 없으면 렌더링
// 전에 이 미들웨어가 /login으로 돌려보낸다.
//
// 강의실은 "/login"·"/join/{code}"·**루트("/")**를 뺀 전부가 인증 구역이다
// (운영자 앱과 같은 이유 — 색인될 공개 표면이 랜딩 하나뿐이다, ADR-0021/0037).
// "/join/{code}"가 예외인 이유는 #280 AC 그대로다 — 계정이 없는 사람도 그
// 링크를 열어 클래스 미리보기(이름·강사·문제 수·참여자 수)를 보고 가입할지
// 판단할 수 있어야 한다. matcher는 화이트리스트가 아니라 예외 목록이다 —
// 운영자 앱이 이미 겪은 "가드 없이 태어나는 페이지" 사고를 되풀이하지 않는다.
//
// **루트가 예외인 이유는 #395다.** 쿠키가 없으면 로그인으로 튕기는 대신
// 서버에서 그린 랜딩(검색으로 온 강사가 보는 소개 화면)을 보여줘야 한다 —
// 쿠키가 있으면 지금까지의 「내 클래스」다. 어느 쪽을 보여줄지는 여기서
// 정하지 않는다 — `app/page.tsx`가 같은 판정 함수(`lib/landing/
// decide-root-view.ts`)로 다시 갈라 렌더링한다. 이 미들웨어는 루트를 그냥
// 통과시킬 뿐이다.
//
// **아이콘 경로도 뺀다**(#392). `app/icon.tsx`·`app/apple-icon.tsx`(Next 아이콘
// 파일 컨벤션)가 `/icon`·`/apple-icon`으로 나가는데, 예전에는 `favicon.ico`만
// 빠져 있어 비로그인 탭이 그 둘을 요청하면 `/login`으로 튕겼다 — 탭에 아이콘이
// 뜨지 않는 것으로 보이는 사고였다.
//
// **robots.txt·sitemap.xml도 뺀다**(#395). `app/robots.ts`·`app/sitemap.ts`가
// `/robots.txt`·`/sitemap.xml`로 나가는데, 검색엔진은 이 요청에 로그인 쿠키를
// 들고 오지 않는다 — 빼지 않으면 크롤러가 매번 `/login`으로 튕겨 랜딩이
// 색인되지 않는다(실제로 처음 걷다가 이 상태로 났다).
//
// 쿠키의 "존재"만 본다 — 유효성 판단은 언제나 백엔드 몫이다. 강의실은 자기
// 로그인을 갖지 않으므로(ADR-0038 — 공개 앱에서 발급된 쿠키가 부모 도메인을 타고
// 온다) 이 쿠키가 없는 사람에게 보여줄 자기 로그인 폼이 없다 — /login 화면은
// 공개 앱으로 가는 안내만 한다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { hasSessionCookie } from "./lib/auth/cookies";
import { decideRootView } from "./lib/landing/decide-root-view";
import { loginNextPath } from "./lib/auth/login-next";

export function middleware(request: NextRequest) {
  const view = decideRootView({
    pathname: request.nextUrl.pathname,
    hasSessionCookie: hasSessionCookie(request.cookies),
  });

  if (view !== "not-applicable") {
    // 루트다 — 쿠키 유무와 무관하게 통과시킨다.
    return NextResponse.next();
  }

  if (!hasSessionCookie(request.cookies)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", loginNextPath(request.url));
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

// **공동 강사 초대 링크(`/invite/{token}`)도 뺀다**(#561) — 가입 링크와 같은 이유다. 받은
// 사람이 로그인하기 전에 어느 클래스의 초대인지 보고, 로그인 링크가 이 주소로 돌아온다.
// 수락 자체는 로그인을 요구한다(백엔드 `accept_co_instructor_invite`).
//
// **연결된 앱의 바깥 주소도 뺀다**(ADR-0052, #512). `/mcp`·`/.well-known/oauth-*`·
// `/oauth/{register,token,revoke}`는 claude.ai 같은 외부 앱이 서버에서 부르는
// 자리라 로그인 쿠키가 없다 — 공개(메타데이터·등록)이거나 앱 자신의 Bearer 토큰으로
// 인증한다(`lib/connected-apps/gateway.ts`). 동의 화면 `/oauth/authorize`는 빼지
// 않는다 — 누가 허락하는지 알아야 하므로 로그인하지 않았으면 로그인으로 보냈다가
// 돌아온다.
export const config = {
  matcher: [
    "/((?!login|join|invite|api|healthz|_next/static|_next/image|favicon.ico|icon|apple-icon|robots.txt|sitemap.xml|opengraph-image|mcp|\\.well-known|oauth/register|oauth/token|oauth/revoke).*)",
  ],
};
