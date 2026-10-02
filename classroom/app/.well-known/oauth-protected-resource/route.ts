// 연결된 앱 — 보호 자원 메타데이터(RFC 9728). 백엔드로 그대로 넘긴다(lib/connected-apps/gateway.ts, ADR-0052).
import type { NextRequest, NextResponse } from "next/server";

import { forwardConnectedAppRequest } from "@/lib/connected-apps/gateway";

export const dynamic = "force-dynamic";

const BACKEND_PATH = "/api/classroom/oauth/metadata/protected-resource";

export function GET(request: NextRequest): Promise<NextResponse> {
  return forwardConnectedAppRequest(request, BACKEND_PATH);
}
export function POST(request: NextRequest): Promise<NextResponse> {
  return forwardConnectedAppRequest(request, BACKEND_PATH);
}
export function DELETE(request: NextRequest): Promise<NextResponse> {
  return forwardConnectedAppRequest(request, BACKEND_PATH);
}
