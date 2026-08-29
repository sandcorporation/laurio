// 현재 세션 조회 (ADR-0016, FE-07 #32).
//
// 인증 구역(app/app/**, ADR-0015)이 마운트될 때 이 엔드포인트로 "누구로 로그인
// 됐는가"를 확인한다. 액세스 토큰이 만료돼 있으면 lib/auth/backend-fetch.ts가
// 조용히 리프레시하고 새 쿠키를 이 응답에 실어 보낸다 — 화면에서는 아무 끊김도
// 보이지 않는다. 리프레시까지 실패하면 401을 내고 죽은 쿠키를 정리한다;
// 클라이언트는 그 401을 보고 /login으로 이동한다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { clearSessionCookies, setSessionCookies } from "@/lib/auth/cookies";
import { fetchBackendAuthenticated } from "@/lib/auth/backend-fetch";
import { safeJson } from "@/lib/auth/http";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const result = await fetchBackendAuthenticated(request, "/api/accounts/me", {
    method: "GET",
  });

  const body = await safeJson(result.response);
  const response = NextResponse.json(body ?? { detail: "세션을 확인할 수 없습니다." }, {
    status: result.response.status,
  });

  if (result.refreshedPair) {
    setSessionCookies(response, result.refreshedPair);
  } else if (result.shouldClearCookies) {
    clearSessionCookies(response);
  }

  return response;
}
