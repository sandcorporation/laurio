// 인증 경로 가드 (#63, ADR-0016/0019). 공개 앱의 `frontend/middleware.ts`와 같은
// 모양이다 — 세션 쿠키가 아예 없으면 렌더링 전에 이 미들웨어가 /login으로
// 돌려보낸다. Next 미들웨어는 라우트 렌더링보다 먼저 실행되므로, 페이지
// 컴포넌트가 실행되는 일 자체가 없다(HTML 본문에 보호된 콘텐츠가 한 조각도
// 안 들어간다).
//
// 이 앱은 "/login"을 뺀 전부가 인증 구역이다(공개 앱처럼 "/console"로 갈라 둘
// 이유가 없다 — 색인될 표면이 없으므로 ADR-0015의 렌더링 경계가 애초에 적용되지
// 않는다, ADR-0021).
//
// **matcher는 화이트리스트가 아니라 예외 목록이다**(코드리뷰 지적) — 처음에는
// "/"만 담아 두고 다음 페이지가 생길 때마다 여기도 늘리기로 했는데, 그 사이에
// 홈이 이미 "/appeals"·"/payouts"로 링크를 걸어 버렸다(#65). 그 라우트들은
// #66·#68이 아직 안 만들었을 뿐 링크는 이미 살아 있으므로, 화이트리스트 방식은
// **가드 없이 태어나는 페이지**를 만든다 — 이 저장소가 반복해서 지키는 "라우터
// 전체 기본 거부"(예: core/operator_auth.py의 OperatorAuth·OperatorOriginMiddleware
// 가 라우터 전체에 걸려 다음 엔드포인트가 열린 채로 태어나지 않게 하는 것과 같은
// 원칙)를 프론트에서도 지킨다: "/login"·"/api/**"·Next 내부 자산·헬스체크만 빼고
// 전부 걸리게 한다.
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
  // /login(로그인 화면 자신), /api/**(로그인·세션 BFF 라우트와 백엔드 프록시 —
  // 이들은 자기 자신의 세션·Origin 검증을 갖는다), Next 정적 자산, /healthz(CI
  // 대기 스텝이 세션 없이 친다)만 뺀다.
  matcher: ["/((?!login|api|healthz|_next/static|_next/image|favicon.ico).*)"],
};
