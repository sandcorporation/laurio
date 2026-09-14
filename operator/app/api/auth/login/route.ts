// 운영자 로그인 BFF 엔드포인트 (#63, ADR-0016/0019).
//
// 공개 앱의 소셜 로그인 라우트(frontend/app/api/auth/social/[provider]/login/
// route.ts)와 다른 지점: 여기는 Django 세션 쿠키를 굽는다, JWT 쌍을 굽지 않는다.
import { assertSameOrigin } from "@codemit/bff-shared";
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
  const originDenied = assertSameOrigin(request, process.env.CODEMIT_OPERATOR_ORIGIN);
  if (originDenied) return originDenied;

  const body = await request.text();

  const backendRes = await fetch(`${backendBaseUrl()}/api/operator/login`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: operatorOrigin() },
    body,
    cache: "no-store",
  });

  const payload = await safeJson(backendRes);

  if (!backendRes.ok) {
    return NextResponse.json(payload ?? { detail: "로그인에 실패했습니다." }, {
      status: backendRes.status,
    });
  }

  const sessionValue = extractSessionCookieValue(backendRes);
  if (!sessionValue) {
    // 백엔드는 로그인을 성공(200)시켰는데 이 앱이 세션 쿠키를 못 뽑았다 — 이건
    // 사용자 입력 문제가 아니라 우리 쪽 실패다(코드리뷰 지적). 여기서 그냥
    // payload를 200으로 돌려주면 폼은 성공으로 보고 이동하는데, 쿠키가 없으니
    // 미들웨어가 곧바로 /login으로 되돌리고 에러 문구도 없다 — 사용자에게는
    // "아무 일도 안 일어남"으로 보인다. 명확한 5xx로 실패시켜 화면이 이유를
    // 말하게 한다.
    return NextResponse.json(
      { detail: "로그인 세션을 만드는 데 실패했습니다. 다시 시도해주세요." },
      { status: 502 },
    );
  }

  const response = NextResponse.json(payload ?? { detail: "로그인되었습니다." }, {
    status: backendRes.status,
  });
  setSessionCookie(response, sessionValue);
  return response;
}
