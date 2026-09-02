// 카카오 OAuth authorize 진입점 (#95, spec #92). 브라우저가 이 라우트를 top-level
// GET 내비게이션(로그인 화면의 <a href>)으로 연다 — fetch가 아니라 실제 브라우저
// 이동이어야 카카오 동의 화면을 볼 수 있다.
//
// 여기서 하는 일은 셋뿐이다: `next`를 같은 오리진 경로로 검증하고, state를
// 발급해 HttpOnly 쿠키에 담고, 카카오의 authorize URL로 302한다. client_secret은
// 이 라우트에 등장하지 않는다 — code→token 교환(callback/route.ts)에서만 쓴다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { readKakaoOAuthConfig, buildKakaoAuthorizeUrl } from "@/lib/auth/kakao";
import { resolveNextPath } from "@/lib/auth/next-path";
import { generateOAuthState, setOAuthRoundTripCookies } from "@/lib/auth/oauth-state";
import { loginPathWithError, redirectToPath } from "@/lib/auth/redirect";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  // origin은 뽑지 않는다 — 우리 화면으로 돌아가는 리다이렉트는 상대 경로다
  // (lib/auth/redirect.ts). 카카오로 나가는 것만 외부 절대 URL이다.
  const { searchParams } = new URL(request.url);
  // 오픈 리다이렉트 방어 — 같은 오리진 경로가 아니면 기본값으로 떨어진다
  // (lib/auth/oauth-state.ts의 isSafeNextPath).
  const next = resolveNextPath(searchParams.get("next"));

  const config = readKakaoOAuthConfig();
  if (!config) {
    // 이 환경에는 카카오 앱이 설정되지 않았다(#96) — 자격증명이 없는 authorize
    // URL로 보내 카카오 자신의 에러 페이지를 보게 하지 않는다. 대신 우리 로그인
    // 화면으로 돌려보내 이유를 보여준다. 배포 환경(staging/production)은 이
    // 상황 자체가 부팅 시점에 이미 거부되므로(#96, config/settings.py와 같은
    // 원칙을 frontend/instrumentation.ts가 흉내낸다), 이 분기가 실제로 사람
    // 앞에 보이는 것은 dev/미설정 환경뿐이다.
    return redirectToPath(loginPathWithError("oauth_unconfigured", next));
  }

  const state = generateOAuthState();
  const authorizeUrl = buildKakaoAuthorizeUrl(config, state);

  const response = NextResponse.redirect(authorizeUrl);
  setOAuthRoundTripCookies(response, state, next);
  return response;
}
