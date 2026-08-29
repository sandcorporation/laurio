// 요청 하나에 대해 "지금 쓸 수 있는 액세스 토큰이 무엇인가"를 판정한다. 만료됐으면
// 리프레시 쿠키로 조용히 회전시킨다 — 호출부(라우트 핸들러)는 이 결과의
// refreshedPair를 응답 쿠키에 실어 보내기만 하면 화면이 끊기지 않는다.
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
    // 리프레시도 없거나 이미 만료됐다 — 더 시도할 게 없다. 쿠키가 하나라도
    // 남아 있었다면(죽은 상태로) 응답에서 정리하라고 알린다.
    return { status: "unauthenticated", shouldClearCookies: Boolean(access || refresh) };
  }

  try {
    const pair = await refreshTokenPair(refresh);
    return { status: "authenticated", accessToken: pair.access, refreshedPair: pair };
  } catch {
    // 리프레시도 실패했다 — 로그인으로 보낸다(FE-07 인수조건). 쿠키를 정리해
    // 죽은 토큰이 브라우저에 남아 있지 않게 한다.
    return { status: "unauthenticated", shouldClearCookies: true };
  }
}
