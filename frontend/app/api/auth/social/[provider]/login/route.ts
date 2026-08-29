// 소셜 로그인 BFF 엔드포인트 (ADR-0016, FE-07 #32).
//
// 브라우저는 이 라우트만 부른다 — 백엔드의 POST /api/auth/social/{provider}/login이
// 돌려주는 access/refresh 토큰 문자열은 여기서 HttpOnly 쿠키로 바뀌어 응답에
// 실리고, 응답 JSON 본문에는 절대 나가지 않는다. 그래서 브라우저 JS는 토큰을
// 한 번도 볼 수 없다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { backendBaseUrl } from "@/lib/auth/backend";
import { setSessionCookies } from "@/lib/auth/cookies";
import { safeJson } from "@/lib/auth/http";
import { assertSameOrigin } from "@/lib/auth/origin";

export const dynamic = "force-dynamic";

// 백엔드가 실제로 구현한 제공자만 통과시킨다(accounts/social.py의 _REAL_ADAPTERS) —
// 목록이 갈라지면 백엔드는 "unsupported provider"로 401을 내는데, 여기서 먼저
// 걸러 그 왕복 없이 바로 404로 답한다.
const SUPPORTED_PROVIDERS = new Set(["kakao", "github", "google"]);

interface SocialLoginRequestBody {
  access_token?: unknown;
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ provider: string }> },
): Promise<NextResponse> {
  const originDenied = assertSameOrigin(request);
  if (originDenied) return originDenied;

  const { provider } = await context.params;
  if (!SUPPORTED_PROVIDERS.has(provider)) {
    return NextResponse.json({ detail: "지원하지 않는 로그인 방식입니다." }, { status: 404 });
  }

  let body: SocialLoginRequestBody;
  try {
    body = (await request.json()) as SocialLoginRequestBody;
  } catch {
    return NextResponse.json({ detail: "잘못된 요청 본문입니다." }, { status: 400 });
  }

  if (typeof body.access_token !== "string" || !body.access_token) {
    return NextResponse.json({ detail: "access_token이 필요합니다." }, { status: 400 });
  }

  const backendRes = await fetch(`${backendBaseUrl()}/api/auth/social/${provider}/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ access_token: body.access_token }),
    cache: "no-store",
  });

  if (!backendRes.ok) {
    const detail = await safeJson(backendRes);
    return NextResponse.json(detail ?? { detail: "로그인에 실패했습니다." }, {
      status: backendRes.status,
    });
  }

  const pair = (await backendRes.json()) as { access: string; refresh: string };

  // status만 돌려준다 — 토큰은 쿠키에만 실린다.
  const response = NextResponse.json({ status: "ok" });
  setSessionCookies(response, pair);
  return response;
}
