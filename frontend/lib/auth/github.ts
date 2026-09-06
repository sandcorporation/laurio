// GitHub OAuth 앱 설정과 code→token 교환(#189). frontend/lib/auth/kakao.ts와 같은
// 모양이다 — authorize/callback 라우트가 provider별로 이 셋(kakao/github/google)
// 중 하나를 골라 쓴다(app/api/auth/social/[provider]/authorize·callback/route.ts).
// 서버 전용 — GITHUB_CLIENT_SECRET은 이 파일 밖으로, 특히 브라우저로 나가는
// 응답으로는 절대 나가지 않는다(client_secret이 필요한 곳은
// exchangeGithubCodeForToken이 서버에서 GitHub 토큰 엔드포인트를 직접 부르는 이
// 자리 하나뿐이다 — kakao.ts와 같은 이유).
//
// NEXT_PUBLIC_ 접두어를 붙이지 않는다 — 이 세 값은 런타임에 Node 서버 프로세스만
// 읽는다(kakao.ts 독스트링 참고).
export interface GithubOAuthConfig {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
}

// 셋 중 하나라도 비어 있으면 null — "이 환경에는 GitHub 앱이 설정되지 않았다"는
// 뜻이다. 호출부는 이 경우 GitHub로 리다이렉트하지 않고 우리 문구로 돌아간다.
// 로그인 화면의 GitHub 버튼도 이 함수의 결과(서버에서 판정해 prop으로 내려온
// 값)로 실제 링크와 비활성 "준비 중" 중 무엇을 그릴지 정한다(app/login/page.tsx) —
// GitHub·구글 OAuth 앱을 사람이 등록하고 이 세 값을 채우는 순간, 코드를 더
// 고치지 않아도 버튼이 실제 링크가 된다.
export function readGithubOAuthConfig(): GithubOAuthConfig | null {
  const clientId = process.env.GITHUB_CLIENT_ID ?? "";
  const clientSecret = process.env.GITHUB_CLIENT_SECRET ?? "";
  const redirectUri = process.env.GITHUB_REDIRECT_URI ?? "";
  if (!clientId || !clientSecret || !redirectUri) return null;
  return { clientId, clientSecret, redirectUri };
}

export function buildGithubAuthorizeUrl(config: GithubOAuthConfig, state: string): string {
  const url = new URL("https://github.com/login/oauth/authorize");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  // backend/accounts/social.py의 GithubAdapter가 GET https://api.github.com/user로
  // id·email을 읽는다 — email은 기본적으로 비공개일 수 있어 user:email 스코프가
  // 없으면 응답의 email 필드가 null로 온다(#189 유저스토리 12 — 그 공백 자체는
  // 허용된 경우이지만, 사람이 이메일 공개를 켜 둔 경우까지 놓치지 않으려면
  // 스코프를 요청해 둬야 한다).
  url.searchParams.set("scope", "read:user user:email");
  url.searchParams.set("state", state);
  return url.toString();
}

export class GithubTokenExchangeError extends Error {}

// code는 1회용이라 mock으로는 이 계약을 증명할 수 없다(kakao.ts와 같은 이유) —
// 실제로 실행하는 것은 옵인 live 테스트뿐이다.
export async function exchangeGithubCodeForToken(
  config: GithubOAuthConfig,
  code: string,
): Promise<string> {
  const body = new URLSearchParams({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    redirect_uri: config.redirectUri,
    code,
  });

  const res = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      // GitHub의 기본 응답은 form-urlencoded다 — 이 헤더가 없으면 access_token=…
      // 형태로 와서 아래 JSON.parse가 항상 실패한다.
      accept: "application/json",
    },
    body: body.toString(),
    cache: "no-store",
  });

  const rawBody = await res.text();

  if (!res.ok) {
    throw new GithubTokenExchangeError(`GitHub 토큰 교환에 실패했다 (${res.status}): ${rawBody}`);
  }

  let data: { access_token?: unknown; error?: unknown } | null = null;
  try {
    data = JSON.parse(rawBody) as { access_token?: unknown; error?: unknown };
  } catch {
    data = null;
  }

  // GitHub는 잘못된 code에도 HTTP 200을 주고 본문의 error 필드로만 실패를
  // 알린다(Accept: application/json을 보냈을 때 기준) — 카카오·구글처럼 비2xx
  // 상태 코드로 오지 않으므로 여기서 따로 확인한다.
  if (data && typeof data.error === "string") {
    throw new GithubTokenExchangeError(`GitHub 토큰 교환이 거절됐다: ${data.error}`);
  }
  if (!data || typeof data.access_token !== "string" || !data.access_token) {
    throw new GithubTokenExchangeError("GitHub 응답에 access_token이 없다.");
  }
  return data.access_token;
}
