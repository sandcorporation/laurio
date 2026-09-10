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

// 204(체크리스트 삭제, #283)·205·304 — `Response`/`NextResponse` 생성자는 이
// 상태 코드에 본문을 실으면 그 자체로 던진다(WHATWG Fetch 표준의 null body
// status). 백엔드가 202바이트짜리 빈 본문을 줘도 그대로 새 Response에
// 넘기면 여기서 500이 된다 — 실제로 체크리스트 항목 삭제(DELETE)가 이걸로
// 막혀 있었다(#283 코드리뷰, 이 저장소 전체에서 처음 204를 낸 엔드포인트라
// 아무도 이 경로를 밟지 않았다).
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

async function handle(request: NextRequest, path: string[]): Promise<NextResponse> {
  const backendPath = sanitizeBackendPath(path);

  if (backendPath === null || !isAllowedBackendPath(backendPath)) {
    return NextResponse.json(NOT_ALLOWED_RESPONSE, { status: 404 });
  }

  const originDenied = assertSameOrigin(request);
  if (originDenied) return originDenied;

  const result = await forwardToBackend(request, backendPath);

  const isNullBodyStatus = NULL_BODY_STATUSES.has(result.response.status);
  const responseBody = isNullBodyStatus ? null : await result.response.arrayBuffer();
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
