// 인증 경로 가드 (ADR-0016, FE-07 #32).
//
// `/console/**`는 로그인 이후 화면이다(ADR-0015 — 인증 구역은 클라이언트 SPA로만
// 렌더된다). 세션 쿠키가 전혀 없으면 그 화면의 어떤 조각도 그려지지 않고 이
// 미들웨어가 요청을 가로채 /login으로 돌려보낸다 — Next 미들웨어는 라우트
// 렌더링보다 먼저 실행되므로, 페이지 컴포넌트가 실행되거나 그 안의 데이터
// fetch가 시작되는 일 자체가 없다(HTML 본문에 보호된 콘텐츠가 한 조각도
// 안 들어간다).
//
// 경로 이름을 "/app"이 아니라 "/console"로 둔 이유: app 라우터의 최상위
// `app/` 디렉터리 바로 아래에 `app`이라는 이름의 라우트 세그먼트를 또 두면
// (`app/app/page.tsx`), Next 15.5.24 dev 서버가 루트 "/"의 RSC 청크를 이
// 중첩 라우트로 잘못 연결해 "/"에 접속해도 이 세그먼트의 내용이 그려지는
// 것을 직접 재현해 확인했다(청크 경로 규약 "static/chunks/app/page.js"와
// 폴더 이름이 겹치는 것으로 보인다). 이름을 바꾸는 것으로 해결되고, 재현
// 조건이 이 dev 서버 인스턴스 한정일 수도 있어 근본 원인까지는 추적하지
// 않았다 — 그 대신 상위 폴더와 같은 이름을 쓰지 않는 규칙으로 회피한다.
//
// 여기서는 쿠키의 "존재"만 본다 — 서명·만료 검증은 하지 않는다(그건 항상
// 백엔드 몫이다, lib/auth/jwt.ts 참고). 액세스가 만료됐어도 리프레시 쿠키가
// 남아 있으면 통과시킨다: 실제 리프레시는 로그인 이후 화면이 백엔드를 호출하는
// 시점에 lib/auth/session.ts가 조용히 처리한다(화면이 끊기지 않아야 한다는
// 인수조건). 리프레시까지 실패하면 그 호출이 401을 내고, 클라이언트 쪽 fetch
// 래퍼가 그때 /login으로 보낸다 — 미들웨어의 몫은 "쿠키가 아예 없는 사람을
// 렌더링 전에 막는 것"까지다.
//
// 공모전 MCP 의 동의 화면 `/oauth/authorize`(#870)도 같은 가드를 받는다 — 로그인하지 않은 사람은
// `/login?next=/oauth/authorize?…` 로 갔다가 쿼리까지 그대로 돌아온다. `/mcp`·`/.well-known/*`·
// `/oauth/{register,token,revoke}` 는 앱이 자기 토큰으로 부르는 경로라 여기 걸지 않는다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "./lib/auth/cookies";
import { loginNextPath } from "./lib/auth/login-next";

export function middleware(request: NextRequest) {
  // 콘솔 현관 제거(#375, spec #371) — `/console` 자체(하위 경로 없이 정확히
  // 이 경로)는 세션 여부와 무관하게 홈으로 보낸다. 로그인 여부를 먼저 따지면
  // 로그인 안 한 사람은 /login을 한 번 더 거쳐야 하는데, 그 화면은 어차피
  // 로그인 뒤 홈으로 돌아오므로(next-path.ts 기본값 "/") 한 홉을 아낀다.
  // `/console/**` 하위 화면(참가 현황·공모전·프로필 등)은 이 분기 밖이라
  // 그대로 로그인 가드를 받는다.
  if (request.nextUrl.pathname === "/console") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  const hasAccess = request.cookies.has(ACCESS_COOKIE);
  const hasRefresh = request.cookies.has(REFRESH_COOKIE);

  if (!hasAccess && !hasRefresh) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", loginNextPath(request.url));
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/console/:path*", "/oauth/authorize"],
};
