// 허용목록을 통과한 요청을 실제로 백엔드에 전달한다 (ADR-0016, FE-08 #33).
//
// lib/auth/backend-fetch.ts(fetchBackendAuthenticated)와 다른 점: 그쪽은 "인증이
// 필수인 호출"(예: /api/auth/session)을 위한 것이라 세션이 없으면 바로 401을
// 반환한다. 이 프록시는 공개 엔드포인트(auth=None인 /api/contests 등)도 그대로
// 통과시켜야 하므로, 세션이 없어도 요청 자체는 백엔드로 보낸다 — Authorization
// 헤더를 붙이지 않을 뿐이고, 그 엔드포인트가 인증을 요구하면 백엔드가 스스로
// 401을 낸다.
import type { NextRequest } from "next/server";

import { buildForwardHeaders, extractForwardBody, forwardRequest } from "@laurio/bff-shared";

import { backendBaseUrl } from "@/lib/auth/backend";
import { REFRESH_COOKIE, type TokenPair } from "@/lib/auth/cookies";
import { isExpired } from "@/lib/auth/jwt";
import { refreshTokenPair } from "@/lib/auth/refresh";
import { resolveAccessToken } from "@/lib/auth/session";

export interface ForwardResult {
  response: Response;
  refreshedPair: TokenPair | null;
  shouldClearCookies: boolean;
}

// 인증(JWT 쿠키 판정·리프레시)은 이 앱만의 것이라 공유 패키지로 옮기지 않았다
// (ADR-0021, 운영자 앱 04 #62) — 운영자 앱은 세션 쿠키를 이름으로 중계할 뿐
// 이런 판정이 없다. 실제로 fetch를 실행하는 기계(`forwardRequest`)만 공유한다.
export async function forwardToBackend(
  request: NextRequest,
  backendPath: string,
): Promise<ForwardResult> {
  const resolution = await resolveAccessToken(request);

  const headers = buildForwardHeaders(request);

  let refreshedPair: TokenPair | null = null;
  let shouldClearCookies = false;

  if (resolution.status === "authenticated") {
    headers.set("authorization", `Bearer ${resolution.accessToken}`);
    refreshedPair = resolution.refreshedPair;
  } else if (resolution.shouldClearCookies) {
    // 죽은 쿠키가 남아 있었다 — 정리 대상으로 표시하되, 요청 자체는 인증 없이
    // 그대로 통과시킨다(이 경로가 공개 엔드포인트일 수 있다).
    shouldClearCookies = true;
  }

  const url = `${backendBaseUrl()}${backendPath}${request.nextUrl.search}`;
  // 바디는 한 번만 읽는다 — 아래 재시도 경로가 같은 바디를 다시 보낸다
  // (extractForwardBody 주석 참고).
  const body = await extractForwardBody(request);

  let response = await forwardRequest(request.method, url, headers, body);

  // 액세스가 exp상 유효해 보였는데도 백엔드가 401을 낸 드문 경우(다른 탭에서
  // 방금 로그아웃, 시계 오차 등) — 이번 요청에서 아직 리프레시를 안 했다면 한 번
  // 더 시도한다. lib/auth/backend-fetch.ts와 같은 이유로 같은 모양을 반복한다.
  if (response.status === 401 && resolution.status === "authenticated" && !refreshedPair) {
    const refreshCookie = request.cookies.get(REFRESH_COOKIE)?.value;
    if (refreshCookie && !isExpired(refreshCookie)) {
      try {
        const pair = await refreshTokenPair(refreshCookie);
        headers.set("authorization", `Bearer ${pair.access}`);
        response = await forwardRequest(request.method, url, headers, body);
        refreshedPair = pair;
      } catch {
        shouldClearCookies = true;
      }
    }
  }

  return { response, refreshedPair, shouldClearCookies };
}
