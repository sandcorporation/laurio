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

export const OAUTH_STATE_COOKIE = "codemit_oauth_state";
export const OAUTH_NEXT_COOKIE = "codemit_oauth_next";
// 돌아갈 형제 오리진(#297 후속) — 강의실에서 온 사람은 로그인이 끝나면 거기로
// 돌아가야 한다. 값은 authorize 가 **허용목록과 대조해 통과한 것만** 싣는다
// (lib/auth/sibling-origins.ts). 없으면 지금까지처럼 같은 오리진 상대 경로로 간다.
export const OAUTH_RETURN_ORIGIN_COOKIE = "codemit_oauth_return_origin";

// 카카오 동의 화면에서 사람이 조작하는 시간이면 충분해야 하지만, 5분은 실제로
// 짧았다(코드리뷰 지적) — 카카오 신규 가입이거나 그 화면에서 추가 인증(휴대폰
// 인증 등)을 거치는 정상 사용자가 그 시간을 넘겨 invalid_state로 튕겨났다.
// 15분으로 늘린다 — 길게 둘수록 탈취된 state 쿠키가 재사용될 수 있는 창은
// 늘어나지만, state는 HttpOnly·1회용(성공·실패 양쪽에서 즉시 지운다)이라
// 탈취 자체가 이미 브라우저/쿠키 저장소가 뚫렸다는 뜻이고, 그 경우엔 TTL이
// 얼마든 방어선이 아니다 — 그래서 이 값은 "정상 사용자가 시간 안에 끝낼 수
// 있는가"로 정한다.
const OAUTH_ROUND_TRIP_MAX_AGE_SECONDS = 15 * 60;

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

export function setOAuthRoundTripCookies(
  response: NextResponse,
  state: string,
  next: string,
  returnOrigin: string | null = null,
): void {
  const attrs = oauthCookieAttributes();
  response.cookies.set(OAUTH_STATE_COOKIE, state, attrs);
  response.cookies.set(OAUTH_NEXT_COOKIE, next, attrs);
  // 빈 값을 굳이 심지 않는다 — 콜백은 "쿠키가 없으면 같은 오리진"으로 읽는다.
  if (returnOrigin) response.cookies.set(OAUTH_RETURN_ORIGIN_COOKIE, returnOrigin, attrs);
}

export function clearOAuthRoundTripCookies(response: NextResponse): void {
  const attrs = { ...oauthCookieAttributes(), maxAge: 0 };
  response.cookies.set(OAUTH_STATE_COOKIE, "", attrs);
  response.cookies.set(OAUTH_NEXT_COOKIE, "", attrs);
  response.cookies.set(OAUTH_RETURN_ORIGIN_COOKIE, "", attrs);
}

export function readOAuthRoundTripCookies(request: NextRequest): {
  state: string | undefined;
  next: string | undefined;
  returnOrigin: string | undefined;
} {
  return {
    state: request.cookies.get(OAUTH_STATE_COOKIE)?.value,
    next: request.cookies.get(OAUTH_NEXT_COOKIE)?.value,
    returnOrigin: request.cookies.get(OAUTH_RETURN_ORIGIN_COOKIE)?.value,
  };
}
