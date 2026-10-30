// 세션 쿠키 — 공개 앱(frontend/lib/auth/cookies.ts)과 완전히 같은 모양이다
// (ADR-0038, #273/#276). 강의실은 자기 로그인을 갖지 않는다 — 공개 앱이 발급한
// 이 쿠키가 부모 도메인(.codemit.…)을 타고 여기로 그대로 온다. 그래서 쿠키 이름·
// domain 판정 로직을 새로 발명하지 않고 그대로 옮긴다: 둘이 갈리면 한쪽이 새로
// 굽는 쿠키를 다른 쪽이 못 읽는 사고가 난다.
import type { NextResponse } from "next/server";

import { decodeJwtPayload } from "./jwt";

export const ACCESS_COOKIE = "codemit_access";
export const REFRESH_COOKIE = "codemit_refresh";

/**
 * 로그인 쿠키(access 또는 refresh)가 하나라도 있는가 — "존재"만 본다,
 * 유효성은 언제나 백엔드 몫이다(이 파일 상단 주석과 같은 원칙). 가드
 * (`middleware.ts`)와 루트 분기 판정(`lib/landing/decide-root-view.ts`,
 * #395)이 같은 함수를 써서 같은 기준으로 갈린다.
 */
export function hasSessionCookie(cookies: { has(name: string): boolean }): boolean {
  return cookies.has(ACCESS_COOKIE) || cookies.has(REFRESH_COOKIE);
}

export interface TokenPair {
  access: string;
  refresh: string;
}

export function isDeployedEnvironment(): boolean {
  return process.env.CODEMIT_DEPLOYMENT_TARGET === "production";
}

// 받는 배포 대상은 backend/config/settings.py 의 `_VALID_DEPLOYMENT_TARGETS` 와 같은 두
// 값이고, 비어 있으면 development 다. staging 은 2026-10-30(#836)에 없앴다 — 그 값을
// 포함한 다른 값은 부팅 가드(instrumentation.ts)가 이 함수로 거부한다. 오타 하나가
// 조용히 development 로 흘러 Secure 쿠키와 필수 설정 가드가 꺼지면 안 된다.
const DEPLOYMENT_TARGETS = ["development", "production"];

export function invalidDeploymentTarget(
  target: string | undefined = process.env.CODEMIT_DEPLOYMENT_TARGET,
): string | null {
  if (!target || DEPLOYMENT_TARGETS.includes(target)) return null;
  return (
    `CODEMIT_DEPLOYMENT_TARGET=${target} 는 유효하지 않다. ${DEPLOYMENT_TARGETS.join("·")} 중 ` +
    "하나여야 한다 — 다른 값이 development 로 흐르면 배포 가드가 전부 꺼진다."
  );
}

// dev는 이 값을 비워 둔다 — domain을 주면 localhost 쿠키가 아예 안 붙는다
// (#273의 frontend/lib/auth/cookies.ts와 같은 계약).
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
