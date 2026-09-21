// BFF 프록시 catch-all (ADR-0016, #276) — 공개 앱
// (frontend/app/api/backend/[...path]/route.ts)과 같은 모양이다.
import { sanitizeBackendPath } from "@codemit/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { clearSessionCookies, setSessionCookies } from "@/lib/auth/cookies";
import { assertSameOrigin } from "@/lib/auth/origin";
import { isAllowedBackendPath } from "@/lib/proxy/allowlist";
import { unlessClientLeft } from "@/lib/proxy/client-left";
import { endQuietlyOnUpstreamError } from "@/lib/proxy/event-stream";
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

  // 브라우저가 위쪽 응답 전에 떠났으면 받을 사람이 없다 — 오류로 올리지 않고
  // 빈 응답으로 끝낸다(`lib/proxy/client-left.ts`, GlitchTip 65).
  const result = await unlessClientLeft(request.signal, () => forwardToBackend(request, backendPath));
  if (result === null) return new NextResponse(null, { status: 499 });
  const contentType = result.response.headers.get("content-type") ?? "application/json";

  // 실시간 신호 SSE(ADR-0046)는 끝까지 모이지 않는 응답이다 — 아래
  // `arrayBuffer()`로 버퍼링하면 연결이 끝날 때까지(=영원히) 아무것도
  // 브라우저에 나가지 않는다. 이 콘텐츠 타입일 때만 본문을 그대로
  // ReadableStream으로 중계한다 — 이 백엔드 라우트는 스트림 응답에 204 같은
  // null-body 상태를 절대 내지 않으므로 두 분기가 겹치지 않는다. 배포 중
  // 이벤트 서비스가 끊는 것은 오류가 아니라 스트림의 끝으로 넘긴다
  // (`lib/proxy/event-stream.ts`).
  const isEventStream = contentType.startsWith("text/event-stream");
  const isNullBodyStatus = NULL_BODY_STATUSES.has(result.response.status);
  const responseBody = isEventStream
    ? result.response.body && endQuietlyOnUpstreamError(result.response.body)
    : isNullBodyStatus
      ? null
      : await result.response.arrayBuffer();

  const response = new NextResponse(responseBody, {
    status: result.response.status,
    headers: {
      "content-type": contentType,
      ...(isEventStream
        ? { "cache-control": "no-cache", "x-accel-buffering": "no" }
        : {}),
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
