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
import { resolveNextPath, withoutForeignNext } from "@/lib/auth/next-path";
import { loginPathWithError, redirectToPath } from "@/lib/auth/redirect";
import { clearOAuthRoundTripCookies, readOAuthRoundTripCookies } from "@/lib/auth/oauth-state";
import { resolveSiblingOrigin } from "@/lib/auth/sibling-origins";
import { loginWithSocialAccessToken } from "@/lib/auth/social-login";
import { isSocialProvider } from "@/lib/auth/social-providers";

export const dynamic = "force-dynamic";

function redirectToLoginWithError(
  error: string,
  next: string,
  nextOrigin: string | null = null,
): NextResponse {
  const response = redirectToPath(loginPathWithError(error, next, nextOrigin));
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
  const {
    state: cookieState,
    next: cookieNext,
    returnOrigin: cookieReturnOrigin,
  } = readOAuthRoundTripCookies(request);
  // returnOrigin은 쿠키 값을 **다시** 허용목록과 대조한다(아래 성공 분기의 주석
  // 참고) — 여기서 한 번만 계산해 이 함수 안에서 재사용한다.
  const returnOrigin = resolveSiblingOrigin(cookieReturnOrigin);
  // next는 쿠키에 저장해 둔 값을 쓴다 — authorize가 이미 같은 오리진 경로로
  // 검증해 둔 값이고, 제공자를 거쳐 오는 쿼리 파라미터에 다시 실으면 그 값이
  // 왕복 중 조작될 여지를 새로 여는 것이라 그러지 않는다. authorize가 이미
  // withoutForeignNext로 걸러 뒀지만(#334), returnOrigin이 authorize 시점과
  // 콜백 시점 사이에 달라질 수 있는 이상(설정이 바뀌는 등) 여기서도 같은
  // 방어를 다시 건다 — 그러지 않으면 형제 앱의 경로가 이 오리진 안에서 그대로
  // 쓰여 404로 떨어질 수 있다.
  const next = withoutForeignNext(resolveNextPath(cookieNext), cookieReturnOrigin, returnOrigin);

  const { provider } = await context.params;
  if (!isSocialProvider(provider)) {
    return redirectToLoginWithError("login_failed", next, returnOrigin);
  }

  // 사용자가 동의를 거부했거나 제공자가 오류를 돌려준 경우 — 빈 화면이 아니라
  // 로그인 화면으로 돌아가 이유를 보여준다.
  const providerError = searchParams.get("error");
  if (providerError) {
    return redirectToLoginWithError("provider_denied", next, returnOrigin);
  }

  const queryState = searchParams.get("state");
  if (!cookieState || !queryState || cookieState !== queryState) {
    return redirectToLoginWithError("invalid_state", next, returnOrigin);
  }

  const code = searchParams.get("code");
  if (!code) {
    return redirectToLoginWithError("invalid_state", next, returnOrigin);
  }

  const adapter = OAUTH_PROVIDER_ADAPTERS[provider];
  const config = adapter.readConfig();
  if (!config) {
    // authorize가 이 상태면 애초에 제공자로 보내지 않았을 것이다 — 그래도 state
    // 쿠키를 훔쳐 이 라우트를 직접 두드리는 경로를 상정해 여기서도 같은 방식으로
    // 막는다(#96).
    return redirectToLoginWithError("oauth_unconfigured", next, returnOrigin);
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
      return redirectToLoginWithError("login_failed", next, returnOrigin);
    }

    // 돌아갈 형제 오리진이 있으면 거기로 보낸다(#297 후속). returnOrigin은 위에서
    // 쿠키 값을 이미 허용목록과 대조해 둔 값이다 — 쿠키는 HttpOnly 지만, 설정이
    // 바뀌어 더 이상 우리 것이 아닌 오리진이 남아 있을 수 있고 그때는 조용히
    // 같은 오리진으로 떨어지는 편이 옳다(그때 `next`도 이미 withoutForeignNext가
    // 기본 경로로 걸러 뒀다, #334). 세션 쿠키는 부모 도메인에 실리므로
    // (ADR-0038) 도착한 쪽에서 그대로 로그인 상태다.
    //
    // 여기만 절대 URL 이다 — `NextResponse.redirect` 는 외부로 나갈 때만 쓴다는
    // 규율(lib/auth/redirect.ts)의 그 "외부"가 형제 서브도메인이다. 우리 오리진
    // 안에서 끝나는 경우는 지금까지처럼 상대 Location 이다.
    const response = returnOrigin
      ? NextResponse.redirect(new URL(next, returnOrigin))
      : redirectToPath(next);
    setSessionCookies(response, result.pair);
    clearOAuthRoundTripCookies(response);
    return response;
  } catch (err) {
    console.error(`${provider} 로그인 콜백 처리 중 예외가 발생했다:`, err);
    return redirectToLoginWithError("login_failed", next, returnOrigin);
  }
}
