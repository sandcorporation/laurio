// 공모전 MCP 의 바깥 주소를 백엔드로 넘긴다 (#870, ADR-0070).
//
// claude.ai 커넥터·Claude Code 는 공개 앱 도메인의 `/mcp`·`/.well-known/oauth-*`·
// `/oauth/{register,token,revoke}` 를 친다 — backend 는 배포에서 호스트 포트가 없어 이 앱이
// 그 요청을 `/api/contests/*` 로 그대로 넘긴다. 강의실 앱의 같은 이름 파일
// (`classroom/lib/connected-apps/gateway.ts`, ADR-0052)과 같은 규칙이다:
//
// - **로그인 쿠키를 읽지 않는다.** 이 경로들은 공개(메타데이터·등록)이거나 앱이 들고 오는
//   자기 토큰(`Authorization: Bearer …`)으로 인증한다.
// - **Origin 검증을 여기서 하지 않는다.** 서버끼리 부르는 요청이고, 실려 오면 백엔드의 MCP
//   엔드포인트가 규격대로 판정한다.
// - **응답 헤더 몇 개를 그대로 돌려준다** — `WWW-Authenticate`·`Retry-After`·`Cache-Control`.
//
// 메타데이터의 주소가 이 앱의 공개 오리진이어야 하므로 그것을 `X-Codemit-Public-Origin` 으로
// 실어 보낸다(배포에서는 백엔드도 같은 `CODEMIT_WEB_ORIGIN` 을 읽는다).
import { buildForwardHeaders, extractForwardBody, forwardRequest, retryWhileConnectionRefused } from "@codemit/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { backendBaseUrl } from "../auth/backend";

const PASS_REQUEST_HEADERS = ["authorization", "accept", "origin", "mcp-protocol-version", "mcp-method", "mcp-name"];
const PASS_RESPONSE_HEADERS = ["content-type", "www-authenticate", "retry-after", "cache-control", "allow"];
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

/** 공개 앱의 바깥 오리진 — 설정이 있으면 그것, 없으면(dev) 요청이 온 호스트. */
export function publicWebOrigin(host: string | null, proto: string | null): string | null {
  const configured = process.env.CODEMIT_WEB_ORIGIN;
  if (configured && configured.trim() !== "") return configured.trim().replace(/\/+$/, "");
  if (!host) return null;
  return `${proto === "https" ? "https" : "http"}://${host}`;
}

export async function forwardConnectedAppRequest(request: NextRequest, backendPath: string): Promise<NextResponse> {
  const headers = buildForwardHeaders(request);
  for (const name of PASS_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  request.headers.forEach((value, name) => {
    if (name.toLowerCase().startsWith("mcp-param-")) headers.set(name, value);
  });
  const origin = publicWebOrigin(request.headers.get("host"), request.headers.get("x-forwarded-proto"));
  if (origin) headers.set("x-codemit-public-origin", origin);

  const body = await extractForwardBody(request);
  const url = `${backendBaseUrl()}${backendPath}${new URL(request.url).search}`;
  const upstream = await retryWhileConnectionRefused(
    () => forwardRequest(request.method, url, headers, body, request.signal),
    { signal: request.signal },
  );

  const responseHeaders = new Headers();
  for (const name of PASS_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const responseBody = NULL_BODY_STATUSES.has(upstream.status) ? null : await upstream.arrayBuffer();
  return new NextResponse(responseBody, { status: upstream.status, headers: responseHeaders });
}

