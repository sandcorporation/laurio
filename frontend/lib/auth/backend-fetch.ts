// 인증이 필요한 백엔드 호출을 대신 실행한다. `/api/auth/session`(FE-07)과
// BFF 프록시 catch-all(FE-08, #33)이 둘 다 이 함수를 쓴다 — 액세스 토큰 판정,
// 만료 시 리프레시, 그리고 "리프레시했는데도 백엔드가 401을 낸 예외적인 경우"의
// 재시도까지 한 곳에 모아, 두 진입점이 각자 다르게 구현해 결함이 갈라지는 일을
// 막는다.
import type { NextRequest } from "next/server";

import { backendBaseUrl } from "./backend";
import { REFRESH_COOKIE, type TokenPair } from "./cookies";
import { isExpired } from "./jwt";
import { refreshTokenPair } from "./refresh";
import { resolveAccessToken } from "./session";

export interface BackendFetchResult {
  response: Response;
  refreshedPair: TokenPair | null;
  shouldClearCookies: boolean;
}

function unauthenticatedResult(shouldClearCookies: boolean): BackendFetchResult {
  return {
    response: new Response(JSON.stringify({ detail: "로그인이 필요합니다." }), {
      status: 401,
      headers: { "content-type": "application/json" },
    }),
    refreshedPair: null,
    shouldClearCookies,
  };
}

export async function fetchBackendAuthenticated(
  request: NextRequest,
  path: string,
  init: { method: string; headers?: HeadersInit; body?: BodyInit | null },
): Promise<BackendFetchResult> {
  const resolution = await resolveAccessToken(request);
  if (resolution.status === "unauthenticated") {
    return unauthenticatedResult(resolution.shouldClearCookies);
  }

  const url = `${backendBaseUrl()}${path}`;
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${resolution.accessToken}`);

  let response = await fetch(url, { ...init, headers, cache: "no-store" });
  let refreshedPair = resolution.refreshedPair;

  // 낙관적 exp 판정(lib/auth/jwt.ts)을 통과한 토큰이 그래도 백엔드에서 401을 받는
  // 드문 경우가 있다 — 다른 탭에서 방금 로그아웃해 블랙리스트에 올랐거나, 서버·클라이언트
  // 시계가 어긋난 경우. 이번 요청에서 아직 리프레시를 하지 않았다면 한 번 더
  // 시도한다. `pending`을 실패로 취급해 되살릴 기회를 날리지 않는다는 원칙과 같은
  // 이유로, "액세스가 exp상 아직 유효해 보인다"는 판정 하나만 믿고 포기하지 않는다.
  if (response.status === 401 && !refreshedPair) {
    const refreshCookie = request.cookies.get(REFRESH_COOKIE)?.value;
    if (refreshCookie && !isExpired(refreshCookie)) {
      try {
        const pair = await refreshTokenPair(refreshCookie);
        headers.set("authorization", `Bearer ${pair.access}`);
        response = await fetch(url, { ...init, headers, cache: "no-store" });
        refreshedPair = pair;
      } catch {
        return unauthenticatedResult(true);
      }
    }
  }

  return { response, refreshedPair, shouldClearCookies: false };
}
