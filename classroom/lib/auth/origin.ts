// CSRF 방어의 한 축 (ADR-0016) — 공개 앱·운영자 앱과 같은 원칙, 이 앱의 기대
// 오리진만 자기 환경변수(LAURIO_CLASSROOM_ORIGIN)에서 읽는다.
import { assertSameOrigin as assertSameOriginShared } from "@laurio/bff-shared";
import type { NextRequest, NextResponse } from "next/server";

export function assertSameOrigin(request: NextRequest): NextResponse | null {
  return assertSameOriginShared(request, process.env.LAURIO_CLASSROOM_ORIGIN);
}
