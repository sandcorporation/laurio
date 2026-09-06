// 세 provider(kakao/github/google)의 OAuth 배선을 하나의 표로 모은다(#189,
// 코드리뷰 지적 — authorize/callback route.ts가 각자 이 표를 따로 들고 있으면
// provider를 추가하거나 바꿀 때 두 파일을 손으로 맞춰야 하고, 둘이 어긋나도
// 컴파일러가 잡아주지 않는다). 이 파일 하나가 "provider 문자열 → 실제 함수"
// 매핑의 유일한 원본이다.
//
// 서버 전용이다 — kakao.ts/github.ts/google.ts를 그대로 끌어오므로 클라이언트
// 컴포넌트(app/login/login-form.tsx)에서는 이 파일을 import하지 않는다(그
// 파일들의 client_secret이 브라우저 번들로 새는 것을 막는 경계, kakao.ts
// 독스트링과 같은 이유).
import { buildGithubAuthorizeUrl, exchangeGithubCodeForToken, readGithubOAuthConfig } from "./github";
import { buildGoogleAuthorizeUrl, exchangeGoogleCodeForToken, readGoogleOAuthConfig } from "./google";
import { buildKakaoAuthorizeUrl, exchangeKakaoCodeForToken, readKakaoOAuthConfig } from "./kakao";
import type { SocialProvider } from "./social-providers";

// 세 provider 모듈의 config 인터페이스는 구조적으로 전부 이 모양이다 — 셋을
// 한 표로 다룰 수 있는 이유다.
export interface OAuthProviderConfig {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
}

export interface OAuthProviderAdapter {
  readConfig: () => OAuthProviderConfig | null;
  buildAuthorizeUrl: (config: OAuthProviderConfig, state: string) => string;
  exchangeCodeForToken: (config: OAuthProviderConfig, code: string) => Promise<string>;
}

export const OAUTH_PROVIDER_ADAPTERS: Record<SocialProvider, OAuthProviderAdapter> = {
  kakao: {
    readConfig: readKakaoOAuthConfig,
    buildAuthorizeUrl: buildKakaoAuthorizeUrl,
    exchangeCodeForToken: exchangeKakaoCodeForToken,
  },
  github: {
    readConfig: readGithubOAuthConfig,
    buildAuthorizeUrl: buildGithubAuthorizeUrl,
    exchangeCodeForToken: exchangeGithubCodeForToken,
  },
  google: {
    readConfig: readGoogleOAuthConfig,
    buildAuthorizeUrl: buildGoogleAuthorizeUrl,
    exchangeCodeForToken: exchangeGoogleCodeForToken,
  },
};
