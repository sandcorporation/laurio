// 허용목록을 통과한 요청을 실제로 백엔드에 전달한다 — 공개 앱
// (frontend/lib/proxy/forward.ts)과 같은 계약이다: 강의실도 JWT 쿠키로 인증하므로
// (ADR-0038) 판정·리프레시 로직이 그대로 같다. 지금은 BACKEND_PROXY_ALLOWLIST가
// 비어 있어(lib/proxy/allowlist.ts) 이 함수가 호출되는 경로가 아직 없지만, 첫
// classroom 엔드포인트가 허용목록에 추가되는 순간 바로 쓰인다.
import type { NextRequest } from "next/server";

import { buildForwardHeaders, extractForwardBody, forwardRequest } from "@codemit/bff-shared";

import { backendBaseUrl, eventsBaseUrl } from "@/lib/auth/backend";
import { REFRESH_COOKIE, type TokenPair } from "@/lib/auth/cookies";
import { isExpired } from "@/lib/auth/jwt";
import { refreshTokenPair } from "@/lib/auth/refresh";
import { resolveAccessToken } from "@/lib/auth/session";

export interface ForwardResult {
  response: Response;
  refreshedPair: TokenPair | null;
  shouldClearCookies: boolean;
}

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
    shouldClearCookies = true;
  }

  // 실시간 신호 SSE(ADR-0046)만 이벤트 서비스로 간다 — 나머지 전부는 지금처럼
  // 동기 API 서버로 간다.
  const base = backendPath.startsWith("/api/classroom/events/") ? eventsBaseUrl() : backendBaseUrl();
  const url = `${base}${backendPath}${request.nextUrl.search}`;
  const body = await extractForwardBody(request);

  // 브라우저가 끊으면 위쪽 요청도 끊는다(2026-09-18) — 끝나지 않는 응답(SSE,
  // ADR-0046)이 이 앱에만 있어서 여기만 신호를 넘긴다. 없으면 탭을 닫거나
  // 새로고침할 때마다 이벤트 서비스에 끝나지 않는 요청이 하나씩 쌓이고, 그
  // 요청이 쥔 DB 연결도 함께 쌓인다(prod 에서 100개까지 갔다).
  let response = await forwardRequest(request.method, url, headers, body, request.signal);

  if (response.status === 401 && resolution.status === "authenticated" && !refreshedPair) {
    const refreshCookie = request.cookies.get(REFRESH_COOKIE)?.value;
    if (refreshCookie && !isExpired(refreshCookie)) {
      try {
        const pair = await refreshTokenPair(refreshCookie);
        headers.set("authorization", `Bearer ${pair.access}`);
        response = await forwardRequest(request.method, url, headers, body, request.signal);
        refreshedPair = pair;
      } catch {
        shouldClearCookies = true;
      }
    }
  }

  return { response, refreshedPair, shouldClearCookies };
}
