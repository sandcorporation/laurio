// 운영자 로그아웃 BFF 엔드포인트 (#63, ADR-0016/0019).
//
// 세션 쿠키를 "이름으로 골라" Django에 다시 실어 보낸다 — 브라우저가 이 요청에
// 실은 Cookie 헤더 전체를 그대로 중계하지 않는다(#63 인수조건). 이 앱의 쿠키
// 저장소에는 이 세션 쿠키 하나만 있어야 정상이지만, 그 사실에 기대지 않고
// 코드로도 한 값만 골라 쓴다.
import { assertSameOrigin } from "@codemit/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME, clearSessionCookie } from "@/lib/auth/cookies";
import { safeJson } from "@/lib/auth/http";
import { backendBaseUrl, operatorOrigin } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const originDenied = assertSameOrigin(request, process.env.CODEMIT_OPERATOR_ORIGIN);
  if (originDenied) return originDenied;

  const sessionValue = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionValue) {
    // 이미 세션이 없다 — 멱등하게 성공으로 본다(frontend/app/api/auth/logout/
    // route.ts와 같은 관용구). 남아 있을지 모르는 쿠키 부스러기만 지운다.
    const response = NextResponse.json({ status: "ok" });
    clearSessionCookie(response);
    return response;
  }

  const backendRes = await fetch(`${backendBaseUrl()}/api/operator/logout`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: operatorOrigin(),
      cookie: `${SESSION_COOKIE_NAME}=${sessionValue}`,
    },
    cache: "no-store",
  });

  if (!backendRes.ok) {
    const detail = await safeJson(backendRes);
    return NextResponse.json(detail ?? { detail: "로그아웃에 실패했습니다." }, {
      status: backendRes.status,
    });
  }

  const response = NextResponse.json({ status: "ok" });
  clearSessionCookie(response);
  return response;
}
