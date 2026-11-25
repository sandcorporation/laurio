// `GET /api/auth/continue`(#1388 D2) — 로그인이 끝난 화면이 여기로 와서, 서버가 세션을
// 확인하고 목적지를 정한다. 목적지는 `resolveLoginDestination` 한 곳에서 정한다.
//
// - 인증됐으면 `303` 으로 목적지에. 리프레시된 쌍이 있으면 응답 쿠키에 싣는다.
// - 아니면 `/login?next=…&next_origin=…` 으로(검증을 통과한 값만 싣는다, `auto` 는 싣지 않는다).
//   죽은 쿠키면 지운다.
// - `auto=1`(공개 앱 /login 의 자동 넘김)이고 형제 목적지면 bounce 쿠키를 심는다.
//
// 라우트 파일(app/api/auth/continue/route.ts)은 이 함수를 부르기만 한다 — 순수 함수
// 시임(vitest)에서 백엔드 호출을 바꿔 끼워 시험하려는 것이다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { fetchBackendAuthenticated as defaultFetchBackendAuthenticated } from "./backend-fetch";
import { clearSessionCookies, isDeployedEnvironment, setSessionCookies } from "./cookies";
import { LOGIN_BOUNCE_COOKIE, LOGIN_BOUNCE_MAX_AGE_SECONDS } from "./login-auto-continue";
import { destinationLocation, resolveLoginDestination } from "./login-destination";

export interface ContinueDeps {
  fetchBackendAuthenticated: typeof defaultFetchBackendAuthenticated;
}

function seeOther(location: string): NextResponse {
  return new NextResponse(null, {
    status: 303,
    headers: { Location: location, "Cache-Control": "no-store" },
  });
}

export async function handleContinue(
  request: NextRequest,
  deps: ContinueDeps = { fetchBackendAuthenticated: defaultFetchBackendAuthenticated },
): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const destination = resolveLoginDestination(searchParams.get("next"), searchParams.get("next_origin"));

  const result = await deps.fetchBackendAuthenticated(request, "/api/accounts/me", { method: "GET" });
  if (result.response.status !== 200) {
    const params = new URLSearchParams({ next: destination.next });
    if (destination.returnOrigin) params.set("next_origin", destination.returnOrigin);
    const response = seeOther(`/login?${params.toString()}`);
    if (result.shouldClearCookies) clearSessionCookies(response);
    return response;
  }

  const response = seeOther(destinationLocation(destination));
  if (result.refreshedPair) setSessionCookies(response, result.refreshedPair);
  // 순환 차단기(#1388 T3, lib/auth/login-auto-continue.ts) — 공개 앱 /login 이 자동으로
  // 형제에게 넘긴 경우에만 심는다. 공개 앱 호스트 전용이라 domain 을 주지 않는다.
  if (searchParams.get("auto") === "1" && destination.returnOrigin) {
    response.cookies.set(LOGIN_BOUNCE_COOKIE, "1", {
      httpOnly: true,
      sameSite: "lax",
      secure: isDeployedEnvironment(),
      path: "/",
      maxAge: LOGIN_BOUNCE_MAX_AGE_SECONDS,
    });
  }
  return response;
}
