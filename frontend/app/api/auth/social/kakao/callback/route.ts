// 카카오 OAuth 콜백 (#95, spec #92). 카카오가 사람을 이 라우트로 top-level GET
// 리다이렉트시킨다 — code(성공) 또는 error(거부/실패)와, authorize에서 그대로
// 돌려준 state를 쿼리로 싣는다.
//
// 순서가 중요하다: state를 먼저 검증하고, 그다음에야 code→token 교환을 한다.
// state 불일치·부재는 카카오에 닿기도 전에 거절한다 — 검증 없이 아무 code나
// 받아 교환을 시도하면 로그인 고정 공격의 문이 열린다(lib/auth/oauth-state.ts).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { setSessionCookies } from "@/lib/auth/cookies";
import { exchangeKakaoCodeForToken, readKakaoOAuthConfig } from "@/lib/auth/kakao";
import { resolveNextPath } from "@/lib/auth/next-path";
import { clearOAuthRoundTripCookies, readOAuthRoundTripCookies } from "@/lib/auth/oauth-state";
import { loginWithSocialAccessToken } from "@/lib/auth/social-login";

export const dynamic = "force-dynamic";

function redirectToLoginWithError(origin: string, error: string, next: string): NextResponse {
  const url = new URL("/login", origin);
  url.searchParams.set("error", error);
  url.searchParams.set("next", next);
  const response = NextResponse.redirect(url);
  clearOAuthRoundTripCookies(response);
  return response;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams, origin } = new URL(request.url);
  const { state: cookieState, next: cookieNext } = readOAuthRoundTripCookies(request);
  // next는 쿠키에 저장해 둔 값을 쓴다 — authorize가 이미 같은 오리진 경로로
  // 검증해 둔 값이고, 카카오를 거쳐 오는 쿼리 파라미터에 다시 실으면 그 값이
  // 왕복 중 조작될 여지를 새로 여는 것이라 그러지 않는다.
  const next = resolveNextPath(cookieNext);

  // 사용자가 동의를 거부했거나 제공자가 오류를 돌려준 경우 — 빈 화면이 아니라
  // 로그인 화면으로 돌아가 이유를 보여준다.
  const providerError = searchParams.get("error");
  if (providerError) {
    return redirectToLoginWithError(origin, "provider_denied", next);
  }

  const queryState = searchParams.get("state");
  if (!cookieState || !queryState || cookieState !== queryState) {
    return redirectToLoginWithError(origin, "invalid_state", next);
  }

  const code = searchParams.get("code");
  if (!code) {
    return redirectToLoginWithError(origin, "invalid_state", next);
  }

  const config = readKakaoOAuthConfig();
  if (!config) {
    // authorize가 이 상태면 애초에 카카오로 보내지 않았을 것이다 — 그래도 state
    // 쿠키를 훔쳐 이 라우트를 직접 두드리는 경로를 상정해 여기서도 같은 방식으로
    // 막는다(#96).
    return redirectToLoginWithError(origin, "oauth_unconfigured", next);
  }

  // 카카오 교환·백엔드 로그인 호출 전체를 하나로 묶어서 잡는다(코드리뷰
  // 지적) — 예전에는 exchangeKakaoCodeForToken의 KakaoTokenExchangeError만
  // 잡고 그 아래 loginWithSocialAccessToken 호출은 try 밖에 있었다. 그 함수가
  // 부르는 fetch가 네트워크 실패(백엔드 연결 거부 등)로 예외를 던지면 이
  // 라우트 핸들러 자체가 처리되지 않은 예외로 죽어 Next가 원인 없는 500을
  // 내려주고, 그 요청이 실패하는 바람에 clearOAuthRoundTripCookies가 한 번도
  // 안 불려 이미 다 쓴 state/next 쿠키가 브라우저에 남았다. 어떤 예외든(카카오
  // 교환 실패든, 백엔드 호출의 네트워크 실패든) 로그인 화면으로 정상적으로
  // 돌아가고 왕복 쿠키를 지운다.
  try {
    const accessToken = await exchangeKakaoCodeForToken(config, code);
    const result = await loginWithSocialAccessToken("kakao", accessToken);
    if (!result.ok) {
      return redirectToLoginWithError(origin, "login_failed", next);
    }

    const response = NextResponse.redirect(new URL(next, origin));
    setSessionCookies(response, result.pair);
    clearOAuthRoundTripCookies(response);
    return response;
  } catch (err) {
    console.error("카카오 로그인 콜백 처리 중 예외가 발생했다:", err);
    return redirectToLoginWithError(origin, "login_failed", next);
  }
}
