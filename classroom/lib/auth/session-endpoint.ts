// 현재 세션 조회 — 공개 앱(frontend/app/api/auth/session/route.ts)과 같은 계약이다
// (#767). `app/api/auth/session/route.ts` 가 이 함수를 그대로 마운트한다.
//
// 강의실 클라이언트(`lib/bff/client.ts`)가 401 을 만나면 이 라우트를 한 번 불러
// 「세션 되살리기」로 삼는다. 액세스가 만료돼 있으면 `resolveAccessToken` 이
// 리프레시 쿠키로 조용히 회전하고 새 쿠키를 이 응답에 싣는다 — 쿠키는 부모
// 도메인(ADR-0038)이라 강의실이 심어도 공개 앱이 같이 읽는다. 회전에 졌을 때
// (형제 요청이 먼저 돌렸을 수 있다, `session.ts` 의 주석) 401 을 내되 쿠키는
// 지우지 않는다 — 다음 시도가 형제가 심은 새 쿠키를 든다. 리프레시까지 만료됐을
// 때만 죽은 쿠키를 정리한다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { backendBaseUrl } from "./backend";
import { REFRESH_COOKIE, clearSessionCookies, setSessionCookies } from "./cookies";
import { safeJson } from "./http";
import { isExpired } from "./jwt";
import { refreshTokenPair } from "./refresh";
import { resolveAccessToken } from "./session";

const UNAUTHENTICATED = { detail: "세션을 확인할 수 없습니다." };

export async function sessionResponse(request: NextRequest): Promise<NextResponse> {
  const resolution = await resolveAccessToken(request);

  if (resolution.status === "unauthenticated") {
    const response = NextResponse.json(UNAUTHENTICATED, { status: 401 });
    if (resolution.shouldClearCookies) clearSessionCookies(response);
    return response;
  }

  const me = (access: string) =>
    fetch(`${backendBaseUrl()}/api/accounts/me`, {
      method: "GET",
      headers: { authorization: `Bearer ${access}` },
      cache: "no-store",
    });

  let refreshedPair = resolution.refreshedPair;
  let backendRes = await me(resolution.accessToken);

  // exp 상 유효해 보이는 액세스를 백엔드가 401 로 거절하는 드문 경우(다른 탭의
  // 로그아웃으로 블랙리스트에 올랐거나 시계가 어긋난 경우) — 공개 앱
  // (frontend/lib/auth/backend-fetch.ts)과 같이, 이번 요청에서 아직 회전하지 않았다면
  // 한 번 더 시도한다. 그 회전까지 실패하면 세션은 정말 죽은 것이라 쿠키를 지운다.
  if (backendRes.status === 401 && !refreshedPair) {
    const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
    if (refresh && !isExpired(refresh)) {
      try {
        refreshedPair = await refreshTokenPair(refresh);
        backendRes = await me(refreshedPair.access);
      } catch {
        const response = NextResponse.json(UNAUTHENTICATED, { status: 401 });
        clearSessionCookies(response);
        return response;
      }
    }
  }

  const body = await safeJson(backendRes);
  const response = NextResponse.json(body ?? UNAUTHENTICATED, { status: backendRes.status });
  if (refreshedPair) setSessionCookies(response, refreshedPair);
  return response;
}
