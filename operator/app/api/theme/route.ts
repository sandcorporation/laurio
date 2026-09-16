// 테마 쿠키 쓰기 — 공개 앱·강의실과 완전히 같은 모양이다(#422, #398, ADR-0038과
// 같은 원칙). 쿠키 도메인은 런타임 설정(`CODEMIT_SESSION_COOKIE_DOMAIN`)이라
// 정적으로 구울 수 없어 서버 쪽 경로에서 쓴다.
//
// 로그인 여부와 무관하다 — 비로그인 방문자도 테마를 고를 수 있다(spec #396
// user story 9). 그래서 `assertSameOrigin` 만 지킨다, 인증은 요구하지 않는다
// (운영자 세션 쿠키와 달리 이 쿠키는 `OperatorAuth`를 거치지 않는다).
import { assertSameOrigin } from "@codemit/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { isDeployedEnvironment, sessionCookieDomain } from "@/lib/auth/cookies";
import { THEME_COOKIE, parseThemePreference } from "@/lib/theme/preference";

export const dynamic = "force-dynamic";

const THEME_COOKIE_MAX_AGE_SECONDS = 400 * 24 * 60 * 60; // 400일 — 브라우저 쿠키 만료 상한 근처

export async function POST(request: NextRequest): Promise<NextResponse> {
  const originDenied = assertSameOrigin(request, process.env.CODEMIT_OPERATOR_ORIGIN);
  if (originDenied) return originDenied;

  const body = await request.json().catch(() => null);
  const preference = parseThemePreference(body?.preference);

  const response = NextResponse.json({ preference });
  response.cookies.set(THEME_COOKIE, preference, {
    httpOnly: true,
    sameSite: "lax",
    secure: isDeployedEnvironment(),
    path: "/",
    domain: sessionCookieDomain(),
    maxAge: THEME_COOKIE_MAX_AGE_SECONDS,
  });
  return response;
}
