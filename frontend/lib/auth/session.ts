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
    // 이 리프레시 시도가 실패한 이유를 이 요청만으로는 확신할 수 없다 — 진짜
    // 죽은 세션(만료·탈취·로그아웃)일 수도 있지만, 리프레시 토큰이 1회용
    // 회전이라(accounts/tokens.py rotate_refresh_token) 동시에 경합하던 다른
    // 요청이 "방금 막" 같은 토큰으로 먼저 회전에 성공해 이 시도가 진 것일 수도
    // 있다. 후자인데 여기서 쿠키를 지우면, 그 형제 요청이 응답에 실어 보낸
    // 새 쿠키를 이 실패 응답이 나중에 도착해 그대로 덮어써 지워버린다 — 로그인
    // 상태가 실제로는 살아 있는데 이 요청 하나의 실패 때문에 사라지는 것이다
    // (직접 재현해 확인했다: 5개 동시 요청 중 1개가 성공해 새 쿠키를 심어도,
    // 나머지 4개의 실패 응답이 쿠키를 지우면서 최종적으로 쿠키가 하나도 안
    // 남았다). 그래서 여기서는 쿠키를 건드리지 않는다 — 진짜로 죽은 세션이면
    // 이후 요청들도 계속 401을 내고, 클라이언트(lib/auth/client-fetch.ts)가
    // 재시도 끝에 결국 로그인으로 보낸다. 로그아웃(app/api/auth/logout)처럼
    // "이 브라우저가 명시적으로 요청한" 경우에만 쿠키를 지운다.
    return { status: "unauthenticated", shouldClearCookies: false };
  }
}
