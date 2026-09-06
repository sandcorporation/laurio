// 소셜 OAuth authorize 진입점 — 제공자 공용(#189). 카카오 전용이던
// app/api/auth/social/kakao/authorize/route.ts(#95, spec #92)를 세 제공자
// 공용으로 일반화했다 — 로직은 그대로이고 바뀐 것은 client_id/secret/redirect_uri를
// 읽는 곳과 authorize URL을 짓는 규칙을 provider별로 고른다는 점뿐이다. 카카오의
// 동작은 이 리팩터로 한 글자도 달라지지 않는다(lib/auth/kakao.ts는 손대지 않았다).
//
// 브라우저가 이 라우트를 top-level GET 내비게이션(로그인 화면의 <a href>)으로
// 연다 — fetch가 아니라 실제 브라우저 이동이어야 제공자의 동의 화면을 볼 수 있다.
//
// 여기서 하는 일은 셋뿐이다: `next`를 같은 오리진 경로로 검증하고, state를
// 발급해 HttpOnly 쿠키에 담고, 제공자의 authorize URL로 302한다. client_secret은
// 이 라우트에 등장하지 않는다 — code→token 교환(callback/route.ts)에서만 쓴다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { OAUTH_PROVIDER_ADAPTERS } from "@/lib/auth/oauth-adapters";
import { resolveNextPath } from "@/lib/auth/next-path";
import { generateOAuthState, setOAuthRoundTripCookies } from "@/lib/auth/oauth-state";
import { loginPathWithError, redirectToPath } from "@/lib/auth/redirect";
import { isSocialProvider } from "@/lib/auth/social-providers";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string }> },
): Promise<NextResponse> {
  // origin은 뽑지 않는다 — 우리 화면으로 돌아가는 리다이렉트는 상대 경로다
  // (lib/auth/redirect.ts). 제공자로 나가는 것만 외부 절대 URL이다.
  const { searchParams } = new URL(request.url);
  // 오픈 리다이렉트 방어 — 같은 오리진 경로가 아니면 기본값으로 떨어진다
  // (lib/auth/next-path.ts의 isSafeNextPath).
  const next = resolveNextPath(searchParams.get("next"));

  const { provider } = await context.params;
  if (!isSocialProvider(provider)) {
    return redirectToPath(loginPathWithError("oauth_unconfigured", next));
  }

  const adapter = OAUTH_PROVIDER_ADAPTERS[provider];
  const config = adapter.readConfig();
  if (!config) {
    // 이 환경에는 이 제공자의 앱이 설정되지 않았다 — 자격증명이 없는 authorize
    // URL로 보내 제공자 자신의 에러 페이지를 보게 하지 않는다. 대신 우리
    // 로그인 화면으로 돌려보내 이유를 보여준다. 배포 환경(staging/production)은
    // 카카오에 한해 이 상황 자체가 부팅 시점에 이미 거부되지만(#96,
    // config/settings.py·frontend/instrumentation.ts) GitHub·구글은 자격증명이
    // 배포 환경에서도 선택 사항이다(#189 — 사람이 OAuth 앱을 등록하기 전까지는
    // 버튼이 "준비 중"으로 남는다) — 그래서 이 분기는 세 제공자 모두에서 실제로
    // 관찰될 수 있다.
    return redirectToPath(loginPathWithError("oauth_unconfigured", next));
  }

  const state = generateOAuthState();
  const authorizeUrl = adapter.buildAuthorizeUrl(config, state);

  const response = NextResponse.redirect(authorizeUrl);
  setOAuthRoundTripCookies(response, state, next);
  return response;
}
