// 현재 세션 조회(#767) — 공개 앱(frontend/app/api/auth/session/route.ts)과 같은
// 계약. 본문은 lib/auth/session-endpoint.ts 에 있다(순수 함수 시임에서 시험하기
// 위해서다, ADR-0026). `middleware.ts` 의 matcher 가 `api` 를 빼므로 가드 밖이다.
import type { NextRequest } from "next/server";
import type { NextResponse } from "next/server";

import { sessionResponse } from "@/lib/auth/session-endpoint";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest): Promise<NextResponse> {
  return sessionResponse(request);
}
