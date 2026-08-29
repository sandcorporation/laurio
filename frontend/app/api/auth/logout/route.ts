// 로그아웃 BFF 엔드포인트 (ADR-0016, FE-07 #32).
//
// backend/accounts/api.py의 logout()은 블랙리스트 기록이 실패하면 예외를 그대로
// 던지도록 설계돼 있다("200을 돌려주고도 토큰이 여전히 유효한 상태로 남는 것"을
// 명시적으로 금지) — 그 규율을 여기서 깨지 않는다. 백엔드가 실패를 answer하면
// 이 라우트도 실패로 답하고 쿠키를 지우지 않는다. 백엔드가 성공했을 때만 쿠키를
// 지운다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { backendBaseUrl } from "@/lib/auth/backend";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies } from "@/lib/auth/cookies";
import { safeJson } from "@/lib/auth/http";
import { assertSameOrigin } from "@/lib/auth/origin";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const originDenied = assertSameOrigin(request);
  if (originDenied) return originDenied;

  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!access) {
    // 이미 세션이 없다 — 멱등하게 성공으로 본다. 남아 있을지 모르는 쿠키 부스러기만 지운다.
    const response = NextResponse.json({ status: "ok" });
    clearSessionCookies(response);
    return response;
  }

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  const backendRes = await fetch(`${backendBaseUrl()}/api/auth/logout`, {
    method: "POST",
    headers: { authorization: `Bearer ${access}`, "content-type": "application/json" },
    body: JSON.stringify(refresh ? { refresh } : {}),
    cache: "no-store",
  });

  if (!backendRes.ok) {
    const detail = await safeJson(backendRes);
    return NextResponse.json(detail ?? { detail: "로그아웃에 실패했습니다." }, {
      status: backendRes.status,
    });
  }

  const response = NextResponse.json({ status: "ok" });
  clearSessionCookies(response);
  return response;
}
