// 로그아웃 BFF 엔드포인트 (#306) — 공개 앱(frontend/app/api/auth/logout/route.ts)과
// 같은 계약이다. 강의실은 자기 로그인이 없지만(ADR-0038) 세션 쿠키는 부모
// 도메인을 타고 두 앱이 나눠 쓰므로, 이 앱에서 보낸 로그아웃도 **같은
// access·refresh 토큰**을 블랙리스트에 올린다(backend/accounts/api.py의
// logout()) — 그래서 여기서 로그아웃하면 공개 앱의 세션도 함께 풀린다
// (AC "로그아웃하면 두 앱 모두에서 풀린다").
//
// 백엔드가 실패를 answer하면 이 라우트도 실패로 답하고 쿠키를 지우지 않는다 —
// "200을 돌려주고도 토큰이 여전히 유효한 상태로 남는 것"을 만들지 않는다(공개
// 앱과 같은 규율, ADR-0012).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { assertSameOrigin } from "@/lib/auth/origin";
import { backendBaseUrl } from "@/lib/auth/backend";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies } from "@/lib/auth/cookies";
import { safeJson } from "@/lib/auth/http";

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
