// BFF 프록시 catch-all (ADR-0016, FE-08 #33).
//
// 브라우저 → 이 라우트 핸들러 → Django로 흐른다. 파일은 하나지만 통과시킬 경로는
// lib/proxy/allowlist.ts의 명시적 허용목록으로만 정해진다 — 기본은 거부다.
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
  // 세그먼트 검사 + 재조립이 허용목록 검사보다 먼저다 — 인코딩된 슬래시(%2f)로
  // 세그먼트 안에 경로 순회를 숨기는 우회를 여기서 원천 차단한다
  // (packages/bff-shared/src/path-safety.ts 상단 주석에 재현 경로가 있다). sanitizeBackendPath가
  // 돌려주는 문자열이 이후 허용목록 검사와 실제 fetch 양쪽에 동일하게 쓰인다 —
  // "검사한 것과 실행한 것이 다르다"는 이 버그의 근본 원인 자체를 구조로 막는다.
  const backendPath = sanitizeBackendPath(path);

  if (backendPath === null || !isAllowedBackendPath(backendPath)) {
    return NextResponse.json(NOT_ALLOWED_RESPONSE, { status: 404 });
  }

  const originDenied = assertSameOrigin(request);
  if (originDenied) return originDenied;

  const result = await forwardToBackend(request, backendPath);

  // 상태 코드와 본문을 그대로 전달한다 — 화면이 실패 이유를 보여줄 수 있어야
  // 한다(FE-08 인수조건). 본문을 굳이 파싱하지 않고 바이트 그대로 넘긴다.
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
