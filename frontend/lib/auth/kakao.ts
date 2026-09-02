// 카카오 OAuth 앱 설정과 code→token 교환(#95/#96, spec #92). 서버 전용 —
// KAKAO_SECRET_KEY는 이 파일 밖으로, 특히 브라우저로 나가는 응답으로는 절대
// 나가지 않는다(client_secret이 필요한 곳은 exchangeKakaoCodeForToken이 서버에서
// 카카오 토큰 엔드포인트를 직접 부르는 이 자리 하나뿐이다 — ADR-0016이 JWT를
// BFF가 쿠키로 들고 있는 것과 같은 이유).
//
// NEXT_PUBLIC_ 접두어를 붙이지 않는다 — 붙이면 빌드 시점에 브라우저 번들에
// 그대로 인라인된다(frontend/docker/compose.staging.yaml의 PORTONE 채널키가
// 그 반대 사례다). 이 세 값은 런타임에 Node 서버 프로세스만 읽는다.
export interface KakaoOAuthConfig {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
}

// 셋 중 하나라도 비어 있으면 null — "이 환경에는 카카오 앱이 설정되지 않았다"는
// 뜻이다(#96). 호출부는 이 경우 카카오로 리다이렉트하지 않고 우리 문구로
// 돌아간다 — 설정되지 않은 authorize URL로 보내 제공자의 에러 페이지를 보게
// 하지 않는다.
export function readKakaoOAuthConfig(): KakaoOAuthConfig | null {
  const clientId = process.env.KAKAO_REST_API_KEY ?? "";
  const clientSecret = process.env.KAKAO_SECRET_KEY ?? "";
  const redirectUri = process.env.KAKAO_REDIRECT_URI ?? "";
  if (!clientId || !clientSecret || !redirectUri) return null;
  return { clientId, clientSecret, redirectUri };
}

export function buildKakaoAuthorizeUrl(config: KakaoOAuthConfig, state: string): string {
  const url = new URL("https://kauth.kakao.com/oauth/authorize");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("state", state);
  return url.toString();
}

export class KakaoTokenExchangeError extends Error {}

// 이 티켓의 유일한 벤더 호출이다(#95 Testing Decisions). code는 1회용이라
// mock으로는 이 계약을 증명할 수 없고, 여기서 실제로 카카오를 친다 — 그래서
// 이 함수를 실제로 실행하는 것은 옵인 live 테스트(#83 live_vendor) 하나뿐이다.
export async function exchangeKakaoCodeForToken(
  config: KakaoOAuthConfig,
  code: string,
): Promise<string> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    client_secret: config.clientSecret,
    redirect_uri: config.redirectUri,
    code,
  });

  const res = await fetch("https://kauth.kakao.com/oauth/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new KakaoTokenExchangeError(`카카오 토큰 교환에 실패했다 (${res.status}): ${text}`);
  }

  const data = (await res.json().catch(() => null)) as { access_token?: unknown } | null;
  if (!data || typeof data.access_token !== "string" || !data.access_token) {
    throw new KakaoTokenExchangeError("카카오 응답에 access_token이 없다.");
  }
  return data.access_token;
}
