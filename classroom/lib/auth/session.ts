// 요청 하나에 대해 "지금 쓸 수 있는 액세스 토큰이 무엇인가"를 판정한다 — 공개
// 앱(frontend/lib/auth/session.ts)과 같은 계약이다. 만료됐으면 리프레시 쿠키로
// 조용히 회전시킨다.
import type { NextRequest } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE, type TokenPair } from "./cookies";
import { isExpired } from "./jwt";
import { refreshTokenPair } from "./refresh";

export type AccessResolution =
  | { status: "authenticated"; accessToken: string; refreshedPair: TokenPair | null }
  | { status: "unauthenticated"; shouldClearCookies: boolean };

export async function resolveAccessToken(request: NextRequest): Promise<AccessResolution> {
  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;

  if (access && !isExpired(access)) {
    return { status: "authenticated", accessToken: access, refreshedPair: null };
  }

  if (!refresh || isExpired(refresh)) {
    return { status: "unauthenticated", shouldClearCookies: Boolean(access || refresh) };
  }

  try {
    const pair = await refreshTokenPair(refresh);
    return { status: "authenticated", accessToken: pair.access, refreshedPair: pair };
  } catch {
    // 경합 중인 형제 요청이 먼저 회전에 성공했을 수 있다(공개 앱과 같은 이유,
    // frontend/lib/auth/session.ts 주석 참고) — 여기서 쿠키를 지우지 않는다.
    return { status: "unauthenticated", shouldClearCookies: false };
  }
}
