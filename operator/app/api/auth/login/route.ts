// 운영자 로그인 BFF 엔드포인트 (#63, ADR-0016/0019).
//
// 공개 앱의 소셜 로그인 라우트(frontend/app/api/auth/social/[provider]/login/
// route.ts)와 다른 지점: 여기는 Django 세션 쿠키를 굽는다, JWT 쌍을 굽지 않는다.
import { assertSameOrigin } from "@laurio/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { extractSessionCookieValue } from "@/lib/auth/extract-session-cookie";
import { safeJson } from "@/lib/auth/http";
import { setSessionCookie } from "@/lib/auth/cookies";
import { backendBaseUrl, operatorOrigin } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  // 로그인 자체가 변경 요청이다(세션을 새로 만든다) — 백엔드의
  // OperatorOriginMiddleware도 auth=None인 로그인 엔드포인트에 예외를 두지
  // 않는다(core/operator_auth.py 상단 주석): "로그인이야말로 반드시 검증돼야
  // 하는 변경 요청"이기 때문이다. 이 BFF도 같은 원칙을 먼저 지킨다.
  const originDenied = assertSameOrigin(request, process.env.LAURIO_OPERATOR_ORIGIN);
  if (originDenied) return originDenied;

  const body = await request.text();

  const backendRes = await fetch(`${backendBaseUrl()}/api/operator/login`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: operatorOrigin() },
    body,
    cache: "no-store",
  });

  const payload = await safeJson(backendRes);
  const response = NextResponse.json(payload ?? { detail: "로그인에 실패했습니다." }, {
    status: backendRes.status,
  });

  if (backendRes.ok) {
    const sessionValue = extractSessionCookieValue(backendRes);
    if (sessionValue) setSessionCookie(response, sessionValue);
  }

  return response;
}
