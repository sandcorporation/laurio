// BFF 프록시 catch-all (ADR-0016, #276) — 공개 앱
// (frontend/app/api/backend/[...path]/route.ts)과 같은 모양이다.
import { sanitizeBackendPath } from "@laurio/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { clearSessionCookies, setSessionCookies } from "@/lib/auth/cookies";
import { assertSameOrigin } from "@/lib/auth/origin";
import { isAllowedBackendPath } from "@/lib/proxy/allowlist";
import { forwardToBackend } from "@/lib/proxy/forward";

export const dynamic = "force-dynamic";

const NOT_ALLOWED_RESPONSE = { detail: "허용되지 않은 경로입니다." } as const;

async function handle(request: NextRequest, path: string[]): Promise<NextResponse> {
  const backendPath = sanitizeBackendPath(path);

  if (backendPath === null || !isAllowedBackendPath(backendPath)) {
    return NextResponse.json(NOT_ALLOWED_RESPONSE, { status: 404 });
  }

  const originDenied = assertSameOrigin(request);
  if (originDenied) return originDenied;

  const result = await forwardToBackend(request, backendPath);

  const responseBody = await result.response.arrayBuffer();
  const response = new NextResponse(responseBody, {
    status: result.response.status,
    headers: {
      "content-type": result.response.headers.get("content-type") ?? "application/json",
    },
  });

  if (result.refreshedPair) {
    setSessionCookies(response, result.refreshedPair);
  } else if (result.shouldClearCookies) {
    clearSessionCookies(response);
  }

  return response;
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return handle(request, (await ctx.params).path);
}
export async function POST(request: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return handle(request, (await ctx.params).path);
}
export async function PUT(request: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return handle(request, (await ctx.params).path);
}
export async function PATCH(request: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return handle(request, (await ctx.params).path);
}
export async function DELETE(request: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return handle(request, (await ctx.params).path);
}
