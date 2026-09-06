// 구글 OAuth 앱 설정과 code→token 교환(#189). frontend/lib/auth/kakao.ts와 같은
// 모양이다 — authorize/callback 라우트가 provider별로 이 셋(kakao/github/google)
// 중 하나를 골라 쓴다(app/api/auth/social/[provider]/authorize·callback/route.ts).
// 서버 전용 — GOOGLE_CLIENT_SECRET은 이 파일 밖으로, 특히 브라우저로 나가는
// 응답으로는 절대 나가지 않는다(kakao.ts와 같은 이유).
//
// NEXT_PUBLIC_ 접두어를 붙이지 않는다 — 이 세 값은 런타임에 Node 서버 프로세스만
// 읽는다(kakao.ts 독스트링 참고).
export interface GoogleOAuthConfig {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
}

// 셋 중 하나라도 비어 있으면 null — "이 환경에는 구글 앱이 설정되지 않았다"는
// 뜻이다. 호출부는 이 경우 구글로 리다이렉트하지 않고 우리 문구로 돌아간다.
// 로그인 화면의 구글 버튼도 이 함수의 결과(서버에서 판정해 prop으로 내려온
// 값)로 실제 링크와 비활성 "준비 중" 중 무엇을 그릴지 정한다(app/login/page.tsx) —
// GitHub·구글 OAuth 앱을 사람이 등록하고 이 세 값을 채우는 순간, 코드를 더
// 고치지 않아도 버튼이 실제 링크가 된다.
export function readGoogleOAuthConfig(): GoogleOAuthConfig | null {
  const clientId = process.env.GOOGLE_CLIENT_ID ?? "";
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET ?? "";
  const redirectUri = process.env.GOOGLE_REDIRECT_URI ?? "";
  if (!clientId || !clientSecret || !redirectUri) return null;
  return { clientId, clientSecret, redirectUri };
}

export function buildGoogleAuthorizeUrl(config: GoogleOAuthConfig, state: string): string {
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("response_type", "code");
  // backend/accounts/social.py의 GoogleAdapter가 GET
  // https://www.googleapis.com/oauth2/v3/userinfo로 sub·email을 읽는다 —
  // email 스코프가 없으면 응답에 email 필드 자체가 없다.
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("state", state);
  return url.toString();
}

export class GoogleTokenExchangeError extends Error {}

// code는 1회용이라 mock으로는 이 계약을 증명할 수 없다(kakao.ts와 같은 이유) —
// 실제로 실행하는 것은 옵인 live 테스트뿐이다.
export async function exchangeGoogleCodeForToken(
  config: GoogleOAuthConfig,
  code: string,
): Promise<string> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    client_secret: config.clientSecret,
    redirect_uri: config.redirectUri,
    code,
  });

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });

  const rawBody = await res.text();

  if (!res.ok) {
    throw new GoogleTokenExchangeError(`구글 토큰 교환에 실패했다 (${res.status}): ${rawBody}`);
  }

  let data: { access_token?: unknown } | null = null;
  try {
    data = JSON.parse(rawBody) as { access_token?: unknown };
  } catch {
    data = null;
  }

  if (!data || typeof data.access_token !== "string" || !data.access_token) {
    throw new GoogleTokenExchangeError("구글 응답에 access_token이 없다.");
  }
  return data.access_token;
}
