// 세션 쿠키 — ADR-0016. 토큰은 여기서만 읽고 쓴다. HttpOnly라 브라우저 JS는
// document.cookie로 이 값을 절대 볼 수 없다(FE-07 인수조건).
import type { NextResponse } from "next/server";

import { decodeJwtPayload } from "./jwt";

export const ACCESS_COOKIE = "codemit_access";
export const REFRESH_COOKIE = "codemit_refresh";

export interface TokenPair {
  access: string;
  refresh: string;
}

// staging/production만 Secure를 건다(ADR-0016 인수조건 "Secure(배포 환경)").
// dev는 컨테이너 간 http로만 통신하므로 Secure를 걸면 쿠키가 아예 안 실린다.
// backend/config/settings.py의 CODEMIT_DEPLOYMENT_TARGET과 같은 이름·같은 값
// 규약을 따른다 — ticket FE-13(#38)이 frontend 서비스를 compose.staging/prod.yaml에
// 추가할 때 이 값만 주입하면 된다.
// #93 코드리뷰 — /dev-tokens(진단 화면, app/dev-tokens/page.tsx)가 같은 판정을
// 재사용한다. 배포 환경인지 아닌지는 여기 이름·값 규약이 유일한 출처여야
// 한다(로직이 두 곳에서 어긋나면 안 된다는 원칙 그대로).
export function isDeployedEnvironment(): boolean {
  const target = process.env.CODEMIT_DEPLOYMENT_TARGET;
  return target === "staging" || target === "production";
}

// 부모 도메인(.codemit.…)으로 올려야 강의실 등 형제 서브도메인이 같은 로그인을
// 공유한다(ADR-0038). dev(localhost)는 이 값을 비워 둔다 — domain을 주면 쿠키가
// 아예 안 붙기 때문이다. staging/prod는 compose 파일이 이 값을 주입한다.
//
// **테마 쿠키(#398, `app/api/theme/route.ts`)도 이 함수를 그대로 쓴다** — 로그인
// 쿠키와 다른 도메인 규칙을 새로 만들면 두 쿠키가 다른 서브도메인 집합에만
// 붙는 사고가 난다.
export function sessionCookieDomain(): string | undefined {
  const domain = process.env.CODEMIT_SESSION_COOKIE_DOMAIN;
  return domain ? domain : undefined;
}

function baseCookieAttributes() {
  return {
    httpOnly: true,
    // Lax: 소셜 로그인 콜백처럼 외부 사이트 → 우리 사이트로 돌아오는 top-level GET
    // 내비게이션에서도 쿠키가 살아 있어야 로그인 흐름이 끊기지 않는다. Strict는 이
    // 리다이렉트에서 쿠키를 빼먹어 콜백 처리 자체가 실패한다. CSRF 방어는 Lax
    // 하나로 끝내지 않는다 — Origin 검증(lib/auth/origin.ts)이 반드시 함께 간다
    // (ADR-0016의 성립 조건).
    sameSite: "lax" as const,
    secure: isDeployedEnvironment(),
    path: "/",
    domain: sessionCookieDomain(),
  };
}

// 쿠키 만료를 토큰 자체의 exp에 맞춘다 — ACCESS_TOKEN_TTL_MINUTES/REFRESH_TOKEN_TTL_DAYS
// 값을 프론트가 다시 하드코딩하면 둘이 어긋날 수 있다(백엔드 설정이 바뀌었는데 여기를
// 안 고치는 경우). 토큰에서 직접 읽으면 항상 실제 만료와 같다.
function maxAgeFromToken(token: string, fallbackSeconds: number): number {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp === "number") {
    const remaining = Math.floor(exp - Date.now() / 1000);
    if (remaining > 0) return remaining;
  }
  return fallbackSeconds;
}

const FALLBACK_ACCESS_TTL_SECONDS = 5 * 60;
const FALLBACK_REFRESH_TTL_SECONDS = 14 * 24 * 60 * 60;

export function setSessionCookies(response: NextResponse, pair: TokenPair): void {
  const base = baseCookieAttributes();
  response.cookies.set(ACCESS_COOKIE, pair.access, {
    ...base,
    maxAge: maxAgeFromToken(pair.access, FALLBACK_ACCESS_TTL_SECONDS),
  });
  response.cookies.set(REFRESH_COOKIE, pair.refresh, {
    ...base,
    maxAge: maxAgeFromToken(pair.refresh, FALLBACK_REFRESH_TTL_SECONDS),
  });
}

export function clearSessionCookies(response: NextResponse): void {
  const base = baseCookieAttributes();
  response.cookies.set(ACCESS_COOKIE, "", { ...base, maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...base, maxAge: 0 });
}
