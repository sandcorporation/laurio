// 세션 쿠키 — ADR-0016 이 세운 원칙(토큰은 여기서만 읽고 쓴다)을 그대로 따르되,
// 여기 담기는 건 JWT가 아니라 Django 세션 id 값 하나다(#63, ADR-0019). HttpOnly라
// 브라우저 JS는 document.cookie로 이 값을 절대 볼 수 없다.
import type { NextResponse } from "next/server";

// backend/config/settings.py의 SESSION_COOKIE_NAME과 정확히 같은 문자열이어야
// 한다 — 이 BFF가 Django로 보내는 Cookie 헤더가 이 이름으로 값을 실어 보내고,
// Django의 세션 미들웨어가 그 이름으로만 세션을 찾는다. 이름이 어긋나면 로그인은
// 성공한 것처럼 응답하고도 다음 요청부터 전부 익명으로 처리된다 — 그 실패가
// 조용하다.
export const SESSION_COOKIE_NAME = "laurio_operator_session";

// staging/production만 Secure를 건다 — frontend/lib/auth/cookies.ts와 같은 이유
// (dev는 컨테이너 간 http로만 통신하므로 Secure를 걸면 쿠키가 아예 안 실린다).
function isDeployedEnvironment(): boolean {
  const target = process.env.LAURIO_DEPLOYMENT_TARGET;
  return target === "staging" || target === "production";
}

function cookieAttributes() {
  return {
    httpOnly: true,
    // Lax — 이 앱에는 외부 사이트에서 돌아오는 콜백이 없으므로(소셜 로그인이
    // 없다, ADR-0018) Strict도 후보였지만, top-level 내비게이션(예: 즐겨찾기로
    // 새 탭에서 열기)까지 막지 않도록 공개 앱과 같은 Lax로 맞춘다. CSRF 방어는
    // 이것 하나로 끝내지 않는다 — Origin 검증(lib/backend.ts, assertSameOrigin)이
    // 반드시 함께 간다(ADR-0016의 성립 조건, 여기서도 같은 원칙).
    sameSite: "lax" as const,
    secure: isDeployedEnvironment(),
    path: "/",
  };
}

export function setSessionCookie(response: NextResponse, sessionValue: string): void {
  // maxAge를 주지 않는다 — 브라우저 세션 쿠키(탭을 닫으면 사라짐)로 남긴다.
  // Django 쪽 세션 만료(SESSION_COOKIE_AGE, 캐시 TTL)가 실제 유효성의 유일한
  // 판정 기준이다 — 이 쿠키가 더 오래 살아 있어도 백엔드가 401을 내면
  // lib/auth/use-session.ts가 로그인으로 돌려보낸다.
  response.cookies.set(SESSION_COOKIE_NAME, sessionValue, cookieAttributes());
}

export function clearSessionCookie(response: NextResponse): void {
  response.cookies.set(SESSION_COOKIE_NAME, "", { ...cookieAttributes(), maxAge: 0 });
}
