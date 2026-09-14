// 세션 쿠키 — 공개 앱(frontend/lib/auth/cookies.ts)과 완전히 같은 모양이다
// (ADR-0038, #273/#276). 강의실은 자기 로그인을 갖지 않는다 — 공개 앱이 발급한
// 이 쿠키가 부모 도메인(.codemit.…)을 타고 여기로 그대로 온다. 그래서 쿠키 이름·
// domain 판정 로직을 새로 발명하지 않고 그대로 옮긴다: 둘이 갈리면 한쪽이 새로
// 굽는 쿠키를 다른 쪽이 못 읽는 사고가 난다.
import type { NextResponse } from "next/server";

import { decodeJwtPayload } from "./jwt";

export const ACCESS_COOKIE = "codemit_access";
export const REFRESH_COOKIE = "codemit_refresh";

export interface TokenPair {
  access: string;
  refresh: string;
}

export function isDeployedEnvironment(): boolean {
  const target = process.env.CODEMIT_DEPLOYMENT_TARGET;
  return target === "staging" || target === "production";
}

// dev는 이 값을 비워 둔다 — domain을 주면 localhost 쿠키가 아예 안 붙는다
// (#273의 frontend/lib/auth/cookies.ts와 같은 계약).
function sessionCookieDomain(): string | undefined {
  const domain = process.env.CODEMIT_SESSION_COOKIE_DOMAIN;
  return domain ? domain : undefined;
}

function baseCookieAttributes() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: isDeployedEnvironment(),
    path: "/",
    domain: sessionCookieDomain(),
  };
}

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
