// 연결된 앱 — 토큰 회수(RFC 7009). 백엔드로 그대로 넘긴다(lib/connected-apps/gateway.ts, ADR-0052).
import type { NextRequest, NextResponse } from "next/server";

import { forwardConnectedAppRequest } from "@/lib/connected-apps/gateway";

export const dynamic = "force-dynamic";

const BACKEND_PATH = "/api/classroom/oauth/revoke";

export function GET(request: NextRequest): Promise<NextResponse> {
  return forwardConnectedAppRequest(request, BACKEND_PATH);
}
export function POST(request: NextRequest): Promise<NextResponse> {
  return forwardConnectedAppRequest(request, BACKEND_PATH);
}
export function DELETE(request: NextRequest): Promise<NextResponse> {
  return forwardConnectedAppRequest(request, BACKEND_PATH);
}
