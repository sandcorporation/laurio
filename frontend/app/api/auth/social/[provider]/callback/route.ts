// 소셜 OAuth 콜백 — 제공자 공용(#189). 카카오 전용이던
// app/api/auth/social/kakao/callback/route.ts(#95, spec #92)를 세 제공자
// 공용으로 일반화했다 — 로직은 그대로이고 바뀐 것은 code→token 교환을
// provider별로 고른다는 점뿐이다. 카카오의 동작은 이 리팩터로 한 글자도
// 달라지지 않는다(lib/auth/kakao.ts는 손대지 않았다).
//
// 제공자가 사람을 이 라우트로 top-level GET 리다이렉트시킨다 — code(성공)
// 또는 error(거부/실패)와, authorize에서 그대로 돌려준 state를 쿼리로 싣는다.
//
// 순서가 중요하다: state를 먼저 검증하고, 그다음에야 code→token 교환을 한다.
// state 불일치·부재는 제공자에 닿기도 전에 거절한다 — 검증 없이 아무 code나
// 받아 교환을 시도하면 로그인 고정 공격의 문이 열린다(lib/auth/oauth-state.ts).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { setSessionCookies } from "@/lib/auth/cookies";
import { OAUTH_PROVIDER_ADAPTERS } from "@/lib/auth/oauth-adapters";
import { resolveNextPath } from "@/lib/auth/next-path";
import { loginPathWithError, redirectToPath } from "@/lib/auth/redirect";
import { clearOAuthRoundTripCookies, readOAuthRoundTripCookies } from "@/lib/auth/oauth-state";
import { loginWithSocialAccessToken } from "@/lib/auth/social-login";
import { isSocialProvider } from "@/lib/auth/social-providers";

export const dynamic = "force-dynamic";

function redirectToLoginWithError(error: string, next: string): NextResponse {
  const response = redirectToPath(loginPathWithError(error, next));
  clearOAuthRoundTripCookies(response);
  return response;
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string }> },
): Promise<NextResponse> {
  // origin은 뽑지 않는다 — 우리 화면으로 돌아가는 리다이렉트는 전부 상대 경로다
  // (lib/auth/redirect.ts가 그 이유를 적는다).
  const { searchParams } = new URL(request.url);
  const { state: cookieState, next: cookieNext } = readOAuthRoundTripCookies(request);
  // next는 쿠키에 저장해 둔 값을 쓴다 — authorize가 이미 같은 오리진 경로로
  // 검증해 둔 값이고, 제공자를 거쳐 오는 쿼리 파라미터에 다시 실으면 그 값이
  // 왕복 중 조작될 여지를 새로 여는 것이라 그러지 않는다.
  const next = resolveNextPath(cookieNext);

  const { provider } = await context.params;
  if (!isSocialProvider(provider)) {
    return redirectToLoginWithError("login_failed", next);
  }

  // 사용자가 동의를 거부했거나 제공자가 오류를 돌려준 경우 — 빈 화면이 아니라
  // 로그인 화면으로 돌아가 이유를 보여준다.
  const providerError = searchParams.get("error");
  if (providerError) {
    return redirectToLoginWithError("provider_denied", next);
  }

  const queryState = searchParams.get("state");
  if (!cookieState || !queryState || cookieState !== queryState) {
    return redirectToLoginWithError("invalid_state", next);
  }

  const code = searchParams.get("code");
  if (!code) {
    return redirectToLoginWithError("invalid_state", next);
  }

  const adapter = OAUTH_PROVIDER_ADAPTERS[provider];
  const config = adapter.readConfig();
  if (!config) {
    // authorize가 이 상태면 애초에 제공자로 보내지 않았을 것이다 — 그래도 state
    // 쿠키를 훔쳐 이 라우트를 직접 두드리는 경로를 상정해 여기서도 같은 방식으로
    // 막는다(#96).
    return redirectToLoginWithError("oauth_unconfigured", next);
  }

  // 제공자 교환·백엔드 로그인 호출 전체를 하나로 묶어서 잡는다(#95 코드리뷰
  // 지적) — 어느 쪽이든(제공자 교환 실패든, 백엔드 호출의 네트워크 실패든)
  // 로그인 화면으로 정상적으로 돌아가고 왕복 쿠키를 지운다. 예전에는
  // exchangeKakaoCodeForToken의 에러만 잡고 그 아래 loginWithSocialAccessToken
  // 호출은 try 밖에 있었다 — 그 함수가 부르는 fetch가 네트워크 실패(백엔드 연결
  // 거부 등)로 예외를 던지면 이 라우트 핸들러 자체가 처리되지 않은 예외로 죽어
  // Next가 원인 없는 500을 내려주고, 그 요청이 실패하는 바람에
  // clearOAuthRoundTripCookies가 한 번도 안 불려 이미 다 쓴 state/next 쿠키가
  // 브라우저에 남았다.
  try {
    const accessToken = await adapter.exchangeCodeForToken(config, code);
    const result = await loginWithSocialAccessToken(provider, accessToken);
    if (!result.ok) {
      return redirectToLoginWithError("login_failed", next);
    }

    const response = redirectToPath(next);
    setSessionCookies(response, result.pair);
    clearOAuthRoundTripCookies(response);
    return response;
  } catch (err) {
    console.error(`${provider} 로그인 콜백 처리 중 예외가 발생했다:`, err);
    return redirectToLoginWithError("login_failed", next);
  }
}
