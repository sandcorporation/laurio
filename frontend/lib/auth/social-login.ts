// 백엔드의 소셜 로그인 엔드포인트(POST /api/auth/social/{provider}/login)를 부르는
// 공유 로직(ADR-0016). 브라우저가 직접 여는 POST 라우트(app/api/auth/social/
// [provider]/login/route.ts, dev seed 폼이 쓴다)와, 세 제공자 공용 OAuth 콜백
// (app/api/auth/social/[provider]/callback/route.ts, #95/#189)이 둘 다 이
// 함수를 쓴다 — access_token을 얻는 방법(폼이 지어낸 fake 토큰이냐, 제공자
// code→token 교환의 결과냐)만 다르고 그 뒤로 백엔드를 부르는 계약은 완전히 같다.
import { backendBaseUrl } from "./backend";
import type { TokenPair } from "./cookies";
import { safeJson } from "./http";

export type SocialLoginResult =
  | { ok: true; pair: TokenPair }
  | { ok: false; status: number; detail: unknown };

export async function loginWithSocialAccessToken(
  provider: string,
  accessToken: string,
): Promise<SocialLoginResult> {
  const backendRes = await fetch(`${backendBaseUrl()}/api/auth/social/${provider}/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ access_token: accessToken }),
    cache: "no-store",
  });

  if (!backendRes.ok) {
    const detail = await safeJson(backendRes);
    return {
      ok: false,
      status: backendRes.status,
      detail: detail ?? { detail: "로그인에 실패했습니다." },
    };
  }

  const pair = (await backendRes.json()) as TokenPair;
  return { ok: true, pair };
}
