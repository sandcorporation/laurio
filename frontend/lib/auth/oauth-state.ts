// 카카오 OAuth authorize→callback 왕복에서 쓰는 state 발급·검증, 그리고 그
// 왕복 동안 next 목적지를 실어 나르는 쿠키(#95, spec #92).
//
// **state**: 브라우저가 authorize로 갈 때 서버가 발급해 HttpOnly 쿠키에 담고,
// 카카오에도 같은 값을 실어 보낸다. 콜백이 돌아오면 쿼리의 state와 쿠키의
// state가 일치해야만 로그인을 진행한다 — 없거나 다르면 거절한다. 검증 없는
// 콜백은 공격자가 자기 계정으로 얻은 code를 피해자의 브라우저에 열게 해
// 피해자 세션에 공격자 계정을 로그인시키는 로그인 고정(login fixation) 공격에
// 열린 문이다.
//
// **next 자체의 같은-오리진 검증**은 lib/auth/next-path.ts에 있다 — 이 파일과
// 분리한 이유는 그 파일의 독스트링을 참고한다(node:crypto를 쓰는 이 파일을
// 클라이언트 컴포넌트가 import하면 브라우저 번들 빌드가 깨진다).
import type { NextRequest, NextResponse } from "next/server";
import { randomBytes } from "node:crypto";

import { isDeployedEnvironment } from "./cookies";

export const OAUTH_STATE_COOKIE = "laurio_oauth_state";
export const OAUTH_NEXT_COOKIE = "laurio_oauth_next";

// 카카오 동의 화면에서 사람이 조작하는 시간이면 충분하다 — 길게 둘수록 탈취된
// state 쿠키가 재사용될 수 있는 창이 늘어난다.
const OAUTH_ROUND_TRIP_MAX_AGE_SECONDS = 5 * 60;

export function generateOAuthState(): string {
  return randomBytes(24).toString("base64url");
}

function oauthCookieAttributes() {
  return {
    httpOnly: true,
    // 카카오 동의 화면 → 콜백은 외부 사이트(kauth.kakao.com)에서 우리 오리진으로
    // 오는 top-level GET 내비게이션이다. Strict면 이 리다이렉트에서 쿠키가
    // 빠져 콜백이 항상 state 불일치로 거절된다 — lib/auth/cookies.ts가 세션
    // 쿠키에 Lax를 쓰는 것과 같은 이유다.
    sameSite: "lax" as const,
    secure: isDeployedEnvironment(),
    path: "/",
    maxAge: OAUTH_ROUND_TRIP_MAX_AGE_SECONDS,
  };
}

export function setOAuthRoundTripCookies(response: NextResponse, state: string, next: string): void {
  const attrs = oauthCookieAttributes();
  response.cookies.set(OAUTH_STATE_COOKIE, state, attrs);
  response.cookies.set(OAUTH_NEXT_COOKIE, next, attrs);
}

export function clearOAuthRoundTripCookies(response: NextResponse): void {
  const attrs = { ...oauthCookieAttributes(), maxAge: 0 };
  response.cookies.set(OAUTH_STATE_COOKIE, "", attrs);
  response.cookies.set(OAUTH_NEXT_COOKIE, "", attrs);
}

export function readOAuthRoundTripCookies(request: NextRequest): {
  state: string | undefined;
  next: string | undefined;
} {
  return {
    state: request.cookies.get(OAUTH_STATE_COOKIE)?.value,
    next: request.cookies.get(OAUTH_NEXT_COOKIE)?.value,
  };
}
