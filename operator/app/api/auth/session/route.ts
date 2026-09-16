// 현재 세션 조회 (#63, ADR-0016/0019).
//
// 화면(lib/auth/use-session.ts)이 "누구로 로그인됐는가"를 이걸로 확인한다. 세션
// 쿠키가 아예 없으면 백엔드를 부르지도 않고 401을 낸다 — Django 세션에는 리프레시
// 개념이 없으므로(공개 앱의 JWT와 다르다) 여기서 조용히 갱신할 것이 없다: 액세스가
// 살아 있으면 200, 죽었으면(만료·비활성화) 401 — 백엔드가 그 자리에서 그대로
// 답한다(#45의 즉시 무효화, ADR-0018).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME, clearSessionCookie } from "@/lib/auth/cookies";
import { sessionOutcomeFor } from "@/lib/auth/session-outcome";
import { safeJson } from "@/lib/auth/http";
import { backendBaseUrl } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const sessionValue = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionValue) {
    return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  }

  const backendRes = await fetch(`${backendBaseUrl()}/api/operator/me`, {
    method: "GET",
    headers: { cookie: `${SESSION_COOKIE_NAME}=${sessionValue}` },
    cache: "no-store",
  });

  const body = await safeJson(backendRes);
  // 403(「Operator 권한이 필요합니다」)도 여기서는 401 이다 — 이유는
  // `lib/auth/session-outcome.ts` 가 들고 있다(옛 흰 화면의 원인).
  const outcome = sessionOutcomeFor(backendRes.status);
  const payload = outcome.detail
    ? { detail: outcome.detail }
    : (body ?? { detail: "세션을 확인할 수 없습니다." });
  const response = NextResponse.json(payload, { status: outcome.status });

  if (outcome.clearCookie) clearSessionCookie(response);

  return response;
}
