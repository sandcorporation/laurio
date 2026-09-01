// BFF 프록시 catch-all (#64, ADR-0016/0019/0021).
//
// 공개 앱의 app/api/backend/[...path]/route.ts와 같은 모양이다 — 경로 순회
// 방어·허용목록 검사·Origin 검증·전달 기계는 전부 공유 패키지(packages/
// bff-shared) 것을 쓴다. 다른 것은 두 가지뿐이다: 이 앱의 허용목록 내용
// (lib/proxy/allowlist.ts, 운영자 표면 하나)과, 세션 쿠키를 중계하는 전달
// 방식(lib/proxy/forward.ts).
import { assertSameOrigin, sanitizeBackendPath } from "@laurio/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { forwardToBackend } from "@/lib/proxy/forward";
import { isAllowedBackendPath } from "@/lib/proxy/allowlist";

export const dynamic = "force-dynamic";

const NOT_ALLOWED_RESPONSE = { detail: "허용되지 않은 경로입니다." } as const;

async function handle(request: NextRequest, path: string[]): Promise<NextResponse> {
  // 세그먼트 검사 + 재조립이 허용목록 검사보다 먼저다 — 인코딩된 슬래시(%2f)로
  // 세그먼트 안에 경로 순회를 숨기는 우회를 여기서 원천 차단한다(공개 앱에서
  // 실제로 뚫렸던 그 경로, packages/bff-shared/src/path-safety.ts 상단 주석).
  const backendPath = sanitizeBackendPath(path);

  if (backendPath === null || !isAllowedBackendPath(backendPath)) {
    return NextResponse.json(NOT_ALLOWED_RESPONSE, { status: 404 });
  }

  const originDenied = assertSameOrigin(request, process.env.LAURIO_OPERATOR_ORIGIN);
  if (originDenied) return originDenied;

  const response = await forwardToBackend(request, backendPath);

  const responseBody = await response.arrayBuffer();
  return new NextResponse(responseBody, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
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
